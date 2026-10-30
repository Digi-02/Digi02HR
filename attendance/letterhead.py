"""Safe letterhead image ingestion and the Phase 1 proof PDF renderer."""

from io import BytesIO
import ctypes
import json
import os
import re
import subprocess
import sys
import warnings

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
A4_RATIO = 210 / 297


def sanitize_letterhead(upload):
    """Validate magic, dimensions and decoded format, then return clean bytes."""
    limit = settings.DIGIDOC_LETTERHEAD_MAX_BYTES
    if not upload or upload.size <= 0 or upload.size > limit:
        raise ValidationError("Choose an image no larger than 8 MB.")

    upload.seek(0)
    signature = upload.read(8)
    if signature.startswith(PNG_MAGIC):
        expected_format, output_format, extension = "PNG", "PNG", "png"
    elif signature.startswith(JPEG_MAGIC):
        expected_format, output_format, extension = "JPEG", "JPEG", "jpg"
    else:
        raise ValidationError("Letterheads must be genuine PNG or JPEG images.")

    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            previous_max_pixels = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = settings.DIGIDOC_MAX_IMAGE_PIXELS
            try:
                probe = Image.open(upload)
                if probe.format != expected_format:
                    raise ValidationError("The image signature and decoded image format do not match.")
                width, height = probe.size
                if (width <= 0 or height <= 0 or
                        width > settings.DIGIDOC_MAX_IMAGE_DIMENSION or
                        height > settings.DIGIDOC_MAX_IMAGE_DIMENSION or
                        width * height > settings.DIGIDOC_MAX_IMAGE_PIXELS):
                    raise ValidationError("The image dimensions exceed the safe processing limit.")
                probe.verify()

                upload.seek(0)
                source = Image.open(upload)
                if source.format != expected_format or getattr(source, "n_frames", 1) != 1:
                    raise ValidationError("Animated or multi-frame images are not supported.")
                source.load()
                clean = ImageOps.exif_transpose(source)
                if output_format == "JPEG":
                    clean = clean.convert("RGB")
                elif clean.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    clean = clean.convert("RGBA")

                output = BytesIO()
                options = {"format": output_format, "optimize": True}
                if output_format == "JPEG":
                    options.update(quality=90, progressive=False)
                clean.save(output, **options)
                data = output.getvalue()
                if not data or len(data) > limit:
                    raise ValidationError("The processed letterhead exceeds the 8 MB limit.")
                return data, output_format.lower(), extension, clean.width, clean.height
            finally:
                Image.MAX_IMAGE_PIXELS = previous_max_pixels
    except ValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError("The image dimensions exceed the safe processing limit.")
    except Exception as exc:
        raise ValidationError("The uploaded PNG or JPEG is truncated, corrupt, or unsupported.") from exc
    finally:
        upload.seek(0)


def letterhead_page_css(letterhead, page_mode):
    """Return the trusted @page rules corresponding to the saved print layout."""
    margins = (
        letterhead.margin_top_mm,
        letterhead.margin_right_mm,
        letterhead.margin_bottom_mm,
        letterhead.margin_left_mm,
    )
    common = " ".join(f"{value}mm" for value in margins)
    rule = f"@page {{ size: A4; margin: {common}; }}"
    image_url = "/settings/branding/letterhead/image/"
    fit = "cover" if letterhead.scale_mode == "fill" else "contain"
    if page_mode == "first":
        rule += f"\n@page:first {{ background-image: url('{image_url}'); background-size: {fit}; }}"
    else:
        rule += f"\n@page {{ background-image: url('{image_url}'); background-size: {fit}; }}"
    return rule


def _margins_from_page_css(stylesheet):
    """Read the four integer mm margins from our own tightly-scoped @page rule."""
    match = re.search(r"@page\s*\{([^}]*)\}", stylesheet)
    if not match or not re.search(r"size:\s*A4\s*;", match.group(1), re.I):
        raise ValueError("Invalid trusted A4 page rule")
    margin = re.search(r"margin:\s*(\d+)mm\s+(\d+)mm\s+(\d+)mm\s+(\d+)mm\s*;", match.group(1), re.I)
    if not margin:
        raise ValueError("Invalid trusted A4 margins")
    top, right, bottom, left = (int(value) for value in margin.groups())
    return top, right, bottom, left


def _page_background_settings(stylesheet, page_number):
    """Interpret only our trusted A4 background declarations; never fetch a URL."""
    rules = re.findall(r"@page\s*(:first)?\s*\{([^}]*)\}", stylesheet, re.I)
    for first_selector, body in rules:
        if "background-image:" not in body:
            continue
        if first_selector and page_number != 1:
            continue
        size = re.search(r"background-size:\s*(cover|contain)\s*;", body, re.I)
        return True, size.group(1).lower() if size else "contain"
    return False, "contain"


def _draw_background(pdf, letterhead, scale_mode):
    width, height = A4
    letterhead.image.open("rb")
    try:
        reader = ImageReader(letterhead.image)
        image_width, image_height = reader.getSize()
        if scale_mode == "cover":
            scale = max(width / image_width, height / image_height)
        else:
            scale = min(width / image_width, height / image_height)
        draw_width, draw_height = image_width * scale, image_height * scale
        x, y = (width - draw_width) / 2, (height - draw_height) / 2

        pdf.saveState()
        clip = pdf.beginPath()
        clip.rect(0, 0, width, height)
        pdf.clipPath(clip, stroke=0, fill=0)
        pdf.drawImage(reader, x, y, width=draw_width, height=draw_height, mask="auto")
        pdf.restoreState()
    finally:
        letterhead.image.close()


def render_sample_pdf(letterhead, page_mode="every"):
    """Create a two-page A4 sample with the uploaded art used as page artwork."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, pageCompression=1, invariant=1)
    pdf.setTitle("DigiDoc letterhead sample")
    pdf.setAuthor("")
    pdf.setSubject("")
    pdf.setCreator("")
    pdf._doc.info.producer = ""

    page_width, page_height = A4
    stylesheet = letterhead_page_css(letterhead, page_mode)
    top_mm, right_mm, bottom_mm, left_mm = _margins_from_page_css(
        stylesheet
    )
    left = left_mm * 72 / 25.4
    right = right_mm * 72 / 25.4
    top = top_mm * 72 / 25.4
    bottom = bottom_mm * 72 / 25.4
    for page_number in (1, 2):
        draw_background, background_fit = _page_background_settings(stylesheet, page_number)
        if draw_background:
            _draw_background(pdf, letterhead, background_fit)
        # The artwork can be dark or busy where the saved content area begins.
        # Keep the sample labels readable without hiding the surrounding art.
        pdf.saveState()
        pdf.setFillAlpha(1)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.rect(left, page_height - top - 29, page_width - left - right, 38, fill=1, stroke=0)
        pdf.restoreState()
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(left, page_height - top, "Letterhead sample")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(left, page_height - top - 22, f"Page {page_number} · saved margins")
        pdf.setStrokeColorRGB(0.55, 0.55, 0.55)
        pdf.setLineWidth(0.5)
        pdf.rect(left, bottom, page_width - left - right, page_height - top - bottom)
        pdf.showPage()
    pdf.save()
    result = buffer.getvalue()
    if len(result) > 25 * 1024 * 1024:
        raise ValueError("The sample PDF exceeds the output size limit.")
    return result


def _assign_windows_job_limit(process, memory_limit=512 * 1024 * 1024):
    """Put the worker in a Windows Job Object with a hard per-process cap."""
    if os.name != "nt":
        return None

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    from ctypes import wintypes
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "Could not create the PDF worker job.")
    process_handle = None
    try:
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x00000100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        limits.ProcessMemoryLimit = memory_limit
        if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise OSError(ctypes.get_last_error(), "Could not set the PDF worker memory cap.")
        process_handle = kernel32.OpenProcess(0x0100 | 0x0001, False, process.pid)
        if not process_handle:
            raise OSError(ctypes.get_last_error(), "Could not open the PDF worker process.")
        if not kernel32.AssignProcessToJobObject(job, process_handle):
            raise OSError(ctypes.get_last_error(), "Could not enforce the PDF worker memory cap.")
        return job
    except Exception:
        kernel32.CloseHandle(job)
        raise
    finally:
        if process_handle:
            kernel32.CloseHandle(process_handle)


def render_sample_pdf_isolated(letterhead, page_mode="every"):
    """Render a sample in a timed, memory-limited child process."""
    if page_mode not in {"every", "first"}:
        raise ValueError("Unsupported letterhead page mode.")
    with letterhead.image.open("rb") as image_file:
        image_bytes = image_file.read(settings.DIGIDOC_LETTERHEAD_MAX_BYTES + 1)
    if not image_bytes or len(image_bytes) > settings.DIGIDOC_LETTERHEAD_MAX_BYTES:
        raise ValueError("The stored letterhead exceeds the sample input limit.")

    metadata = {
        "image_format": letterhead.image_format,
        "image_width": letterhead.image_width,
        "image_height": letterhead.image_height,
        "scale_mode": letterhead.scale_mode,
        "default_page_mode": letterhead.default_page_mode,
        "margin_top_mm": letterhead.margin_top_mm,
        "margin_bottom_mm": letterhead.margin_bottom_mm,
        "margin_left_mm": letterhead.margin_left_mm,
        "margin_right_mm": letterhead.margin_right_mm,
        "page_mode": page_mode,
    }
    payload = json.dumps(metadata, separators=(",", ":")).encode("utf-8") + b"\n" + image_bytes
    worker_env = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if name in os.environ
    }
    worker_env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [sys.executable, "-m", "attendance.letterhead_worker"],
        cwd=str(settings.BASE_DIR), env=worker_env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    job_handle = None
    try:
        job_handle = _assign_windows_job_limit(process)
        output, _ = process.communicate(payload, timeout=20)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise ValueError("PDF rendering timed out.") from exc
    except Exception:
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise
    finally:
        if job_handle:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job_handle)
    if process.returncode != 0:
        raise ValueError("PDF rendering failed in the isolated worker.")
    if not output or len(output) > 25 * 1024 * 1024:
        raise ValueError("The sample PDF exceeds the output size limit.")
    return output

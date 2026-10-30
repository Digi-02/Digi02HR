"""Company-scoped DigiDoc document views and strict editor JSON handling."""

import html
import json
import re
import secrets
import unicodedata
import uuid
import base64
import ctypes
import os
import subprocess
import sys
import zipfile
from types import SimpleNamespace
from urllib.parse import quote
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import json_script
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Image as PdfImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .digidoc_exports import docx as export_docx, odt as export_odt, plain_text as export_text, rtf_text as export_rtf
from .models import AuditLog, CompanyLetterhead, DigiDocDocument, DigiDocImageAsset
from .organization import get_active_organization, user_has_hr_access
from .shell import shell_context


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 20
MAX_NODES = 10000
MAX_TITLE = 200
ALLOWED_TYPES = {"doc", "paragraph", "heading", "text", "hardBreak", "horizontalRule", "bulletList", "orderedList", "listItem", "table", "tableRow", "tableCell", "image"}
ALLOWED_MARKS = {"bold", "italic", "underline", "strike", "link", "fontFamily", "fontSize", "textColor", "highlight"}
ALIGNMENTS = {"left", "center", "right", "justify"}
FONT_FAMILIES = {
    "Helvetica", "Times-Roman", "Courier", "Roboto", "Open Sans", "Lato",
    "Montserrat", "Merriweather", "Nunito", "Oswald", "Source Sans 3",
    "Poppins", "Playfair Display", "Roboto Mono", "Inter",
}
FONT_SIZE_VALUES = {8, 9, 10, 11, 12, 14, 16, 18, 24, 36, 48}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LINE_SPACING = {"single", "1.15", "1.5", "double"}
CHILDREN = {
    "doc": {"paragraph", "heading", "bulletList", "orderedList", "table", "image", "hardBreak", "horizontalRule"},
    "paragraph": {"text", "hardBreak", "image"}, "heading": {"text", "hardBreak"},
    "bulletList": {"listItem"}, "orderedList": {"listItem"},
    "listItem": {"paragraph", "bulletList", "orderedList"},
    "table": {"tableRow"}, "tableRow": {"tableCell"}, "tableCell": {"text", "hardBreak"},
}


def _scope(request):
    organization = get_active_organization(request)
    if not organization or not user_has_hr_access(request.user, organization):
        raise PermissionDenied
    return organization


def _clean_title(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) not in {"Cc", "Cf", "Cs"})
    return " ".join(value.split())[:MAX_TITLE] or "Untitled document"


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValidationError("Invalid document link.")
    if not re.match(r"^(https?://|mailto:)[^\s<>]+$", value, re.I):
        raise ValidationError("Only web and email links are allowed.")
    return value


def validate_document_json(value):
    """Accept only the small, typed document tree understood by this editor."""
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValidationError("The document data is invalid.") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise ValidationError("The document exceeds the 2 MB limit.")
    count = [0]
    image_count = [0]

    def visit(node, depth=0):
        count[0] += 1
        if count[0] > MAX_NODES or depth > MAX_DEPTH or not isinstance(node, dict):
            raise ValidationError("The document structure is too large or deeply nested.")
        kind = node.get("type")
        if not isinstance(kind, str) or kind not in ALLOWED_TYPES:
            raise ValidationError("Unsupported document element.")
        allowed_keys = {"type", "content"}
        if kind == "text":
            allowed_keys |= {"text", "marks"}
        if kind == "heading":
            allowed_keys |= {"level", "content", "attrs"}
        if kind in {"paragraph", "tableCell"}:
            allowed_keys |= {"attrs"}
        if kind == "image":
            allowed_keys |= {"attrs"}
        if set(node) - allowed_keys:
            raise ValidationError("Unsupported document property.")
        cleaned = {"type": kind}
        if kind == "text":
            text = node.get("text", "")
            if not isinstance(text, str) or len(text) > 100000:
                raise ValidationError("Text is too long.")
            cleaned["text"] = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf", "Cs"})
            marks = node.get("marks", [])
            if not isinstance(marks, list) or len(marks) > 8:
                raise ValidationError("Invalid text formatting.")
            clean_marks = []
            for mark in marks:
                if not isinstance(mark, dict) or not isinstance(mark.get("type"), str) or mark.get("type") not in ALLOWED_MARKS or set(mark) - {"type", "attrs"}:
                    raise ValidationError("Unsupported text formatting.")
                item = {"type": mark["type"]}
                if mark["type"] == "link":
                    attrs = mark.get("attrs")
                    if not isinstance(attrs, dict) or set(attrs) != {"href"}:
                        raise ValidationError("Invalid link formatting.")
                    item["attrs"] = {"href": _safe_url(attrs["href"])}
                elif mark["type"] in {"fontFamily", "fontSize", "textColor", "highlight"}:
                    attrs = mark.get("attrs")
                    key = {"fontFamily": "value", "fontSize": "value", "textColor": "color", "highlight": "color"}[mark["type"]]
                    if not isinstance(attrs, dict) or set(attrs) != {key}:
                        raise ValidationError("Invalid text formatting.")
                    value = attrs[key]
                    if mark["type"] == "fontFamily" and (not isinstance(value, str) or value not in FONT_FAMILIES):
                        raise ValidationError("Unsupported font family.")
                    if mark["type"] == "fontSize" and (type(value) is not int or value not in FONT_SIZE_VALUES):
                        raise ValidationError("Unsupported font size.")
                    if mark["type"] in {"textColor", "highlight"} and (not isinstance(value, str) or not COLOR_RE.fullmatch(value)):
                        raise ValidationError("Unsupported text colour.")
                    item["attrs"] = {key: value.upper() if key == "color" else value}
                elif "attrs" in mark:
                    raise ValidationError("Unsupported formatting property.")
                clean_marks.append(item)
            if clean_marks:
                cleaned["marks"] = clean_marks
            return cleaned
        if kind == "heading":
            level = node.get("level", 1)
            if type(level) is not int or level not in {1, 2, 3}:
                raise ValidationError("Unsupported heading level.")
            cleaned["level"] = level
        attrs = node.get("attrs")
        if kind == "image" and attrs is None:
            raise ValidationError("Image references are required.")
        if attrs is not None:
            if not isinstance(attrs, dict):
                raise ValidationError("Unsupported element property.")
            if kind == "image":
                if not {"asset_id", "alt"} <= set(attrs) or set(attrs) - {"asset_id", "alt", "width_percent", "align", "crop"}:
                    raise ValidationError("Invalid image reference.")
                try:
                    asset_id = str(uuid.UUID(str(attrs["asset_id"])))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValidationError("Invalid image reference.") from exc
                alt = attrs.get("alt", "")
                if not isinstance(alt, str) or len(alt) > 300:
                    raise ValidationError("Invalid image description.")
                image_count[0] += 1
                if image_count[0] > 30:
                    raise ValidationError("A document can contain up to 30 images.")
                width_percent = attrs.get("width_percent", 100)
                alignment = attrs.get("align", "center")
                crop = attrs.get("crop", "none")
                if type(width_percent) is not int or not 10 <= width_percent <= 100:
                    raise ValidationError("Image width must be between 10 and 100 percent.")
                if not isinstance(alignment, str) or alignment not in {"left", "center", "right"}:
                    raise ValidationError("Unsupported image alignment.")
                if not isinstance(crop, str) or crop not in {"none", "square", "landscape", "portrait"}:
                    raise ValidationError("Unsupported image crop shape.")
                cleaned["attrs"] = {
                    "asset_id": asset_id,
                    "alt": "".join(ch for ch in alt if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf", "Cs"}),
                    "width_percent": width_percent,
                    "align": alignment,
                    "crop": crop,
                }
            else:
                if set(attrs) - {"align", "indent", "line_spacing"}:
                    raise ValidationError("Unsupported element property.")
                clean_attrs = {}
                if "align" in attrs:
                    if not isinstance(attrs["align"], str) or attrs["align"] not in ALIGNMENTS:
                        raise ValidationError("Unsupported alignment.")
                    clean_attrs["align"] = attrs["align"]
                if "indent" in attrs:
                    if type(attrs["indent"]) is not int or attrs["indent"] not in range(5):
                        raise ValidationError("Unsupported paragraph indent.")
                    clean_attrs["indent"] = attrs["indent"]
                if "line_spacing" in attrs:
                    if not isinstance(attrs["line_spacing"], str) or attrs["line_spacing"] not in LINE_SPACING:
                        raise ValidationError("Unsupported line spacing.")
                    clean_attrs["line_spacing"] = attrs["line_spacing"]
                cleaned["attrs"] = clean_attrs
        children = node.get("content", [])
        if not isinstance(children, list) or len(children) > MAX_NODES:
            raise ValidationError("Invalid document contents.")
        if kind in {"doc", "paragraph", "heading", "bulletList", "orderedList", "listItem", "table", "tableRow", "tableCell"}:
            allowed_children = CHILDREN.get(kind, set())
            if any(not isinstance(child, dict) or not isinstance(child.get("type"), str) or child.get("type") not in allowed_children for child in children):
                raise ValidationError("This document element contains an unsupported child.")
            if kind == "table" and len(children) > 100:
                raise ValidationError("A table can have up to 100 rows.")
            if kind == "tableRow" and len(children) > 20:
                raise ValidationError("A table row can have up to 20 cells.")
            cleaned["content"] = [visit(child, depth + 1) for child in children]
        elif children:
            raise ValidationError("This element cannot have child content.")
        return cleaned

    result = visit(value)
    if result["type"] != "doc":
        raise ValidationError("Invalid document root.")
    return result


def _ensure_company_images(content, organization):
    image_ids = []
    def walk(node):
        if node["type"] == "image": image_ids.append(node["attrs"]["asset_id"])
        for child in node.get("content", []): walk(child)
    walk(content)
    found = set(str(value) for value in DigiDocImageAsset.objects.filter(organization=organization, pk__in=image_ids).values_list("pk", flat=True))
    if found != set(image_ids):
        raise ValidationError("One or more document images are unavailable.")


def _doc_context(request, organization, **extra):
    return {"organization": organization, "page_title": "DigiDoc", **shell_context(request, organization), **extra}


@login_required
def digidoc_list(request):
    organization = _scope(request)
    query = _clean_title(request.GET.get("q", "")) if request.GET.get("q") else ""
    documents = DigiDocDocument.objects.filter(organization=organization)
    if query:
        documents = documents.filter(title__icontains=query)
    return render(request, "attendance/digidoc_list.html", _doc_context(request, organization, documents=documents, query=query))


@login_required
@require_POST
def digidoc_create(request):
    organization = _scope(request)
    letterhead = CompanyLetterhead.objects.filter(organization=organization).first()
    doc = DigiDocDocument.objects.create(
        organization=organization,
        created_by=request.user,
        title="Untitled document",
        content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
        letterhead_enabled=bool(letterhead and letterhead.image),
        letterhead_page_mode=letterhead.default_page_mode if letterhead else "every",
    )
    return redirect("digidoc_editor", document_id=doc.pk)


@login_required
@ensure_csrf_cookie
def digidoc_editor(request, document_id):
    organization = _scope(request)
    doc = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization)
    try:
        content = validate_document_json(doc.content_json)
    except ValidationError:
        content = {"type": "doc", "content": [{"type": "paragraph", "content": []}]}
    letterhead = CompanyLetterhead.objects.filter(organization=organization).first()
    nonce = secrets.token_urlsafe(18)
    safe_json_script = str(json_script(content, "dd-initial")).replace("<script ", f'<script nonce="{nonce}" ', 1)
    response = render(request, "attendance/digidoc_editor.html", _doc_context(request, organization, document=doc, initial_json_script=safe_json_script, letterhead=letterhead, letterhead_image_url=reverse("company_letterhead_image"), branding_url=reverse("organization_branding"), csp_nonce=nonce))
    response["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-{nonce}'; img-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    response["X-Frame-Options"] = "DENY"
    response["Referrer-Policy"] = "same-origin"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def digidoc_save(request, document_id):
    organization = _scope(request)
    doc = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization)
    if len(request.body) > MAX_JSON_BYTES + 4096:
        return JsonResponse({"error": "The document exceeds the 2 MB limit."}, status=413)
    rate_key = f"digidoc:save:{organization.pk}:{request.user.pk}"
    cache.add(rate_key, 0, timeout=60)
    try:
        if cache.incr(rate_key) > 120:
            return JsonResponse({"error": "Autosave rate limit reached. Try again shortly."}, status=429)
    except ValueError:
        cache.set(rate_key, 1, timeout=60)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) - {"title", "content", "letterhead_enabled", "letterhead_page_mode", "version"}:
            raise ValidationError("Unsupported save request.")
        content = validate_document_json(payload.get("content"))
        _ensure_company_images(content, organization)
        expected_version = payload.get("version")
        if type(expected_version) is not int:
            raise ValidationError("Document version is invalid.")
        title = _clean_title(payload.get("title"))
        enabled = payload.get("letterhead_enabled", False)
        mode = payload.get("letterhead_page_mode", "every")
        if type(enabled) is not bool or mode not in {"every", "first"}:
            raise ValidationError("Invalid letterhead settings.")
        if enabled and not CompanyLetterhead.objects.filter(organization=organization).exists():
            raise ValidationError("This company has no saved letterhead.")
        with transaction.atomic():
            doc = get_object_or_404(DigiDocDocument.objects.select_for_update(), pk=document_id, organization=organization)
            if expected_version != doc.version:
                return JsonResponse({"error": "This document changed in another session. Reload before saving."}, status=409)
            doc.title, doc.content_json = title, content
            doc.letterhead_enabled, doc.letterhead_page_mode = enabled, mode
            doc.version += 1
            doc.save(update_fields=["title", "content_json", "letterhead_enabled", "letterhead_page_mode", "version", "updated_at"])
        return JsonResponse({"ok": True, "version": doc.version, "updated_at": timezone.localtime(doc.updated_at).strftime("%I:%M %p").lstrip("0")})
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else "Invalid save request."
        return JsonResponse({"error": message}, status=400)


@login_required
@require_POST
def digidoc_duplicate(request, document_id):
    organization = _scope(request)
    original = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization)
    doc = DigiDocDocument.objects.create(organization=organization, created_by=request.user, title=_clean_title("Copy of " + original.title), content_json=original.content_json, letterhead_enabled=original.letterhead_enabled, letterhead_page_mode=original.letterhead_page_mode)
    return redirect("digidoc_editor", document_id=doc.pk)


@login_required
@require_POST
def digidoc_delete(request, document_id):
    organization = _scope(request)
    doc = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization)
    doc.delete()
    return redirect("digidoc_list")


@login_required
@require_POST
def digidoc_image_upload(request):
    organization = _scope(request)
    upload = request.FILES.get("image")
    if not upload or upload.size <= 0 or upload.size > 8 * 1024 * 1024:
        return JsonResponse({"error": "Choose a PNG or JPEG image no larger than 8 MB."}, status=400)
    recent_uploads = AuditLog.objects.filter(actor=request.user, action="digidoc.image_uploaded", created_at__gte=timezone.now()-timedelta(hours=1)).count()
    if recent_uploads >= 10:
        return JsonResponse({"error": "Upload limit reached for this hour."}, status=429)
    usage = 0
    for asset in DigiDocImageAsset.objects.filter(organization=organization).only("image"):
        try: usage += asset.image.size
        except OSError: pass
    if usage + upload.size > 100 * 1024 * 1024:
        return JsonResponse({"error": "The company DigiDoc image storage limit has been reached."}, status=413)
    from .letterhead import sanitize_letterhead
    try:
        data, image_format, _extension, width, height = sanitize_letterhead(upload)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)
    asset = DigiDocImageAsset(organization=organization, uploaded_by=request.user, image_format=image_format, image_width=width, image_height=height)
    asset.image.save("asset.png" if image_format == "png" else "asset.jpg", ContentFile(data), save=True)
    AuditLog.objects.create(organization=organization, actor=request.user, area="organization", action="digidoc.image_uploaded", target_model="DigiDocImageAsset", target_id=str(asset.pk), summary="Uploaded a DigiDoc image asset.", metadata={"format": image_format, "size": len(data)})
    return JsonResponse({"id": str(asset.pk), "url": reverse("digidoc_image", args=[asset.pk]), "alt": ""})


@login_required
def digidoc_image(request, asset_id):
    organization = _scope(request)
    asset = get_object_or_404(DigiDocImageAsset, pk=asset_id, organization=organization)
    try:
        with asset.image.open("rb") as image_file:
            data = image_file.read(8 * 1024 * 1024 + 1)
    except OSError:
        return HttpResponse(status=404)
    if len(data) > 8 * 1024 * 1024:
        return HttpResponse(status=404)
    response = HttpResponse(data, content_type="image/png" if asset.image_format == "png" else "image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def _paragraph_html(node):
    if node["type"] == "text":
        value = html.escape(node.get("text", "")).replace("\n", "<br/>")
        for mark in node.get("marks", []):
            kind = mark["type"]
            if kind == "bold": value = f"<b>{value}</b>"
            elif kind == "italic": value = f"<i>{value}</i>"
            elif kind == "underline": value = f"<u>{value}</u>"
            elif kind == "strike": value = f"<strike>{value}</strike>"
            elif kind == "link": value = f'<link href="{html.escape(mark["attrs"]["href"], quote=True)}" color="#2457b2">{value}</link>'
            elif kind == "fontFamily": value = f'<font name="{mark["attrs"]["value"]}">{value}</font>'
            elif kind == "fontSize": value = f'<font size="{mark["attrs"]["value"]}">{value}</font>'
            elif kind == "textColor": value = f'<font color="{mark["attrs"]["color"]}">{value}</font>'
            elif kind == "highlight": value = f'<font backColor="{mark["attrs"]["color"]}">{value}</font>'
        return value
    return "".join(_paragraph_html(child) for child in node.get("content", []))


def _build_pdf(doc, organization=None, *, pdf_assets=None, letterhead_bytes=None, letterhead_meta=None):
    font_dir = os.path.join(os.path.dirname(__file__), "static", "attendance", "fonts")
    for family, slug in (("Roboto", "roboto"), ("Open Sans", "open-sans"), ("Lato", "lato"), ("Montserrat", "montserrat"), ("Merriweather", "merriweather"), ("Nunito", "nunito"), ("Oswald", "oswald"), ("Source Sans 3", "source-sans-3"), ("Poppins", "poppins"), ("Playfair Display", "playfair-display"), ("Roboto Mono", "roboto-mono"), ("Inter", "inter")):
        regular = os.path.join(font_dir, f"{slug}-400.ttf")
        bold = os.path.join(font_dir, f"{slug}-700.ttf")
        if os.path.isfile(regular) and os.path.isfile(bold):
            pdfmetrics.registerFont(TTFont(family, regular))
            pdfmetrics.registerFont(TTFont(f"{family}-Bold", bold))
            pdfmetrics.registerFontFamily(family, normal=family, bold=f"{family}-Bold", italic=family, boldItalic=f"{family}-Bold")
    content = validate_document_json(doc.content_json)
    if letterhead_meta is not None:
        letterhead = SimpleNamespace(**letterhead_meta) if doc.letterhead_enabled else None
    else:
        letterhead = CompanyLetterhead.objects.filter(organization=organization).first() if doc.letterhead_enabled else None
    if doc.letterhead_enabled and not letterhead:
        raise ValidationError("The saved letterhead is unavailable.")
    margins = (25, 20, 25, 20)
    if letterhead:
        margins = (letterhead.margin_top_mm, letterhead.margin_right_mm, letterhead.margin_bottom_mm, letterhead.margin_left_mm)
    buffer = BytesIO()
    top, right, bottom, left = margins
    pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=left*mm, rightMargin=right*mm, topMargin=top*mm, bottomMargin=bottom*mm, title=_clean_title(doc.title), pageCompression=1)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DigiDocH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=20, leading=25, spaceBefore=8, spaceAfter=8))
    styles.add(ParagraphStyle(name="DigiDocH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=16, leading=20, spaceBefore=7, spaceAfter=6))
    styles.add(ParagraphStyle(name="DigiDocH3", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=13, leading=17, spaceBefore=6, spaceAfter=5))
    alignments = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
    flow = []

    def blocks(nodes):
        for node in nodes:
            kind = node["type"]
            if kind == "image":
                if pdf_assets is not None:
                    image_data = pdf_assets.get(node["attrs"]["asset_id"], b"")
                else:
                    asset = get_object_or_404(DigiDocImageAsset, pk=node["attrs"]["asset_id"], organization=organization)
                    with asset.image.open("rb") as image_file:
                        image_data = image_file.read(8 * 1024 * 1024 + 1)
                if len(image_data) > 8 * 1024 * 1024:
                    raise ValidationError("A document image is unavailable.")
                attrs = node["attrs"]
                crop_ratio = {"square": 1, "landscape": 16 / 9, "portrait": 3 / 4}.get(attrs.get("crop", "none"))
                if crop_ratio:
                    from PIL import Image, ImageOps
                    with Image.open(BytesIO(image_data)) as source_image:
                        cropped = ImageOps.fit(source_image.convert("RGB"), (1200, max(1, round(1200 / crop_ratio))), centering=(0.5, 0.5))
                        image_buffer = BytesIO()
                        cropped.save(image_buffer, format="JPEG", quality=90, optimize=True)
                        image_data = image_buffer.getvalue()
                image_flow = PdfImage(BytesIO(image_data))
                max_width, max_height = A4[0] - (left + right) * mm, A4[1] - (top + bottom) * mm
                max_width *= attrs.get("width_percent", 100) / 100
                scale = min(max_width / image_flow.imageWidth, max_height / image_flow.imageHeight, 1)
                image_flow.drawWidth = image_flow.imageWidth * scale
                image_flow.drawHeight = image_flow.imageHeight * scale
                image_flow.hAlign = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}.get(attrs.get("align", "center"), "CENTER")
                flow.extend([image_flow, Spacer(1, 8)])
                continue
            if kind in {"paragraph", "heading", "tableCell"}:
                text = _paragraph_html(node)
                attrs = node.get("attrs", {})
                if kind == "heading":
                    base_style = styles[f"DigiDocH{node['level']}"]
                    base_size = base_style.fontSize
                    leading_ratio = base_style.leading / base_size
                else:
                    base_style = styles["BodyText"]
                    base_size = 10
                    leading_ratio = 1.2
                leading_ratio = {"single": 1.2, "1.15": 1.38, "1.5": 1.8, "double": 2.4}.get(attrs.get("line_spacing", "single"), leading_ratio)
                style = ParagraphStyle(
                    "DigiDocBlock", parent=base_style, fontName=base_style.fontName,
                    fontSize=base_size, leading=round(base_size * leading_ratio, 1),
                    alignment=alignments.get(attrs.get("align"), TA_LEFT),
                    leftIndent=attrs.get("indent", 0) * 18, spaceAfter=7,
                )
                flow.append(Paragraph(text or "&#160;", style))
            elif kind == "hardBreak": flow.append(PageBreak())
            elif kind == "horizontalRule":
                from reportlab.platypus import HRFlowable
                flow.extend([HRFlowable(width="100%", thickness=0.8, color="#9aa2ad", spaceBefore=6, spaceAfter=10), Spacer(1, 2)])
            elif kind in {"bulletList", "orderedList"}:
                for ix, item in enumerate(node.get("content", []), 1):
                    raw = "".join(_paragraph_html(child) for child in item.get("content", []))
                    flow.append(Paragraph(("• " if kind == "bulletList" else f"{ix}. ") + (raw or "&#160;"), styles["BodyText"]))
            elif kind == "table":
                rows = []
                for row in node.get("content", []):
                    rows.append([Paragraph(_paragraph_html(cell) or "&#160;", styles["BodyText"]) for cell in row.get("content", [])])
                if rows:
                    width = A4[0] - (left + right)*mm
                    column_count = max(len(row) for row in rows)
                    table = Table(rows, colWidths=[width/max(column_count, 1)] * column_count, repeatRows=1, hAlign="LEFT")
                    table.setStyle(TableStyle([("GRID", (0,0), (-1,-1), .5, (0.65,0.68,0.72)), ("BACKGROUND", (0,0), (-1,0), (0.92,0.94,0.97)), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
                    flow.extend([table, Spacer(1, 8)])
            elif kind in {"doc", "listItem"}:
                blocks(node.get("content", []))
    blocks(content.get("content", []))

    image_handle = None
    if letterhead:
        if letterhead_bytes is None:
            with letterhead.image.open("rb") as source:
                letterhead_bytes = source.read(8 * 1024 * 1024 + 1)
        if not letterhead_bytes or len(letterhead_bytes) > 8 * 1024 * 1024:
            raise ValidationError("The saved letterhead is unavailable.")
        image_handle = BytesIO(letterhead_bytes)
        reader = ImageReader(image_handle)
        iw, ih = reader.getSize()
        scale = max(A4[0]/iw, A4[1]/ih) if letterhead.scale_mode == "fill" else min(A4[0]/iw, A4[1]/ih)
        w, h = iw*scale, ih*scale
        def draw_page(canvas, _document):
            page_number = canvas.getPageNumber()
            if page_number > 100:
                raise ValidationError("The document exceeds the 100 page limit.")
            if doc.letterhead_page_mode == "every" or page_number == 1:
                canvas.saveState(); path=canvas.beginPath(); path.rect(0,0,A4[0],A4[1]); canvas.clipPath(path, stroke=0, fill=0)
                canvas.drawImage(reader,(A4[0]-w)/2,(A4[1]-h)/2,width=w,height=h,mask="auto"); canvas.restoreState()
    else:
        def draw_page(canvas, _document):
            if canvas.getPageNumber() > 100:
                raise ValidationError("The document exceeds the 100 page limit.")

    def make_canvas(*args, **kwargs):
        kwargs.update(pagesize=A4, pageCompression=1, invariant=1)
        output = pdf_canvas.Canvas(*args, **kwargs)
        output.setTitle(_clean_title(doc.title))
        output.setAuthor("")
        output.setSubject("")
        output.setCreator("")
        output._doc.info.producer = ""
        return output

    try:
        pdf.build(flow or [Paragraph("&#160;", styles["BodyText"])], onFirstPage=draw_page, onLaterPages=draw_page, canvasmaker=make_canvas)
    except Exception:
        if image_handle:
            image_handle.close()
        raise
    if image_handle:
        image_handle.close()
    data = buffer.getvalue()
    if len(data) > 25 * 1024 * 1024:
        raise ValidationError("The generated PDF is too large.")
    return data


def _render_pdf_isolated(document):
    """Run PDF generation in a short-lived worker with a process memory cap."""
    content = validate_document_json(document.content_json)
    _ensure_company_images(content, document.organization)
    image_ids = set()
    def collect(node):
        if node["type"] == "image": image_ids.add(node["attrs"]["asset_id"])
        for child in node.get("content", []): collect(child)
    collect(content)
    image_payload = {}
    total_asset_bytes = 0
    for asset in DigiDocImageAsset.objects.filter(organization=document.organization, pk__in=image_ids):
        with asset.image.open("rb") as source:
            data = source.read(8 * 1024 * 1024 + 1)
        if not data or len(data) > 8 * 1024 * 1024:
            raise ValidationError("A document image is unavailable.")
        total_asset_bytes += len(data)
        if total_asset_bytes > 20 * 1024 * 1024:
            raise ValidationError("The combined document images exceed the PDF input limit.")
        image_payload[str(asset.pk)] = base64.b64encode(data).decode("ascii")
    letterhead_bytes = None
    letterhead_meta = None
    if document.letterhead_enabled:
        letterhead = CompanyLetterhead.objects.filter(organization=document.organization).first()
        if not letterhead:
            raise ValidationError("The saved letterhead is unavailable.")
        with letterhead.image.open("rb") as source:
            letterhead_bytes = source.read(8 * 1024 * 1024 + 1)
        letterhead_meta = {"scale_mode": letterhead.scale_mode, "margin_top_mm": letterhead.margin_top_mm, "margin_bottom_mm": letterhead.margin_bottom_mm, "margin_left_mm": letterhead.margin_left_mm, "margin_right_mm": letterhead.margin_right_mm}
    worker_request = {
        "title": _clean_title(document.title), "content": content,
        "letterhead_enabled": document.letterhead_enabled,
        "letterhead_page_mode": document.letterhead_page_mode,
        "letterhead_meta": letterhead_meta,
        "letterhead_bytes": base64.b64encode(letterhead_bytes).decode("ascii") if letterhead_bytes else None,
        "assets": image_payload,
    }
    payload = json.dumps(worker_request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > 32 * 1024 * 1024:
        raise ValidationError("The document exceeds the PDF input limit.")
    worker_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if name in os.environ}
    worker_env.update({"PYTHONIOENCODING": "utf-8", "DJANGO_SETTINGS_MODULE": "core.settings"})
    kwargs = {}
    if os.name != "nt":
        import resource
        def set_limits():
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        kwargs["preexec_fn"] = set_limits
    process = subprocess.Popen([sys.executable, "-m", "attendance.digidoc_worker"], cwd=str(settings.BASE_DIR), env=worker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    job_handle = None
    try:
        if os.name == "nt":
            from .letterhead import _assign_windows_job_limit
            job_handle = _assign_windows_job_limit(process, cpu_limit_seconds=20)
        output, _error = process.communicate(payload, timeout=60)
    except subprocess.TimeoutExpired as exc:
        process.kill(); process.communicate()
        raise ValidationError("The document export timed out.") from exc
    except Exception:
        if process.poll() is None: process.kill()
        process.communicate()
        raise
    finally:
        if job_handle:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job_handle)
    if process.returncode != 0 or not output or len(output) > 25 * 1024 * 1024:
        raise ValidationError("The document could not be exported.")
    return output


def _render_preview_images_isolated(pdf_data):
    """Rasterize a generated PDF in a bounded worker and validate its PNG bundle."""
    if not pdf_data.startswith(b"%PDF-") or len(pdf_data) > 25 * 1024 * 1024:
        raise ValidationError("The preview could not be generated.")
    worker_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if name in os.environ}
    kwargs = {}
    if os.name != "nt":
        import resource
        def set_limits():
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        kwargs["preexec_fn"] = set_limits
    process = subprocess.Popen(
        [sys.executable, "-m", "attendance.digidoc_preview_worker"],
        cwd=str(settings.BASE_DIR), env=worker_env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
    )
    job_handle = None
    try:
        if os.name == "nt":
            from .letterhead import _assign_windows_job_limit
            job_handle = _assign_windows_job_limit(process, cpu_limit_seconds=20)
        output, _error = process.communicate(pdf_data, timeout=60)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise ValidationError("The preview could not be generated.") from exc
    except Exception:
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise
    finally:
        if job_handle:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job_handle)
    if process.returncode != 0 or not output or len(output) > 31 * 1024 * 1024:
        raise ValidationError("The preview could not be generated.")
    try:
        pages = []
        total = 0
        with zipfile.ZipFile(BytesIO(output), "r") as archive:
            names = archive.namelist()
            if not 1 <= len(names) <= 100 or names != [f"page-{i}.png" for i in range(1, len(names) + 1)]:
                raise ValueError("Invalid preview archive")
            for index, name in enumerate(names, start=1):
                info = archive.getinfo(name)
                if info.file_size > 10 * 1024 * 1024:
                    raise ValueError("Preview image too large")
                raw = archive.read(name)
                total += len(raw)
                if len(raw) != info.file_size or total > 30 * 1024 * 1024 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Invalid preview image")
                pages.append({"number": index, "data": base64.b64encode(raw).decode("ascii")})
        return pages
    except Exception as exc:
        raise ValidationError("The preview could not be generated.") from exc


@login_required
def digidoc_pdf(request, document_id):
    organization = _scope(request)
    doc = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization)
    cutoff = timezone.now() - timedelta(minutes=1)
    recent = AuditLog.objects.filter(actor=request.user, action="digidoc.download", created_at__gte=cutoff).count()
    if recent >= 10:
        return HttpResponse("Download limit reached. Try again shortly.", status=429)
    slot = None
    token = secrets.token_urlsafe(18)
    for slot_number in (0, 1):
        candidate = f"digidoc:pdf:slot:{slot_number}"
        if cache.add(candidate, token, timeout=30):
            slot = candidate
            break
    if slot is None:
        return HttpResponse("PDF generation is busy. Try again shortly.", status=429)
    try:
        data = _render_pdf_isolated(doc)
    except ValidationError as exc:
        if cache.get(slot) == token: cache.delete(slot)
        return HttpResponse(exc.messages[0], status=400)
    except Exception:
        if cache.get(slot) == token: cache.delete(slot)
        return HttpResponse("The document could not be exported.", status=400)
    if cache.get(slot) == token: cache.delete(slot)
    clean_name = _clean_title(doc.title).replace('\\', '_').replace('/', '_').replace('"', '').replace("'", '')
    clean_name = re.sub(r"[. ]+$", "", re.sub(r"[^\w .-]+", "_", clean_name, flags=re.UNICODE))[:80].strip(" .") or "document"
    if clean_name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        clean_name = "document"
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", unicodedata.normalize("NFKD", clean_name).encode("ascii", "ignore").decode())[:80].strip("_") or "document"
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"; filename*=UTF-8\'\'{quote(clean_name)}.pdf'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    AuditLog.objects.create(organization=organization, actor=request.user, area="organization", action="digidoc.download", target_model="DigiDocDocument", target_id=str(doc.pk), summary="Downloaded a DigiDoc PDF.", metadata={"format": "pdf"})
    return response


@login_required
def digidoc_export(request, document_id, file_format):
    organization = _scope(request)
    doc = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization)
    exporters = {
        "docx": (export_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "odt": (export_odt, "application/vnd.oasis.opendocument.text"),
        "rtf": (export_rtf, "application/rtf"),
        "txt": (export_text, "text/plain; charset=utf-8"),
    }
    if file_format not in exporters:
        return HttpResponse("Unsupported document format.", status=404)
    cutoff = timezone.now() - timedelta(minutes=1)
    recent = AuditLog.objects.filter(actor=request.user, action="digidoc.download", created_at__gte=cutoff).count()
    if recent >= 10:
        return HttpResponse("Download limit reached. Try again shortly.", status=429)
    try:
        content = validate_document_json(doc.content_json)
        exporter, content_type = exporters[file_format]
        data = exporter(content)
    except ValidationError as exc:
        return HttpResponse(exc.messages[0], status=400)
    except Exception:
        return HttpResponse("The document could not be exported.", status=400)
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not data or len(data) > 25 * 1024 * 1024:
        return HttpResponse("The generated document is too large to download.", status=400)
    clean_name = _clean_title(doc.title).replace("\\", "_").replace("/", "_").replace('"', "").replace("'", "")
    clean_name = re.sub(r"[. ]+$", "", re.sub(r"[^\w .-]+", "_", clean_name, flags=re.UNICODE))[:80].strip(" .") or "document"
    if clean_name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        clean_name = "document"
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", unicodedata.normalize("NFKD", clean_name).encode("ascii", "ignore").decode())[:80].strip("_") or "document"
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}.{file_format}"; filename*=UTF-8\'\'{quote(clean_name)}.{file_format}'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    AuditLog.objects.create(organization=organization, actor=request.user, area="organization", action="digidoc.download", target_model="DigiDocDocument", target_id=str(doc.pk), summary=f"Downloaded a DigiDoc {file_format.upper()}.", metadata={"format": file_format})
    return response


@login_required
def digidoc_preview(request, document_id):
    organization = _scope(request)
    doc = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization)
    try:
        pdf_data = _render_pdf_isolated(doc)
        pages = _render_preview_images_isolated(pdf_data)
    except Exception:
        return HttpResponse("The document preview could not be generated.", status=400)
    response = render(request, "attendance/digidoc_preview.html", {"document": doc, "pages": pages})
    response["Content-Security-Policy"] = "default-src 'self'; img-src data:; style-src 'self'; script-src 'none'; object-src 'none'; frame-ancestors 'none'"
    response["X-Frame-Options"] = "DENY"
    response["Referrer-Policy"] = "same-origin"
    response["Cache-Control"] = "private, no-store"
    return response

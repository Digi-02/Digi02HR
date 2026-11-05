"""Render trusted generated PDF pages to a bounded ZIP of PNG previews."""

from io import BytesIO
import sys
import zipfile

import pypdfium2 as pdfium


def main():
    first_page_only = "--first-page" in sys.argv[1:]
    pdf_bytes = sys.stdin.buffer.read(25 * 1024 * 1024 + 1)
    if not pdf_bytes.startswith(b"%PDF-") or len(pdf_bytes) > 25 * 1024 * 1024:
        return 2
    try:
        document = pdfium.PdfDocument(pdf_bytes)
        if not 1 <= len(document) <= 100:
            document.close()
            return 2
        archive = BytesIO()
        total = 0
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
            pages = [document[0]] if first_page_only else document
            for index, page in enumerate(pages):
                image = page.render(scale=0.55 if first_page_only else 1.25).to_pil()
                buffer = BytesIO()
                image.save(buffer, format="PNG", optimize=True)
                data = buffer.getvalue()
                total += len(data)
                if total > 30 * 1024 * 1024:
                    document.close()
                    return 3
                output.writestr(f"page-{index+1}.png", data)
        document.close()
        result = archive.getvalue()
        if len(result) > 31 * 1024 * 1024:
            return 3
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

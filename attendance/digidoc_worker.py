"""Constrained child process for PDF generation from a saved DigiDoc record."""

import json
import sys
import base64
from types import SimpleNamespace


def main():
    payload = sys.stdin.buffer.read(48 * 1024 * 1024 + 1)
    if not payload or len(payload) > 48 * 1024 * 1024:
        return 2
    try:
        value = json.loads(payload.decode("utf-8"))
        expected = {"title", "content", "letterhead_enabled", "letterhead_page_mode", "letterhead_first_slot", "letterhead_other_slot", "letterhead_meta", "letterhead_bytes", "assets"}
        if not isinstance(value, dict) or set(value) != expected or not isinstance(value["assets"], dict):
            return 2
        import django
        django.setup()
        from .digidoc import _build_pdf
        document = SimpleNamespace(title=value["title"], content_json=value["content"], letterhead_enabled=value["letterhead_enabled"], letterhead_page_mode=value["letterhead_page_mode"], letterhead_first_slot=value["letterhead_first_slot"], letterhead_other_slot=value["letterhead_other_slot"])
        assets = {key: base64.b64decode(data, validate=True) for key, data in value["assets"].items()}
        letterhead_bytes = {slot: base64.b64decode(data, validate=True) for slot, data in value["letterhead_bytes"].items()} if value["letterhead_bytes"] else None
        output = _build_pdf(document, pdf_assets=assets, letterhead_bytes=letterhead_bytes, letterhead_meta=value["letterhead_meta"])
        if not output.startswith(b"%PDF-") or len(output) > 25 * 1024 * 1024:
            return 3
        if any(token in output for token in (b"/JavaScript", b"/OpenAction", b"/EmbeddedFiles", b"/AcroForm", b"/Launch")):
            return 3
        import pypdfium2 as pdfium
        check = pdfium.PdfDocument(output)
        if not 1 <= len(check) <= 100:
            check.close()
            return 3
        check.close()
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Isolated, no-network worker for the bounded Phase 1 sample PDF."""

import json
import os
import sys
from types import SimpleNamespace


def _set_memory_limit():
    if os.name == "nt":
        # The parent applies a Windows Job Object before sending this worker data.
        return
    try:
        import resource
        cap = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    except (ImportError, OSError, ValueError):
        raise RuntimeError("The PDF worker memory cap could not be enforced.")


def main():
    _set_memory_limit()
    from django.core.files.base import ContentFile
    from .letterhead import render_sample_pdf

    header = sys.stdin.buffer.readline(2049)
    if not header or len(header) > 2048:
        return 2
    metadata = json.loads(header.decode("utf-8"))
    image_bytes = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if not image_bytes or len(image_bytes) > 8 * 1024 * 1024:
        return 2
    allowed = {
        "image_format", "image_width", "image_height", "scale_mode",
        "default_page_mode", "margin_top_mm", "margin_bottom_mm",
        "margin_left_mm", "margin_right_mm", "page_mode",
    }
    if set(metadata) != allowed or metadata["page_mode"] not in {"every", "first"}:
        return 2
    asset = SimpleNamespace(**{
        key: value for key, value in metadata.items() if key != "page_mode"
    })
    asset.image = ContentFile(image_bytes, name="letterhead.png" if asset.image_format == "png" else "letterhead.jpg")
    pdf = render_sample_pdf(asset, metadata["page_mode"])
    if len(pdf) > 25 * 1024 * 1024:
        return 2
    sys.stdout.buffer.write(pdf)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

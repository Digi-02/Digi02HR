"""Read-only template helper for the welcome-page testimonials.

All editable testimonial content lives in ``attendance/testimonials.json``.
In DEBUG every entry is returned and unapproved entries are marked with
``placeholder=True`` so the template can show the review label.  In
production only approved entries are returned; an empty list makes the
template omit the whole section (title included).
"""

import json
from pathlib import Path

from django import template
from django.conf import settings

register = template.Library()

_DATA_FILE = Path(__file__).resolve().parent.parent / "testimonials.json"


def _load_entries():
    try:
        payload = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    entries = payload.get("testimonials", []) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    return [dict(entry) for entry in entries if isinstance(entry, dict)]


@register.simple_tag
def get_testimonials():
    entries = _load_entries()

    if settings.DEBUG:
        for entry in entries:
            entry["placeholder"] = not bool(entry.get("approved"))
        return entries

    return [entry for entry in entries if entry.get("approved") is True]

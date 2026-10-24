"""Read-only template helpers for the shared welcome-page content.

All editable welcome-page copy lives in ``attendance/testimonials.json``:
the ``testimonials`` list and the ``how_it_works`` block.  In DEBUG every
testimonial is returned and unapproved entries are marked with
``placeholder=True`` so the template can show the review label.  In
production only approved testimonials are returned; an empty list makes the
template omit the whole Testimonials section (title included).
"""

import json
from pathlib import Path

from django import template
from django.conf import settings

register = template.Library()

_DATA_FILE = Path(__file__).resolve().parent.parent / "testimonials.json"


def _load_payload():
    try:
        payload = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    if isinstance(payload, dict):
        return payload
    # Keep the original bare-list format working.
    return {"testimonials": payload}


def _load_entries():
    payload = _load_payload()
    entries = payload.get("testimonials", [])
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


@register.simple_tag
def get_how_it_works():
    payload = _load_payload()
    data = payload.get("how_it_works", {})
    if not isinstance(data, dict):
        return {"title": "How it works", "steps": []}

    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raw_steps = []

    steps = []
    for step in raw_steps:
        if not isinstance(step, dict):
            continue
        steps.append({
            "number": str(step.get("number") or ""),
            "title": str(step.get("title") or ""),
            "body": str(step.get("body") or ""),
        })

    return {
        "title": str(data.get("title") or "How it works"),
        "steps": [step for step in steps if step["title"] and step["body"]],
    }

"""Small, curated Lucide-style icon set for the application sidebar.

Icons are inline SVG so they inherit ``currentColor`` and do not require a
second icon font or a runtime icon library.  Keep this list limited to real
navigation destinations.
"""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


ICON_PATHS = {
    "bi-person-vcard": [
        "M16 10h2M16 14h2M8 10h2M8 14h2M4 4h16v16H4z",
    ],
    "bi-person-lines-fill": [
        "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2",
        "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
    ],
    "bi-person": [
        "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2",
        "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
    ],
    "bi-folder2-open": [
        "M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z",
    ],
    "bi-grid-1x2": [
        "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
    ],
    "bi-kanban": [
        "M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z",
        "M8 7v8M12 7v5M16 7v11",
    ],
    "bi-people": [
        "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2",
        "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
        "M22 21v-2a4 4 0 0 0-3-3.87",
        "M16 3.13a4 4 0 0 1 0 7.75",
    ],
    "bi-people-fill": [
        "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2",
        "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
        "M22 21v-2a4 4 0 0 0-3-3.87",
        "M16 3.13a4 4 0 0 1 0 7.75",
    ],
    "bi-list-check": [
        "M10 6h11M10 12h11M10 18h11",
        "m4 6 1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
    ],
    "bi-calendar-check": [
        "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
        "m9 16 2 2 4-4",
    ],
    "bi-calendar2-week": [
        "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
        "M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01M16 18h.01",
    ],
    "bi-calendar2-range": [
        "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
        "M7 14h4M13 18h4",
    ],
    "bi-envelope-paper": [
        "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
        "m22 6-10 7L2 6",
    ],
    "bi-journal-text": [
        "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
        "M14 2v6h6M8 13h8M8 17h8M8 9h2",
    ],
    "bi-graph-up": [
        "M3 3v18h18",
        "m7 14 4-4 3 3 5-6",
    ],
    "bi-cash-stack": [
        "M20 12V8H6a2 2 0 0 1 0-4h12v4",
        "M4 6v12a2 2 0 0 0 2 2h14v-4",
        "M18 12a2 2 0 0 0 0 4h4v-4z",
    ],
    "bi-receipt": [
        "M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1z",
        "M8 7h8M8 11h8M8 15h5",
    ],
    "bi-clipboard2-check": [
        "M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2",
        "M9 3h6v4H9z",
        "m9 14 2 2 4-4",
    ],
    "bi-buildings": [
        "M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16",
        "M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1",
    ],
    "bi-sliders": [
        "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3",
        "M1 14h6M9 8h6M17 16h6",
    ],
    "bi-palette": [
        "M12 2a10 10 0 0 0 0 20h2a2 2 0 0 0 0-4h-1a2 2 0 0 1 0-4h3a4 4 0 0 0 4-4 10 10 0 0 0-8-8z",
        "M7 10h.01M9 6h.01M14 6h.01M17 9h.01",
    ],
    "bi-qr-code": [
        "M3 3h6v6H3zM15 3h6v6h-6zM3 15h6v6H3z",
        "M15 15h2v2h-2zM19 15h2v2h-2zM15 19h2v2h-2zM19 19h2v2h-2z",
    ],
    "bi-star": [
        "m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z",
    ],
    "bi-star-fill": [
        "m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z",
    ],
    "bi-box-arrow-up-right": [
        "M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6",
    ],
    "bi-file-earmark": [
        "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
        "M14 2v6h6",
    ],
}

ICON_ALIASES = {
    "bi-person-badge": "bi-person-vcard",
    "bi-grid": "bi-grid-1x2",
    "bi-envelope": "bi-envelope-paper",
    "bi-file-text": "bi-journal-text",
    "bi-bar-chart": "bi-graph-up",
    "bi-wallet": "bi-cash-stack",
}

FALLBACK_ICON = "bi-file-earmark"

ICON_NAMES = {
    "bi-person-vcard": "badge",
    "bi-person-lines-fill": "person",
    "bi-person": "person",
    "bi-folder2-open": "folder_open",
    "bi-grid-1x2": "dashboard",
    "bi-kanban": "view_kanban",
    "bi-people": "groups",
    "bi-people-fill": "groups_2",
    "bi-list-check": "checklist",
    "bi-calendar-check": "event_available",
    "bi-calendar2-week": "calendar_month",
    "bi-calendar2-range": "date_range",
    "bi-envelope-paper": "mail",
    "bi-journal-text": "article",
    "bi-graph-up": "monitoring",
    "bi-cash-stack": "payments",
    "bi-receipt": "receipt_long",
    "bi-clipboard2-check": "fact_check",
    "bi-buildings": "apartment",
    "bi-sliders": "tune",
    "bi-palette": "palette",
    "bi-qr-code": "qr_code_2",
    "bi-star": "star",
    "bi-star-fill": "star",
    "bi-box-arrow-up-right": "open_in_new",
    "bi-file-earmark": "description",
}


def icon_paths(name):
    key = ICON_ALIASES.get(name, name)
    return ICON_PATHS.get(key, ICON_PATHS[FALLBACK_ICON])


def icon_name(name):
    key = ICON_ALIASES.get(name, name)
    return ICON_NAMES.get(key, ICON_NAMES[FALLBACK_ICON])


@register.simple_tag
def nav_icon(name):
    glyph = icon_name(str(name or ""))
    return mark_safe(
        '<span class="app-nav__icon" aria-hidden="true">'
        '<span class="material-symbols-rounded">%s</span></span>' % glyph
    )

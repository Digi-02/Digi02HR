"""Navigation appearance tokens and presets.

This module is the single source of truth for the sidebar palette.  The
settings page, the live preview endpoint and the real shell all resolve their
CSS variables through :func:`resolve_nav_theme`.
"""
from __future__ import annotations

from .branding import (
    HEX_RE,
    _luminance,
    contrast_ratio,
    contrast_text,
    normalize_hex,
    tint,
)


NAV_APPEARANCE_CHOICES = [
    ("clean", "Clean"),
    ("light", "Light"),
    ("dark", "Dark"),
    ("teal", "Evergreen"),
    ("brand", "Company Brand"),
    ("custom", "Custom"),
]

NAV_ACTIVE_STYLE_CHOICES = [
    ("rounded_pill", "Rounded Pill"),
    ("soft_pill", "Soft Pill"),
    ("minimal", "Minimal Indicator"),
    ("outline", "Outline"),
    ("custom", "Custom Highlight"),
]

NAV_HIGHLIGHT_SOURCE_CHOICES = [
    ("auto", "Default Black"),
    ("accent", "Company Brand Colour"),
    ("custom", "Custom Colour"),
]

NAV_DEFAULTS = {
    "nav_style": "clean",
    "nav_bg_color": "#0A0A0A",
    "nav_highlight_style": "rounded_pill",
    "nav_highlight_source": "auto",
    "nav_highlight_color": "#111111",
    "nav_unhovered_highlight_color": "",
    "nav_text_color": "",
    "nav_muted_color": "",
    "nav_hover_bg": "",
    "nav_hover_fg": "",
    "nav_active_icon_bg": "",
    "nav_active_icon_fg": "",
}

NAV_PRESET_BACKGROUNDS = {
    "clean": "#FFFFFF",
    "light": "#F5F5F5",
    "dark": "#0A0A0A",
    "teal": "#3B5B57",
}

# Stored values from releases before the Jobgio redesign.  They are accepted
# when resolving existing rows and when old forms are posted.
LEGACY_APPEARANCE = {
    "black": "dark",
    "white": "clean",
    "light_grey": "light",
}
LEGACY_ACTIVE_STYLE = {
    "pill": "rounded_pill",
    "left_bar": "minimal",
    "soft_tint": "soft_pill",
}

DEFAULT_FG = "#1C1C1C"
DEFAULT_MUTED = "#6B6B6B"
DARK_FG = "#F5F5F5"
DARK_MUTED = "#B3B3B3"
TRANSPARENT = "transparent"


def _mix(foreground, background, amount=0.5):
    """Mix two hex colours. ``amount`` is the share of foreground."""
    fg = normalize_hex(foreground)
    bg = normalize_hex(background)
    fr, fg_g, fb = (int(fg[i:i + 2], 16) for i in (1, 3, 5))
    br, bg_g, bb = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    amount = max(0.0, min(1.0, float(amount)))
    return "#{:02X}{:02X}{:02X}".format(
        round(fr * amount + br * (1 - amount)),
        round(fg_g * amount + bg_g * (1 - amount)),
        round(fb * amount + bb * (1 - amount)),
    )


def _first_contrasting(background, candidates, minimum=4.5):
    for candidate in candidates:
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return contrast_text(background)


def _valid_override(value, background, minimum=4.5):
    """Return a stored colour only when it is a valid, readable colour."""
    if not value or not isinstance(value, str) or not HEX_RE.match(value.strip()):
        return ""
    colour = normalize_hex(value)
    if contrast_ratio(colour, background) < minimum:
        return ""
    return colour


def _resolve_icon_pair(icon_bg, icon_fg, default_bg, default_fg):
    """Resolve explicit active-icon overrides, always keeping 4.5:1."""
    bg = normalize_hex(icon_bg) if icon_bg and HEX_RE.match(str(icon_bg).strip()) else default_bg
    fg = normalize_hex(icon_fg) if icon_fg and HEX_RE.match(str(icon_fg).strip()) else default_fg
    if contrast_ratio(fg, bg) < 4.5:
        fg = contrast_text(bg)
    return bg, fg


def _normalise_appearance(value):
    value = (value or "clean").strip().lower()
    value = LEGACY_APPEARANCE.get(value, value)
    return value if value in dict(NAV_APPEARANCE_CHOICES) else "clean"


def _normalise_active_style(value):
    value = (value or "rounded_pill").strip().lower()
    value = LEGACY_ACTIVE_STYLE.get(value, value)
    return value if value in dict(NAV_ACTIVE_STYLE_CHOICES) else "rounded_pill"


def _normalise_source(value):
    value = (value or "auto").strip().lower()
    return value if value in dict(NAV_HIGHLIGHT_SOURCE_CHOICES) else "auto"


def resolve_nav_theme(
    nav_style="clean",
    nav_bg_color="#0A0A0A",
    nav_highlight_style="rounded_pill",
    nav_highlight_source="auto",
    nav_highlight_color="#111111",
    nav_unhovered_highlight_color="",
    nav_text_color="",
    nav_muted_color="",
    nav_hover_bg="",
    nav_hover_fg="",
    nav_active_icon_bg="",
    nav_active_icon_fg="",
    accent="#0A0A0A",
):
    """Return the complete ``--nav-*`` token set for an organisation.

    The function is deliberately pure: it never writes to the database and is
    safe to call from the context processor, settings view and preview API.
    """
    style = _normalise_appearance(nav_style)
    active_style = _normalise_active_style(nav_highlight_style)
    source = _normalise_source(nav_highlight_source)
    accent = normalize_hex(accent, "#0A0A0A")

    if style == "brand":
        bg = accent
    elif style == "custom":
        bg = normalize_hex(nav_bg_color, "#0A0A0A")
    else:
        bg = NAV_PRESET_BACKGROUNDS.get(style, "#FFFFFF")

    dark_bg = contrast_text(bg) == "#FFFFFF"
    clean_like = style in ("clean", "light")

    # Base palette.  Explicit colours are accepted only when they remain
    # readable; invalid legacy values quietly fall back to the safe palette.
    fg_default = DEFAULT_FG if clean_like else (DARK_FG if dark_bg else contrast_text(bg))
    fg = _valid_override(nav_text_color, bg, 4.5) or fg_default
    if clean_like:
        muted_default = DEFAULT_MUTED
    elif style == "teal":
        muted_default = _first_contrasting(bg, ["#C8D5D2", "#E1E7E5"])
    elif dark_bg:
        muted_default = DARK_MUTED
    else:
        muted_default = _first_contrasting(bg, ["#404040", "#5C5C5C", "#6B6B6B", "#737373"])
    fg_muted = _valid_override(nav_muted_color, bg, 4.5) or muted_default

    border = "rgba(255,255,255,0.16)" if dark_bg else ("#ECECEC" if clean_like else "#E5E5E5")
    if dark_bg:
        hover_bg_default = _mix("#FFFFFF", bg, 0.10) if style == "teal" else "#1C1C1C"
    else:
        hover_bg_default = "#F6F6F6"
    hover_bg = (
        normalize_hex(nav_hover_bg)
        if nav_hover_bg and HEX_RE.match(str(nav_hover_bg).strip())
        else hover_bg_default
    )
    hover_fg = _valid_override(nav_hover_fg, hover_bg, 4.5) or fg

    icon_bg = "#262626" if dark_bg else "#F4F4F5"
    icon_fg = "#D4D4D4" if dark_bg else "#5C5C5C"
    if contrast_ratio(icon_fg, icon_bg) < 4.5:
        icon_fg = _first_contrasting(icon_bg, [DARK_FG, "#D4D4D4", DEFAULT_FG])
    hover_icon_bg = "#333333" if dark_bg else "#ECECEC"

    # Highlight colour.  "Default Black" auto-inverts on dark sidebars so the
    # active row remains visible and AA-compliant.
    if source == "accent":
        highlight = accent
    elif source == "custom":
        highlight = normalize_hex(nav_highlight_color, "#111111")
    else:
        highlight = "#111111" if not dark_bg else "#FFFFFF"
    if nav_unhovered_highlight_color and HEX_RE.match(str(nav_unhovered_highlight_color).strip()):
        highlight = normalize_hex(nav_unhovered_highlight_color, highlight)

    active_bg = TRANSPARENT
    active_fg = fg
    active_border = TRANSPARENT
    active_icon_bg = highlight
    active_icon_fg = contrast_text(highlight)

    if active_style in ("rounded_pill", "custom"):
        active_bg = highlight
        active_fg = contrast_text(highlight)
        active_icon_bg, active_icon_fg = _resolve_icon_pair(
            nav_active_icon_bg,
            nav_active_icon_fg,
            active_fg,
            highlight,
        )
    elif active_style == "soft_pill":
        active_bg = tint(highlight, 0.88) if not dark_bg else _mix(highlight, bg, 0.14)
        active_fg = fg if contrast_ratio(fg, active_bg) >= 4.5 else contrast_text(active_bg)
        active_icon_bg, active_icon_fg = _resolve_icon_pair(
            nav_active_icon_bg,
            nav_active_icon_fg,
            highlight,
            contrast_text(highlight),
        )
    elif active_style == "minimal":
        active_bg = TRANSPARENT
        active_fg = fg
        active_icon_bg, active_icon_fg = _resolve_icon_pair(
            nav_active_icon_bg,
            nav_active_icon_fg,
            tint(highlight, 0.88) if not dark_bg else _mix(highlight, bg, 0.15),
            highlight,
        )
    else:  # outline
        active_bg = TRANSPARENT
        active_fg = fg
        active_border = highlight
        active_icon_bg, active_icon_fg = _resolve_icon_pair(
            nav_active_icon_bg,
            nav_active_icon_fg,
            tint(highlight, 0.90) if not dark_bg else _mix(highlight, bg, 0.15),
            highlight,
        )

    active_surface = bg if active_bg == TRANSPARENT else active_bg
    contrast = {
        "text": round(contrast_ratio(fg, bg), 2),
        "muted": round(contrast_ratio(fg_muted, bg), 2),
        "active": round(contrast_ratio(active_fg, active_surface), 2),
        "active_icon": round(contrast_ratio(active_icon_fg, active_icon_bg), 2),
        "highlight": round(contrast_ratio(highlight, bg), 2),
    }

    return {
        "nav_bg": bg,
        "nav_fg": fg,
        "nav_fg_muted": fg_muted,
        "nav_border": border,
        "nav_hover_bg": hover_bg,
        "nav_hover_fg": hover_fg,
        "nav_icon_bg": icon_bg,
        "nav_icon_fg": icon_fg,
        "nav_hover_icon_bg": hover_icon_bg,
        "nav_active_bg": active_bg,
        "nav_active_fg": active_fg,
        "nav_active_icon_bg": active_icon_bg,
        "nav_active_icon_fg": active_icon_fg,
        "nav_active_indicator": highlight,
        "nav_active_border": active_border,
        "nav_focus_ring": fg,
        "nav_pill_bg": active_bg,  # compatibility with older templates/tests
        "nav_highlight_style": active_style,
        "nav_highlight_source": source,
        "nav_appearance": style,
        "nav_active_style": active_style,
        "nav_is_dark": dark_bg,
        "nav_contrast": contrast,
    }


def nav_inputs_from_organization(organization):
    """Read all theme inputs from a model instance."""
    return {
        "nav_style": getattr(organization, "nav_style", "clean"),
        "nav_bg_color": getattr(organization, "nav_bg_color", "#0A0A0A"),
        "nav_highlight_style": getattr(organization, "nav_highlight_style", "rounded_pill"),
        "nav_highlight_source": getattr(organization, "nav_highlight_source", "auto"),
        "nav_highlight_color": getattr(organization, "nav_highlight_color", "#111111"),
        "nav_unhovered_highlight_color": getattr(organization, "nav_unhovered_highlight_color", ""),
        "nav_text_color": getattr(organization, "nav_text_color", ""),
        "nav_muted_color": getattr(organization, "nav_muted_color", ""),
        "nav_hover_bg": getattr(organization, "nav_hover_bg", ""),
        "nav_hover_fg": getattr(organization, "nav_hover_fg", ""),
        "nav_active_icon_bg": getattr(organization, "nav_active_icon_bg", ""),
        "nav_active_icon_fg": getattr(organization, "nav_active_icon_fg", ""),
        "accent": getattr(organization, "brand_color", "#0A0A0A") or "#0A0A0A",
    }


def nav_inputs_from_mapping(data, organization=None):
    """Read theme inputs from a QueryDict/FormData-like mapping.

    Missing fields fall back to the organisation's saved values, which keeps
    the preview stable while a form is being edited.
    """
    fallback = nav_inputs_from_organization(organization) if organization is not None else dict(NAV_DEFAULTS)
    inputs = {}
    for key, default in fallback.items():
        value = data.get(key, default) if hasattr(data, "get") else default
        inputs[key] = value if value not in (None, "") else (default if key not in {
            "nav_text_color", "nav_muted_color", "nav_hover_bg", "nav_hover_fg",
            "nav_active_icon_bg", "nav_active_icon_fg", "nav_unhovered_highlight_color",
        } else "")
    return inputs

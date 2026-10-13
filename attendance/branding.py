"""Brand-color helpers: all server-side so templates never emit raw user CSS."""
import re

HEX_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


def normalize_hex(value, default='#3B5BFF'):
    if isinstance(value, str) and HEX_RE.match(value.strip()):
        return value.strip().upper() if False else _canon(value.strip())
    return default


def _canon(value):
    # Keep stored case as-is but ensure leading #; CSS is case-insensitive.
    return value if value.startswith('#') else f'#{value}'


def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _to_hex(rgb):
    return '#{:02X}{:02X}{:02X}'.format(*[max(0, min(255, int(round(c)))) for c in rgb])


def darken(hex_color, amount=0.12):
    r, g, b = _rgb(normalize_hex(hex_color))
    return _to_hex((r * (1 - amount), g * (1 - amount), b * (1 - amount)))


def tint(hex_color, amount=0.9):
    """Very light version for backgrounds: mix with white."""
    r, g, b = _rgb(normalize_hex(hex_color))
    return _to_hex((r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount))


def _luminance(hex_color):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = (la, lb) if la >= lb else (lb, la)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_text(hex_color):
    """White or near-black text on the accent, chosen by WCAG contrast."""
    hex_color = normalize_hex(hex_color)
    white_ratio = contrast_ratio(hex_color, '#FFFFFF')
    dark_ratio = contrast_ratio(hex_color, '#0A0A0B')
    return '#FFFFFF' if white_ratio >= dark_ratio else '#0A0A0B'


def readable_on_white(hex_color):
    """Link/text variant guaranteed AA (4.5:1) on white; darken if needed."""
    hex_color = normalize_hex(hex_color)
    candidate = hex_color
    for _ in range(20):
        if contrast_ratio(candidate, '#FFFFFF') >= 4.5:
            return candidate
        r, g, b = _rgb(candidate)
        candidate = _to_hex((r * 0.88, g * 0.88, b * 0.88))
    return '#0A0A0B'


def accent_vars(hex_color):
    base = normalize_hex(hex_color)
    r, g, b = _rgb(base)
    return {
        'accent': base,
        'accent_rgb': f'{r},{g},{b}',
        'accent_hover': darken(base),
        'accent_tint': tint(base),
        'accent_contrast': contrast_text(base),
        'accent_text': readable_on_white(base),
        # Left bar on the black sidebar: fall back to white when the
        # accent itself is near-black and would be invisible.
        'accent_bar': '#FFFFFF' if _luminance(base) < 0.08 else base,
    }


# Preset backgrounds for the sidebar picker (name -> hex).
NAV_PRESET_BACKGROUNDS = {
    'black': '#0A0A0A',
    'white': '#FFFFFF',
    'light_grey': '#F5F5F5',
    'midnight': '#0B1226',
}

NAV_DEFAULTS = {
    'nav_style': 'black',
    'nav_bg_color': '#0A0A0A',
    'nav_highlight_style': 'pill',
    'nav_highlight_source': 'auto',
    'nav_highlight_color': '#0A0A0A',
}


def _is_dark(hex_color):
    """True when white text reads better on the color than near-black text."""
    return contrast_text(normalize_hex(hex_color)) == '#FFFFFF'


def nav_vars(nav_style='black', nav_bg_color='#0A0A0A',
             nav_highlight_style='pill', nav_highlight_source='auto',
             nav_highlight_color='#0A0A0A', accent='#0A0A0A'):
    """Server-side sidebar palette. Text is always WCAG-chosen, never stored.

    Returns the eight --nav-* variables. `accent` is only consulted when the
    company explicitly chose 'brand' (background) or 'accent' (highlight).
    """
    style = nav_style if nav_style in dict(
        [('black', ''), ('white', ''), ('light_grey', ''), ('brand', ''), ('custom', '')]) else 'black'
    if style == 'brand':
        bg = normalize_hex(accent)
    elif style == 'custom':
        bg = normalize_hex(nav_bg_color, '#0A0A0A')
    else:
        bg = NAV_PRESET_BACKGROUNDS.get(style, '#0A0A0A')

    dark_bg = _is_dark(bg)
    fg = '#FFFFFF' if dark_bg else '#0A0A0A'
    # Muted inactive text: first candidate that still meets 4.5:1 on bg.
    fg_muted = fg
    for candidate in (['#E5E5E5', '#D4D4D4', '#A3A3A3'] if dark_bg
                      else ['#404040', '#737373']):
        if contrast_ratio(candidate, bg) >= 4.5:
            fg_muted = candidate
            break

    border = 'rgba(255,255,255,0.14)' if dark_bg else '#E5E5E5'
    hover_bg = 'rgba(255,255,255,0.07)' if dark_bg else 'rgba(10,10,10,0.05)'

    hstyle = nav_highlight_style if nav_highlight_style in (
        'pill', 'left_bar', 'soft_tint', 'outline') else 'pill'
    hsource = nav_highlight_source if nav_highlight_source in (
        'auto', 'accent', 'custom') else 'auto'
    if hsource == 'accent':
        indicator = normalize_hex(accent)
    elif hsource == 'custom':
        indicator = normalize_hex(nav_highlight_color, '#0A0A0A')
    else:
        indicator = '#FFFFFF' if dark_bg else '#0A0A0A'

    # Active-item background per highlight style; text re-checked for 4.5:1.
    if hstyle == 'pill':
        active_bg = indicator
        active_fg = contrast_text(indicator)
    elif hstyle in ('left_bar', 'soft_tint'):
        if dark_bg and _luminance(indicator) > 0.5:
            # Light indicator on a dark sidebar: translucent white keeps the
            # bar/tint subtle instead of a solid white block.
            active_bg = 'rgba(255,255,255,0.12)' if hstyle == 'left_bar' else 'rgba(255,255,255,0.08)'
            active_fg = '#FFFFFF'
        else:
            active_bg = tint(indicator, 0.9) if hstyle == 'left_bar' else tint(indicator, 0.85)
            active_fg = fg
            if contrast_ratio(active_fg, active_bg) < 4.5:
                active_fg = '#FFFFFF' if _is_dark(active_bg) else '#0A0A0A'
    else:  # outline
        active_bg = 'transparent'
        active_fg = fg

    return {
        'nav_bg': bg,
        'nav_fg': fg,
        'nav_fg_muted': fg_muted,
        'nav_border': border,
        'nav_hover_bg': hover_bg,
        'nav_active_bg': active_bg,
        'nav_active_fg': active_fg,
        'nav_active_indicator': indicator,
        'nav_highlight_style': hstyle,
    }


def dominant_color(image_file):
    """Extract dominant non-white, non-near-black color with Pillow."""
    from PIL import Image
    img = Image.open(image_file).convert('RGB')
    img = img.resize((64, 64))
    pixels = list(img.getdata())
    usable = [p for p in pixels if sum(p) < 720 and sum(p) > 60]
    if not usable:
        return '#3B5BFF'
    # Quantize roughly and pick most common bucket.
    from collections import Counter
    buckets = Counter((r // 32, g // 32, b // 32) for r, g, b in usable)
    br, bg, bb = buckets.most_common(1)[0][0]
    return _to_hex((br * 32 + 16, bg * 32 + 16, bb * 32 + 16))

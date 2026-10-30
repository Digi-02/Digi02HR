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


# Compatibility names for callers that imported the old navigation helpers.
# New code should use attendance.nav_theme directly.
def nav_vars(*args, **kwargs):
    from .nav_theme import resolve_nav_theme
    return resolve_nav_theme(*args, **kwargs)


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

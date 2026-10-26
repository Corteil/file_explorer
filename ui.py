"""Drawing helpers for the round 240x240 display (origin at the centre)."""
import math

try:
    from app_components.tokens import small_font_size, label_font_size
except ImportError:  # off the badge (tests)
    small_font_size, label_font_size = 18.2, 25.0

tiny_font_size = small_font_size * 0.8   # header, footer, toast, dense lists
TAU = 2 * math.pi
RADIUS = 116   # usable radius of the display, a little inside the glass

TEXT = (1, 1, 1)
MUTED = (0.62, 0.62, 0.68)
DIM = (0.2, 0.2, 0.26)
FOLDER = (1.0, 0.8, 0.2)
FILE = (0.7, 0.8, 1.0)
CARD = (0.4, 0.9, 0.5)
OK = (0.2, 0.9, 0.4)
WARN = (1.0, 0.7, 0.1)
BAD = (1.0, 0.35, 0.35)
ACCENT = (0.3, 0.8, 1.0)


def _chord(y, size):
    """Width of the display at the top and bottom edge of a line of text centred on y."""
    edge = abs(y) + size / 2
    return 2 * math.sqrt(max(0.0, RADIUS * RADIUS - edge * edge))


def fit(ctx, s, avail, tail=0):
    """s, shortened with ".." until it is no wider than avail pixels (current font).
    With tail > 0 the last `tail` characters are kept, so a file extension survives."""
    if ctx.text_width(s) <= avail:
        return s
    keep = s[-tail:] if tail else ""
    s = s[:-tail] if tail else s
    while len(s) > 1 and ctx.text_width(s + ".." + keep) > avail:
        s = s[:-1]
    return s + ".." + keep


def text(ctx, s, x, y, rgb=TEXT, size=None, align="c", tail=0):
    """Draw text, shortened if it would run off the round edge of the screen."""
    ctx.font_size = size or small_font_size
    ctx.text_align = ctx.LEFT if align == "l" else ctx.CENTER
    ctx.text_baseline = ctx.MIDDLE
    chord = _chord(y, ctx.font_size)
    if align == "l":
        s = fit(ctx, s, chord / 2 - x, tail)
    else:
        s = fit(ctx, s, chord - 2 * abs(x), tail)
    ctx.rgb(*rgb).move_to(x, y).text(s)


def bar(ctx, x, y, w, h, frac, rgb):
    frac = max(0.0, min(1.0, frac))
    ctx.rgb(*DIM).rectangle(x, y, w, h).fill()
    if frac > 0:
        ctx.rgb(*rgb).rectangle(x, y, w * frac, h).fill()


def ring(ctx, frac, rgb, r=112, width=8):
    """Progress ring round the edge of the display, starting at the top."""
    frac = max(0.0, min(1.0, frac))
    ctx.line_width = width
    ctx.rgb(*DIM).arc(0, 0, r, 0, TAU, 0).stroke()
    if frac > 0:
        ctx.rgb(*rgb).arc(0, 0, r, -TAU / 4, -TAU / 4 + TAU * frac, 0).stroke()


def toast(ctx, msg, rgb=WARN):
    """A message on a dark band near the bottom, wrapped onto two lines if needed."""
    ctx.font_size = tiny_font_size
    first, second = msg, ""
    if ctx.text_width(msg) > _chord(82, tiny_font_size):
        cut = msg.rfind(" ", 0, 21)
        if cut > 0:
            first, second = msg[:cut], msg[cut + 1:]
    ctx.rgba(0, 0, 0, 0.9).rectangle(-100, 71, 200, 38 if second else 22).fill()
    text(ctx, first, 0, 82, rgb, tiny_font_size)
    if second:
        text(ctx, second, 0, 98, rgb, tiny_font_size)


# --- small icons, s = half-size in pixels, centred on (cx, cy) ---

def folder(ctx, cx, cy, s, rgb=FOLDER):
    ctx.rgb(*rgb)
    ctx.rectangle(cx - s, cy - 0.75 * s, 0.9 * s, 0.4 * s).fill()
    ctx.rectangle(cx - s, cy - 0.4 * s, 2 * s, 1.2 * s).fill()


def file(ctx, cx, cy, s, rgb=FILE):
    ctx.rgb(*rgb)
    ctx.line_width = max(1.5, s / 4)
    ctx.rectangle(cx - 0.7 * s, cy - s, 1.4 * s, 2 * s).stroke()
    for k in (-0.35, 0.05, 0.45):
        ctx.move_to(cx - 0.4 * s, cy + k * s).line_to(cx + 0.4 * s, cy + k * s).stroke()


def card(ctx, cx, cy, s, rgb=CARD):
    ctx.rgb(*rgb)
    ctx.move_to(cx - 0.7 * s, cy - s).line_to(cx + 0.3 * s, cy - s).line_to(cx + 0.7 * s, cy - 0.6 * s) \
        .line_to(cx + 0.7 * s, cy + s).line_to(cx - 0.7 * s, cy + s).close_path().fill()
    ctx.rgb(0, 0, 0)
    for k in (-0.3, 0.0, 0.3):
        ctx.rectangle(cx + k * s - 0.06 * s, cy - 0.85 * s, 0.12 * s, 0.4 * s).fill()


def chip(ctx, cx, cy, s, rgb=ACCENT):
    ctx.rgb(*rgb)
    ctx.line_width = max(1.5, s / 4)
    ctx.rectangle(cx - 0.8 * s, cy - 0.5 * s, 1.6 * s, s).stroke()
    for k in (-0.4, 0.0, 0.4):
        ctx.move_to(cx + k * s, cy + 0.5 * s).line_to(cx + k * s, cy + 0.9 * s).stroke()

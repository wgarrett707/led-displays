# Lays out lyric lines and status screens for the 256x32 LED matrix.
# Everything uses one font size: up to two lines of 6x11 at size 16 (about 41 characters each).
# Text comes out as masks (where the letters are) plus line boxes, so effects can colour it.
import unicodedata
from PIL import Image, ImageDraw, ImageFont
from lrclib import cleanTitle

WIDTH, HEIGHT = 256, 32
MARGIN = 2
FONT = ImageFont.truetype('/home/pi/led-scripts/lyrics/fonts/6x11.ttf', size=16)
# Two lines 16 px apart fill the 32-px panel
LINE_SPACING = 16

GREY = (140, 140, 140)
DIM = (70, 70, 70)
# Text brightness: lyrics and titles full, the artist line dimmer; much dimmer between lines
SHADE_TITLE, SHADE_ARTIST = 1.0, 0.55
SHADE_DIM_TITLE, SHADE_DIM_ARTIST = 0.4, 0.3

# The pixel font only covers ASCII well, so typographic characters are mapped to plain ones
REPLACEMENTS = {'‘': "'", '’': "'", '‚': "'", '“': '"', '”': '"',
                '„': '"', '–': '-', '—': '-', '…': '...', ' ': ' '}

_measure = ImageDraw.Draw(Image.new('L', (1, 1)))
_widths = {}


def toAscii(text):
    # Strips accents (é -> e) and drops anything the font can't draw (e.g. CJK)
    text = ''.join(REPLACEMENTS.get(c, c) for c in text)
    text = unicodedata.normalize('NFKD', text)
    return ' '.join(''.join(c for c in text if ord(c) < 128).split())


def width(text):
    # Memoized: wrapping measures the same fragments many times
    if text not in _widths:
        if len(_widths) > 20000:
            _widths.clear()
        _widths[text] = _measure.textsize(text, font=FONT)[0]
    return _widths[text]


def fits(text):
    return width(text) <= WIDTH - 2 * MARGIN


def wrap(text):
    # One line if it fits, else the most even split into two lines that fit; None if neither works
    if fits(text):
        return [text]
    words = text.split()
    best = None
    for i in range(1, len(words)):
        first, second = ' '.join(words[:i]), ' '.join(words[i:])
        if not fits(first):
            break
        if fits(second):
            widest = max(width(first), width(second))
            if best is None or widest < best[0]:
                best = (widest, [first, second])
    return best[1] if best else None


def _top(count):
    ascent, descent = FONT.getmetrics()
    return (HEIGHT - (ascent + descent) - LINE_SPACING * (count - 1)) // 2


def textMask(lines, shades):
    # Centred lines as a mask, plus one box per line: (x0, y0, x1, y1, shade, string)
    mask = Image.new('L', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(mask)
    draw.fontmode = '1'
    top = _top(len(lines))
    boxes = []
    for i, (line, shade) in enumerate(zip(lines, shades)):
        x, y = (WIDTH - width(line)) // 2, top + i * LINE_SPACING
        draw.text((x, y), line, font=FONT, fill=255)
        boxes.append((x, max(0, y), x + width(line), min(HEIGHT, y + LINE_SPACING), shade, line))
    return mask, boxes


def lyric(text):
    # Returns (mask, boxes, False) if the line fits on the panel, or (wide mask, boxes, True)
    # for the very rare line too long for two lines, which scrolls across while it's sung
    text = toAscii(text)
    lines = wrap(text)
    if lines:
        mask, boxes = textMask(lines, [1.0] * len(lines))
        return mask, boxes, False
    mask = Image.new('L', (width(text) + 2 * MARGIN, HEIGHT))
    draw = ImageDraw.Draw(mask)
    draw.fontmode = '1'
    y = _top(1)
    draw.text((MARGIN, y), text, font=FONT, fill=255)
    return mask, [(MARGIN, max(0, y), MARGIN + width(text), min(HEIGHT, y + LINE_SPACING), 1.0, text)], True


def shorten(text, suffix=''):
    # Trims text with '...' until text + suffix fits on one line
    if fits(text + suffix):
        return text + suffix
    while text and not fits(text + '...' + suffix):
        text = text[:-1]
    return text.rstrip(' ,') + '...' + suffix


def songInfo(title, artist, note=None, dim=False):
    # Title on top, artist (and an optional note) underneath, as a mask. The note matters more
    # than the end of a long artist list, so the artist is what gets shortened.
    lines = [shorten(toAscii(cleanTitle(title))), shorten(toAscii(artist), '  -  ' + note if note else '')]
    return textMask(lines, [SHADE_DIM_TITLE, SHADE_DIM_ARTIST] if dim else [SHADE_TITLE, SHADE_ARTIST])


def message(text, color=GREY):
    # A plain one-line status screen (no effects), as an RGB image
    img = Image.new('RGB', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    draw.fontmode = '1'
    text = shorten(toAscii(text))
    draw.text(((WIDTH - width(text)) // 2, _top(1)), text, font=FONT, fill=color)
    return img

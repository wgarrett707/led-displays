# Renders lyric lines and status screens as 256x32 images for the LED matrix.
# Everything uses one font size: up to two lines of 6x11 at size 16 (about 41 characters each).
import unicodedata
from PIL import Image, ImageDraw, ImageFont
from lrclib import cleanTitle

WIDTH, HEIGHT = 256, 32
MARGIN = 2
FONT = ImageFont.truetype('/home/pi/led-scripts/lyrics/fonts/6x11.ttf', size=16)
# Two lines 16 px apart fill the 32-px panel
LINE_SPACING = 16

WHITE = (255, 255, 255)
GREY = (140, 140, 140)
DIM = (70, 70, 70)

# The pixel font only covers ASCII well, so typographic characters are mapped to plain ones
REPLACEMENTS = {'‘': "'", '’': "'", '‚': "'", '“': '"', '”': '"',
                '„': '"', '–': '-', '—': '-', '…': '...', ' ': ' '}

_measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
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


def newImage(size=(WIDTH, HEIGHT)):
    img = Image.new('RGB', size)
    draw = ImageDraw.Draw(img)
    draw.fontmode = '1'
    return img, draw


def drawLines(draw, lines, colors):
    # Centres each line horizontally and the block vertically
    ascent, descent = FONT.getmetrics()
    top = (HEIGHT - (ascent + descent) - LINE_SPACING * (len(lines) - 1)) // 2
    for i, (line, color) in enumerate(zip(lines, colors)):
        draw.text(((WIDTH - width(line)) // 2, top + i * LINE_SPACING), line, font=FONT, fill=color)


def lyric(text, color=WHITE):
    # Returns (image, None) if the line fits on the panel, or (None, wide image) to scroll across
    text = toAscii(text)
    lines = wrap(text)
    if lines:
        img, draw = newImage()
        drawLines(draw, lines, [color] * len(lines))
        return img, None
    # Too long for two lines (very rare): one wide line, scrolled across while it's sung
    ascent, descent = FONT.getmetrics()
    wide, draw = newImage((width(text) + 2 * MARGIN, HEIGHT))
    draw.text((MARGIN, (HEIGHT - ascent - descent) // 2), text, font=FONT, fill=color)
    return None, wide


def shorten(text, suffix=''):
    # Trims text with '...' until text + suffix fits on one line
    if fits(text + suffix):
        return text + suffix
    while text and not fits(text + '...' + suffix):
        text = text[:-1]
    return text.rstrip(' ,') + '...' + suffix


def songInfo(title, artist, note=None, dim=False):
    # Title on top, artist (and an optional status note) underneath. The note matters more than
    # the end of a long artist list, so the artist is what gets shortened.
    img, draw = newImage()
    lines = [shorten(toAscii(cleanTitle(title))), shorten(toAscii(artist), '  -  ' + note if note else '')]
    drawLines(draw, lines, [DIM, DIM] if dim else [WHITE, GREY])
    return img


def message(text, color=GREY):
    img, draw = newImage()
    drawLines(draw, [shorten(toAscii(text))], [color])
    return img

# Lays out lyric lines and status screens for the 256x32 LED matrix.
# Everything uses one font size: up to two lines of 6x11 at size 16 (about 41 characters each).
# Text comes out as masks (where the letters are) plus line boxes, so effects can colour it.
import unicodedata
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from lrclib import cleanTitle

WIDTH, HEIGHT = 256, 32
MARGIN = 2
# Two lines 16 px apart fill the 32-px panel
LINE_SPACING = 16


class Face:
    # A font and how text is set in it. PIXEL is the normal one; a theme can bring its own
    # (e.g. brat.FACE), which is then passed to the layout functions below.
    def __init__(self, path, size, smooth=False, blur=0, lowercase=False):
        self.font = ImageFont.truetype(path, size=size)
        self.smooth = smooth          # anti-aliased: the mask gets grey edges instead of 1-bit
        self.blur = blur              # Gaussian blur radius applied to the mask
        self.lowercase = lowercase
        self.widths = {}
        if lowercase:
            # Lowercase-only text is centred on its own ink: the font's metrics leave room above
            # for capitals and accents that never appear
            probe = Image.new('L', (200, 80))
            ImageDraw.Draw(probe).text((0, 0), 'bdfhklgjpqy', font=self.font, fill=255)
            box = probe.getbbox()
            self.inkTop, self.inkHeight = box[1], box[3] - box[1]
        else:
            ascent, descent = self.font.getmetrics()
            self.inkTop, self.inkHeight = 0, ascent + descent


PIXEL = Face('/home/pi/led-scripts/lyrics/fonts/6x11.ttf', 16)
FONT = PIXEL.font

GREY = (140, 140, 140)
DIM = (70, 70, 70)
# Text brightness: lyrics and titles full, the artist line dimmer; much dimmer between lines
SHADE_TITLE, SHADE_ARTIST = 1.0, 0.55
SHADE_DIM_TITLE, SHADE_DIM_ARTIST = 0.4, 0.3

# The pixel font only covers ASCII well, so typographic characters are mapped to plain ones
REPLACEMENTS = {'‘': "'", '’': "'", '‚': "'", '“': '"', '”': '"',
                '„': '"', '–': '-', '—': '-', '…': '...', '\xa0': ' '}

_measure = ImageDraw.Draw(Image.new('L', (1, 1)))


def toAscii(text):
    # Strips accents (é -> e) and drops anything the font can't draw (e.g. CJK)
    text = ''.join(REPLACEMENTS.get(c, c) for c in text)
    text = unicodedata.normalize('NFKD', text)
    return ' '.join(''.join(c for c in text if ord(c) < 128).split())


def _prepare(text, face):
    text = toAscii(text)
    return text.lower() if face.lowercase else text


def width(text, face=PIXEL):
    # Memoized: wrapping measures the same fragments many times
    widths = face.widths
    if text not in widths:
        if len(widths) > 20000:
            widths.clear()
        widths[text] = _measure.textsize(text, font=face.font)[0]
    return widths[text]


def fits(text, face=PIXEL):
    return width(text, face) <= WIDTH - 2 * MARGIN


def wrap(text, face=PIXEL):
    # One line if it fits, else the most even split into two lines that fit; None if neither works
    if fits(text, face):
        return [text]
    words = text.split()
    best = None
    for i in range(1, len(words)):
        first, second = ' '.join(words[:i]), ' '.join(words[i:])
        if not fits(first, face):
            break
        if fits(second, face):
            widest = max(width(first, face), width(second, face))
            if best is None or widest < best[0]:
                best = (widest, [first, second])
    return best[1] if best else None


def _top(count, face=PIXEL):
    return (HEIGHT - face.inkHeight - LINE_SPACING * (count - 1)) // 2 - face.inkTop


def _canvas(size, face):
    mask = Image.new('L', size)
    draw = ImageDraw.Draw(mask)
    if not face.smooth:
        draw.fontmode = '1'
    return mask, draw


def _finish(mask, face):
    return mask.filter(ImageFilter.GaussianBlur(face.blur)) if face.blur else mask


def textMask(lines, shades, face=PIXEL):
    # Centred lines as a mask, plus one box per line: (x0, y0, x1, y1, shade, string)
    mask, draw = _canvas((WIDTH, HEIGHT), face)
    top = _top(len(lines), face)
    boxes = []
    for i, (line, shade) in enumerate(zip(lines, shades)):
        x, y = (WIDTH - width(line, face)) // 2, top + i * LINE_SPACING
        draw.text((x, y), line, font=face.font, fill=255)
        boxes.append((x, max(0, y), x + width(line, face), min(HEIGHT, y + LINE_SPACING), shade, line))
    return _finish(mask, face), boxes


def lyric(text, face=PIXEL):
    # Returns (mask, boxes, False) if the line fits on the panel, or (wide mask, boxes, True)
    # for the very rare line too long for two lines, which scrolls across while it's sung
    text = _prepare(text, face)
    lines = wrap(text, face)
    if lines:
        mask, boxes = textMask(lines, [1.0] * len(lines), face)
        return mask, boxes, False
    mask, draw = _canvas((width(text, face) + 2 * MARGIN, HEIGHT), face)
    y = _top(1, face)
    draw.text((MARGIN, y), text, font=face.font, fill=255)
    return _finish(mask, face), [(MARGIN, max(0, y), MARGIN + width(text, face),
                                  min(HEIGHT, y + LINE_SPACING), 1.0, text)], True


def shorten(text, suffix='', face=PIXEL):
    # Trims text with '...' until text + suffix fits on one line
    if fits(text + suffix, face):
        return text + suffix
    while text and not fits(text + '...' + suffix, face):
        text = text[:-1]
    return text.rstrip(' ,') + '...' + suffix


def songInfo(title, artist, note=None, dim=False, face=PIXEL):
    # Title on top, artist (and an optional note) underneath, as a mask. The note matters more
    # than the end of a long artist list, so the artist is what gets shortened.
    suffix = '  -  ' + note if note else ''
    if face.lowercase:
        suffix = suffix.lower()
    lines = [shorten(_prepare(cleanTitle(title), face), face=face),
             shorten(_prepare(artist, face), suffix, face)]
    return textMask(lines, [SHADE_DIM_TITLE, SHADE_DIM_ARTIST] if dim else [SHADE_TITLE, SHADE_ARTIST], face)


def message(text, color=GREY):
    # A plain one-line status screen (no effects), as an RGB image
    img = Image.new('RGB', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    draw.fontmode = '1'
    text = shorten(toAscii(text))
    draw.text(((WIDTH - width(text)) // 2, _top(1)), text, font=FONT, fill=color)
    return img

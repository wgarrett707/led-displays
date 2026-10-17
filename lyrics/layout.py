# Renders lyric lines and status screens as 256x32 images for the LED matrix.
import unicodedata
from PIL import Image, ImageDraw, ImageFont
from lrclib import cleanTitle

WIDTH, HEIGHT = 256, 32
MARGIN = 2

FONT_DIR = '/home/pi/led-scripts/lyrics/fonts/'
BIG = ImageFont.truetype(FONT_DIR + '6x11.ttf', size=22)
MEDIUM = ImageFont.truetype(FONT_DIR + '6x11.ttf', size=16)
SMALL = ImageFont.truetype(FONT_DIR + 'm5x7.ttf', size=16)

WHITE = (255, 255, 255)
GREY = (140, 140, 140)
DIM = (70, 70, 70)

# The pixel fonts only cover ASCII well, so typographic characters are mapped to plain ones
REPLACEMENTS = {'‘': "'", '’': "'", '‚': "'", '“': '"', '”': '"',
                '„': '"', '–': '-', '—': '-', '…': '...', ' ': ' '}

_measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))


def toAscii(text):
    # Strips accents (é -> e) and drops anything the fonts can't draw (e.g. CJK)
    text = ''.join(REPLACEMENTS.get(c, c) for c in text)
    text = unicodedata.normalize('NFKD', text)
    return ' '.join(''.join(c for c in text if ord(c) < 128).split())


_widths = {}


def width(text, font):
    # Memoized: wrapping measures the same fragments many times
    key = (text, id(font))
    if key not in _widths:
        if len(_widths) > 20000:
            _widths.clear()
        _widths[key] = _measure.textsize(text, font=font)[0]
    return _widths[key]


def lineHeight(font):
    ascent, descent = font.getmetrics()
    return ascent + descent


def wrap(text, font, lines):
    # Splits text into at most 'lines' lines that each fit the panel, as evenly as possible.
    # Returns None if it can't fit.
    words = text.split()
    maxWidth = WIDTH - 2 * MARGIN
    if lines == 1:
        return [text] if width(text, font) <= maxWidth else None
    best = None
    for i in range(1, len(words)):
        first = ' '.join(words[:i])
        if width(first, font) > maxWidth:
            break
        rest = wrap(' '.join(words[i:]), font, lines - 1)
        if rest is None:
            continue
        widest = max(width(l, font) for l in [first] + rest)
        if best is None or widest < best[0]:
            best = (widest, [first] + rest)
    return best[1] if best else None


# Font and line count to try, largest first, with the vertical distance between lines
LAYOUTS = [(BIG, 1, 0), (MEDIUM, 1, 0), (MEDIUM, 2, 16), (SMALL, 2, 14), (SMALL, 3, 10)]


def drawLines(draw, lines, font, spacing, color, top=None):
    # Centres each line horizontally and the block vertically
    if top is None:
        block = lineHeight(font) + spacing * (len(lines) - 1)
        top = (HEIGHT - block) // 2
    for i, line in enumerate(lines):
        x = (WIDTH - width(line, font)) // 2
        draw.text((x, top + i * spacing), line, font=font, fill=color)


def lyric(text, color=WHITE):
    # Returns (image, None) if the line fits, or (wide image, None) for horizontal scrolling
    text = toAscii(text)
    img = Image.new('RGB', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    draw.fontmode = '1'
    for font, count, spacing in LAYOUTS:
        lines = wrap(text, font, count)
        if lines:
            drawLines(draw, lines, font, spacing, color)
            return img, None
    # Too long even for three small lines: render one wide line to scroll across
    wide = Image.new('RGB', (width(text, MEDIUM) + 2 * MARGIN, HEIGHT))
    d = ImageDraw.Draw(wide)
    d.fontmode = '1'
    d.text((MARGIN, (HEIGHT - lineHeight(MEDIUM)) // 2), text, font=MEDIUM, fill=color)
    return None, wide


def fitOne(text, fonts):
    # First font in which text fits on one line; shortens with '...' as a last resort
    for font in fonts:
        if width(text, font) <= WIDTH - 2 * MARGIN:
            return text, font
    font = fonts[-1]
    while text and width(text + '...', font) > WIDTH - 2 * MARGIN:
        text = text[:-1]
    return text.rstrip() + '...', font


def songInfo(title, artist, note=None, dim=False):
    # Title on top, artist (and an optional status note) underneath
    img = Image.new('RGB', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    draw.fontmode = '1'
    title, titleFont = fitOne(toAscii(cleanTitle(title)), [MEDIUM, SMALL])
    # The note matters more than the end of a long artist list, so the artist gets shortened
    suffix = '  -  ' + note if note else ''
    artist = toAscii(artist)
    if width(artist + suffix, SMALL) > WIDTH - 2 * MARGIN:
        while artist and width(artist + '...' + suffix, SMALL) > WIDTH - 2 * MARGIN:
            artist = artist[:-1]
        artist = artist.rstrip(' ,') + '...'
    second, secondFont = artist + suffix, SMALL
    drawLines(draw, [title], titleFont, 0, DIM if dim else WHITE, top=1)
    drawLines(draw, [second], secondFont, 0, DIM if dim else GREY, top=17)
    return img


def message(text, color=GREY):
    img = Image.new('RGB', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    draw.fontmode = '1'
    text, font = fitOne(toAscii(text), [MEDIUM, SMALL])
    drawLines(draw, [text], font, 0, color)
    return img

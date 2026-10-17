# Animated text/background effects for the lyrics display.
# Each effect turns the current text (a Text) into one 32x256 RGB frame (numpy uint8) per call.
import colorsys
import math
import random
import numpy as np
from PIL import ImageFilter

H, W = 32, 256
YY, XX = [a.astype(np.float32) for a in np.mgrid[0:H, 0:W]]
# Most effects assume a party-typical 120 BPM (Spotify no longer gives new apps tempo data)
BPM = 120.0


def gradient(stops, n=256):
    # Colour lookup table: stops are (position 0..1, (r, g, b))
    positions = np.linspace(0, 1, n)
    table = np.zeros((n, 3), np.float32)
    for c in range(3):
        table[:, c] = np.interp(positions, [s[0] for s in stops], [s[1][c] for s in stops])
    return table


RAINBOW = np.array([colorsys.hsv_to_rgb(i / 256.0, 1, 1) for i in range(256)], np.float32) * 255
FIRE = gradient([(0, (0, 0, 0)), (0.3, (110, 0, 0)), (0.55, (220, 50, 0)), (0.8, (255, 160, 0)),
                 (1, (255, 240, 170))])
PLASMA = gradient([(0, (60, 0, 110)), (0.25, (220, 0, 140)), (0.5, (255, 110, 0)), (0.75, (0, 170, 220)),
                   (1, (60, 0, 110))])
SPECTRUM = gradient([(0, (0, 255, 60)), (0.55, (255, 230, 0)), (1, (255, 30, 0))], H)[::-1]
NEON = [(255, 40, 170), (0, 220, 255), (130, 255, 40), (255, 150, 0), (180, 70, 255)]


def ease(x):
    # 0..1 -> 0..1, fast start and soft landing
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def shift(a, dy=0, dx=0):
    # Moves an array down by dy and right by dx (negative = up/left), filling with zeros
    out = np.zeros_like(a)
    if abs(dy) >= a.shape[0] or abs(dx) >= a.shape[1]:
        return out
    src = a[max(0, -dy):a.shape[0] - max(0, dy), max(0, -dx):a.shape[1] - max(0, dx)]
    out[max(0, dy):max(0, dy) + src.shape[0], max(0, dx):max(0, dx) + src.shape[1]] = src
    return out


YI, XI = np.mgrid[0:H, 0:W]


def outlineOf(mask):
    # The 1-px ring around a mask (8-neighbourhood)
    grown = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                grown |= shift(mask, dy, dx)
    return grown & ~mask


def columnShift(a, dy):
    # Moves each column x of a down by dy[x] pixels (negative = up), filling with zeros
    src = YI - dy[None, :]
    ok = (src >= 0) & (src < H)
    return np.where(ok, a[np.clip(src, 0, H - 1), XI], 0).astype(a.dtype)


class Text:
    # Where the letters are (mask), a 1-px ring around them (outline, drawn black so text stays
    # readable over busy backgrounds), per-pixel brightness (shade), and the line boxes
    # (x0, y0, x1, y1, shade, string)
    def __init__(self, maskImage, boxes):
        self.maskImage = maskImage
        self.mask = np.asarray(maskImage) > 127
        self.outline = (np.asarray(maskImage.filter(ImageFilter.MaxFilter(3))) > 127) & ~self.mask
        self.shade = np.ones((H, W), np.float32)
        for x0, y0, x1, y1, shade, string in boxes:
            self.shade[y0:y1, :] = shade
        self.boxes = boxes
        self._glow = None

    def glow(self):
        # Soft halo around the letters (computed on first use; ~1 ms)
        if self._glow is None:
            g = np.asarray(self.maskImage.filter(ImageFilter.GaussianBlur(2.5)), np.float32)
            self._glow = np.clip(g * (1.8 / max(1.0, float(g.max()))), 0, 1)
        return self._glow

    def moved(self, dy=0, dx=0):
        # A shifted copy, for slide-in/slide-out transitions
        other = Text.__new__(Text)
        other.maskImage, other._glow = self.maskImage, None
        other.mask, other.outline = shift(self.mask, dy, dx), shift(self.outline, dy, dx)
        other.shade = shift(self.shade, dy, dx)
        other.boxes = [(x0 + dx, y0 + dy, x1 + dx, y1 + dy, s, t) for x0, y0, x1, y1, s, t in self.boxes]
        return other

    def lineBands(self):
        # Per line: (rows y0..y1, that line's mask on its own, its shade on its own)
        bands = []
        for x0, y0, x1, y1, s, t in self.boxes:
            m = np.zeros((H, W), bool)
            m[y0:y1] = self.mask[y0:y1]
            sh = np.zeros((H, W), np.float32)
            sh[y0:y1] = self.shade[y0:y1]
            bands.append((y0, y1, m, sh))
        return bands

    def charSpans(self):
        # Per line: list of (x0, x1) columns for each visible character
        import layout
        spans = []
        for x0, y0, x1, y1, s, string in self.boxes:
            edges = [x0 + layout.width(string[:i]) for i in range(len(string) + 1)]
            spans.append([(edges[i], edges[i + 1]) for i in range(len(string)) if string[i] != ' '])
        return spans

    def displaced(self, offsets):
        # A copy with each line's columns moved vertically: offsets[i] is a length-W int array
        # of pixels down (negative = up) for line i. Used for waving and bouncing letters.
        other = Text.__new__(Text)
        other.maskImage, other._glow, other.boxes = self.maskImage, None, self.boxes
        mask = np.zeros((H, W), bool)
        shade = np.zeros((H, W), np.float32)
        for (y0, y1, m, sh), dy in zip(self.lineBands(), offsets):
            mask |= columnShift(m, dy)
            shade = np.maximum(shade, columnShift(sh, dy))
        other.mask, other.shade = mask, np.where(mask, shade, 1.0).astype(np.float32)
        other.outline = outlineOf(mask)
        return other

    def revealed(self, fraction):
        # Columns of each line up to 'fraction' of the total text length, read left to right
        # (line 1 then line 2). Used for karaoke fill and typewriter reveal.
        total = sum(b[2] - b[0] for b in self.boxes)
        remaining = fraction * total
        cols = np.zeros((H, W), bool)
        edges = []
        for x0, y0, x1, y1, s, t in self.boxes:
            limit = x0 + max(0.0, min(remaining, x1 - x0))
            cols[y0:y1, :] = XX[y0:y1, :] < limit
            if x0 < limit < x1:
                edges.append((y0, y1, int(limit)))
            remaining -= x1 - x0
        return cols, edges


class Frame:
    def __init__(self, text, prev, t, age, progress, line, dt):
        self.text = text          # Text on screen now
        self.prev = prev          # Text that was on screen before (for transitions), or None
        self.t = t                # effect clock, seconds (stops while paused)
        self.age = age            # seconds since this text appeared
        self.progress = progress  # 0..1 through the current lyric line, or None for song info
        self.line = line          # lyric line index (for per-line colours)
        self.dt = dt              # seconds since the previous frame


def paint(out, text, color, alpha=1.0, outline=True):
    # Draws text onto out (float HxWx3) in color ((3,) or HxWx3), with a black outline
    if outline:
        out[text.outline] *= 1 - alpha
    m = text.mask
    c = color[m] if np.ndim(color) == 3 else np.asarray(color, np.float32)
    out[m] = out[m] * (1 - alpha) + c * text.shade[m][:, None] * alpha


class Effect:
    name = ''

    def render(self, f):
        raise NotImplementedError


class Rainbow(Effect):
    # Text filled with a flowing rainbow; new lines slide up, pushing the old one out
    name = 'Rainbow'

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        color = RAINBOW[((XX * 1.5 + YY * 3 - f.t * 160) % 256).astype(np.uint8)]
        k = ease(f.age / 0.25)
        if k < 1:
            dy = int(round((1 - k) * H))
            if f.prev is not None:
                paint(out, f.prev.moved(dy - H), color, outline=False)
            paint(out, f.text.moved(dy), color, outline=False)
        else:
            paint(out, f.text, color, outline=False)
        return out


class Neon(Effect):
    # Neon-tube text with a glow that pulses on the beat; each line flickers on like a sign
    name = 'Neon'
    FLICKER = [1, 0, 0, 1, 0.3, 0, 1, 1, 0, 1]

    def render(self, f):
        color = np.array(NEON[f.line % len(NEON)], np.float32)
        beat = (f.t * BPM / 60.0) % 1.0
        pulse = 0.45 + 0.35 * math.exp(-beat * 4)
        step = int(f.age / 0.045)
        on = self.FLICKER[step] if step < len(self.FLICKER) else 1.0
        out = f.text.glow()[:, :, None] * color * (pulse * on)
        out *= f.text.shade[:, :, None]
        paint(out, f.text, color * 0.45 + 255 * 0.55, alpha=on, outline=False)
        return out


class Fire(Effect):
    # The letters are the fuel: flames rise off them; new lines ignite from orange to white-hot
    name = 'Fire'

    def __init__(self):
        self.heat = np.zeros((H, W), np.float32)

    def render(self, f):
        below = shift(self.heat, -1)
        rising = (below * 2 + shift(below, 0, -1) + shift(below, 0, 1) + self.heat) / 5.0
        self.heat = rising * np.random.uniform(0.80, 0.98, (H, W)).astype(np.float32)
        fuel = f.text.mask
        self.heat[fuel] = np.maximum(self.heat[fuel], np.random.uniform(0.55, 1.0, int(fuel.sum())))
        self.heat[H - 1] = np.maximum(self.heat[H - 1], np.random.uniform(0, 1, W) ** 4 * 0.8)
        out = FIRE[(np.clip(self.heat, 0, 1) * 255).astype(np.uint8)] * 0.75
        k = min(1.0, f.age / 0.35)
        color = np.array([255, 120 + 120 * k, 40 + 140 * k], np.float32)
        paint(out, f.text, color)
        return out


class Karaoke(Effect):
    # Dim text that fills with colour left to right as the line is sung
    name = 'Karaoke'
    FILL = gradient([(0, (255, 40, 160)), (0.5, (255, 90, 60)), (1, (255, 190, 0))], W)

    def render(self, f):
        out = RAINBOW[((XX * 0.6 + YY * 2 + f.t * 25) % 256).astype(np.uint8)] * 0.10
        paint(out, f.text, (70, 70, 110))
        filled, edges = f.text.revealed(1.0 if f.progress is None else f.progress)
        fill = Text.__new__(Text)
        fill.mask, fill.outline, fill.shade = f.text.mask & filled, f.text.outline, f.text.shade
        paint(out, fill, np.broadcast_to(self.FILL[None, :, :], (H, W, 3)), outline=False)
        for y0, y1, x in edges:
            band = f.text.mask[y0:y1, max(0, x - 1):x + 1]
            out[y0:y1, max(0, x - 1):x + 1][band] = 255
        return out


class Plasma(Effect):
    # Swirling plasma behind outlined white text; new lines fade in
    name = 'Plasma'
    RADIUS = np.sqrt((XX - 128) ** 2 + ((YY - 16) * 3) ** 2)

    def render(self, f):
        t = f.t
        v = (np.sin(XX / 19 + t * 1.1) + np.sin(YY / 5 + t * 1.7) + np.sin((XX + YY * 3) / 27 - t * 0.8)
             + np.sin(self.RADIUS / 11 - t * 2.2))
        out = PLASMA[(((v + 4) * 32 + t * 30) % 256).astype(np.uint8)] * 0.35
        paint(out, f.text, (255, 255, 255), alpha=min(1.0, f.age / 0.25))
        return out


class Glitch(Effect):
    # Chromatic-split text over scanlines, with bursts of slice-shifting glitches
    name = 'Glitch'

    def __init__(self):
        self.burstUntil = 0.0
        self.nextBurst = 2.0

    def render(self, f):
        if f.t >= self.nextBurst:
            self.burstUntil = f.t + random.uniform(0.08, 0.2)
            self.nextBurst = f.t + random.uniform(1.2, 3.5)
        burst = f.age < 0.3 or f.t < self.burstUntil
        dx = random.randint(2, 5) if burst else 1
        m, shade = f.text.mask.astype(np.float32) * f.text.shade, f.text.shade
        out = np.zeros((H, W, 3), np.float32)
        out[::2] = (0, 0, 14)
        out[:, :, 0] += shift(m, 0, -dx) * 255
        out[:, :, 1] += m * 255
        out[:, :, 2] += shift(m, 0, dx) * 255
        if burst:
            for _ in range(random.randint(2, 4)):
                y0 = random.randint(0, H - 2)
                y1 = min(H, y0 + random.randint(2, 7))
                out[y0:y1] = np.roll(out[y0:y1], random.randint(-14, 14), axis=1)
            if random.random() < 0.3:
                x0, y0 = random.randint(0, W - 20), random.randint(0, H - 4)
                out[y0:y0 + random.randint(1, 4), x0:x0 + random.randint(6, 30)] = random.choice(
                    [(255, 0, 90), (0, 255, 200), (90, 90, 255)])
        return out


class Hyperspace(Effect):
    # Warp-speed starfield; new lines drop in from the top
    name = 'Hyperspace'
    STARS = 240

    def __init__(self):
        self.x = np.random.uniform(-1, 1, self.STARS)
        self.y = np.random.uniform(-1, 1, self.STARS)
        self.z = np.random.uniform(0.05, 1, self.STARS)

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        speed = 0.55
        self.z -= f.dt * speed
        gone = self.z <= 0.04
        n = int(gone.sum())
        self.x[gone], self.y[gone] = np.random.uniform(-1, 1, n), np.random.uniform(-1, 1, n)
        self.z[gone] = 1.0
        # Each star is drawn as a short streak from slightly further back to where it is now
        for back in (0.0, 0.015, 0.03, 0.045):
            z = self.z + back * speed
            sx = (128 + self.x / z * 60).astype(int)
            sy = (16 + self.y / z * 10).astype(int)
            ok = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
            bright = (np.clip((1.1 - z) * 2.0, 0, 1) * (1 - back * 15))[ok]
            out[sy[ok], sx[ok]] = np.maximum(out[sy[ok], sx[ok]], bright[:, None] * (170, 200, 255))
        k = ease(f.age / 0.25)
        if k < 1:
            dy = int(round((1 - k) * H))
            if f.prev is not None:
                paint(out, f.prev.moved(H - dy), (220, 240, 255))
            paint(out, f.text.moved(-dy), (220, 240, 255))
        else:
            paint(out, f.text, (220, 240, 255))
        return out


class Equalizer(Effect):
    # Bouncing spectrum bars that kick on the beat; new lines type themselves out
    name = 'Equalizer'
    BARS, BAR_WIDTH = 32, 8

    def __init__(self):
        self.level = np.zeros(self.BARS, np.float32)
        self.target = np.zeros(self.BARS, np.float32)
        self.peak = np.zeros(self.BARS, np.float32)
        self.bass = np.linspace(1, 0, self.BARS) ** 2

    def render(self, f):
        beat = (f.t * BPM / 60.0) % 1.0
        kick = math.exp(-beat * 6)
        self.target = 0.55 * self.target + 0.45 * np.random.uniform(0.1, 1.0, self.BARS) ** 1.2
        goal = np.clip(self.target + kick * self.bass * 0.9, 0, 1)
        self.level += (goal - self.level) * 0.5
        self.peak = np.maximum(self.peak - f.dt * 0.6, self.level)
        bar = (XX // self.BAR_WIDTH).astype(int)
        inBar = (XX % self.BAR_WIDTH) < self.BAR_WIDTH - 2
        lit = inBar & (YY >= H - self.level[bar] * H)
        out = np.zeros((H, W, 3), np.float32)
        out[lit] = np.broadcast_to(SPECTRUM[:, None, :], (H, W, 3))[lit] * 0.55
        capRow = np.clip((H - 1 - self.peak * (H - 1)).astype(int), 0, H - 1)
        caps = inBar & (YY.astype(int) == capRow[bar])
        out[caps] = 110
        shown, edges = f.text.revealed(min(1.0, f.age / 0.35))
        typed = Text.__new__(Text)
        typed.mask, typed.outline, typed.shade = f.text.mask & shown, f.text.outline & shown, f.text.shade
        paint(out, typed, (255, 255, 255))
        return out


EFFECTS = [Rainbow, Neon, Fire, Karaoke, Plasma, Glitch, Hyperspace, Equalizer]


def toBytes(frame):
    return np.clip(frame, 0, 255).astype(np.uint8)

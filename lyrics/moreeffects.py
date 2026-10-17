# More animated effects for the lyrics display (see effects.py for the framework).
import math
import random
import numpy as np
from effects import (Effect, Text, H, W, YY, XX, XI, BPM, RAINBOW, gradient, ease, shift, paint,
                     outlineOf)


def beatPhase(t):
    # 0..1 position within the current beat (at BPM)
    return (t * BPM / 60.0) % 1.0


def beatNumber(t):
    return int(t * BPM / 60.0)


def bigLetters(text):
    # True when the text is one line (lots of free rows above and below it)
    return len(text.boxes) == 1


def additive(out, ys, xs, colors):
    # Adds colours at pixel coordinates, ignoring ones off the panel
    ok = (ys >= 0) & (ys < H) & (xs >= 0) & (xs < W)
    np.add.at(out, (ys[ok], xs[ok]), colors[ok] if np.ndim(colors) == 2 else colors)


def movedLines(text, offsets):
    # Each line's own mask with its columns moved by offsets[i] (no outline: cheap enough for
    # per-letter motion every frame). Returns [(mask, shade)] per line.
    from effects import columnShift
    moved = []
    for (x0, y0, x1, y1, shade, string), dy in zip(text.boxes, offsets):
        band = np.zeros((H, W), bool)
        band[y0:y1] = text.mask[y0:y1]
        moved.append((columnShift(band, dy), shade))
    return moved


class Wave(Effect):
    # Letters ripple up and down like a flag, in a flowing aqua-to-violet gradient
    name = 'Wave'
    COLORS = gradient([(0, (0, 255, 220)), (0.5, (120, 120, 255)), (1, (255, 60, 220))])

    def render(self, f):
        amplitude = 5 if bigLetters(f.text) else 2
        offsets = [np.round(amplitude * np.sin(XX[0] / 11.0 - f.t * 6 + i * 1.3)).astype(int)
                   for i in range(len(f.text.boxes))]
        columnColor = self.COLORS[((XX[0] * 0.8 - f.t * 70) % 256).astype(np.uint8)]
        alpha = min(1.0, f.age / 0.2)
        out = np.zeros((H, W, 3), np.float32)
        for mask, shade in movedLines(f.text, offsets):
            out[mask] = columnColor[XI[mask]] * (shade * alpha)
        return out


class Bounce(Effect):
    # Each new line's letters drop in one at a time and bounce; then they hop on the beat
    name = 'Bounce'
    CANDY = [(255, 80, 120), (255, 200, 40), (80, 230, 120), (60, 190, 255), (200, 110, 255)]

    @staticmethod
    def bounceOut(p):
        # Standard "ease out bounce": 0..1 with a few decaying bounces at the end
        if p < 1 / 2.75:
            return 7.5625 * p * p
        if p < 2 / 2.75:
            p -= 1.5 / 2.75
            return 7.5625 * p * p + 0.75
        if p < 2.5 / 2.75:
            p -= 2.25 / 2.75
            return 7.5625 * p * p + 0.9375
        p -= 2.625 / 2.75
        return 7.5625 * p * p + 0.984375

    def render(self, f):
        hop = 2 if bigLetters(f.text) else 1
        beat = beatPhase(f.t)
        if getattr(self, 'spansFor', None) is not f.text:
            self.spansFor, self.spans = f.text, f.text.charSpans()
        offsets, colors = [], []
        letter = 0
        for (x0, y0, x1, y1, s, string), spans in zip(f.text.boxes, self.spans):
            dy = np.zeros(W, int)
            color = np.zeros((W, 3), np.float32)
            for a, b in spans:
                drop = f.age - letter * 0.035
                if drop < 0.6:
                    # Falling in from above the panel
                    dy[a:b] = -int(round((1 - self.bounceOut(max(0.0, drop / 0.6))) * (y1 + 4)))
                else:
                    # Hop on the beat, rippling along the line
                    phase = (beat - letter * 0.04) % 1.0
                    dy[a:b] = -int(round(hop * math.exp(-phase * 8)))
                color[a:b] = self.CANDY[letter % len(self.CANDY)]
                letter += 1
            offsets.append(dy)
            colors.append(color)
        out = np.zeros((H, W, 3), np.float32)
        # Letters only move vertically, so each keeps its colour by column
        for (mask, shade), color in zip(movedLines(f.text, offsets), colors):
            out[mask] = color[XI[mask]] * shade
        return out


# --- Earth ---------------------------------------------------------------------------------
# Land by 5-degree latitude band: (west, east) longitude ranges. Coarse, but at this size it
# reads clearly as the continents.
LAND = {
    85: [(-60, -30)],
    80: [(-95, -65), (-65, -20), (15, 30), (90, 105)],
    75: [(-125, -80), (-60, -20), (55, 65), (80, 115)],
    70: [(-165, -140), (-135, -95), (-90, -70), (-55, -22), (15, 32), (60, 180)],
    65: [(-168, -140), (-140, -62), (-52, -38), (-24, -14), (8, 32), (32, 180)],
    60: [(-165, -140), (-138, -64), (-48, -42), (5, 30), (30, 165)],
    55: [(-132, -95), (-80, -60), (-6, 0), (8, 30), (30, 140), (155, 162)],
    50: [(-127, -55), (-5, 2), (2, 140)],
    45: [(-124, -62), (-2, 40), (40, 135), (140, 145)],
    40: [(-124, -72), (-9, 3), (8, 18), (20, 45), (45, 122), (130, 142)],
    35: [(-120, -77), (-10, 35), (35, 60), (60, 120), (132, 140)],
    30: [(-115, -95), (-85, -80), (-10, 32), (35, 50), (50, 90), (90, 122)],
    25: [(-110, -97), (-15, 35), (37, 57), (68, 90), (92, 120)],
    20: [(-105, -87), (-84, -75), (-17, 40), (40, 58), (72, 87), (93, 110)],
    15: [(-92, -84), (-17, 42), (43, 52), (74, 80), (97, 109), (120, 125)],
    10: [(-85, -77), (-75, -62), (-15, 50), (76, 80), (98, 106), (122, 126)],
    5: [(-77, -52), (-10, 48), (100, 104), (110, 118)],
    0: [(-80, -50), (9, 42), (98, 106), (109, 118), (120, 125)],
    -5: [(-81, -35), (12, 40), (105, 115), (132, 150)],
    -10: [(-78, -36), (13, 40), (106, 115), (130, 150)],
    -15: [(-76, -39), (12, 40), (44, 50), (125, 145)],
    -20: [(-70, -40), (13, 35), (44, 48), (115, 150)],
    -25: [(-70, -48), (15, 33), (45, 47), (113, 153)],
    -30: [(-71, -51), (17, 31), (115, 153)],
    -35: [(-72, -57), (18, 25), (117, 150)],
    -40: [(-73, -62), (140, 148), (172, 178)],
    -45: [(-74, -66), (167, 172)],
    -50: [(-75, -68)],
    -55: [(-72, -65)],
    -60: [],
    -65: [(-65, -55), (40, 170)],
    -70: [(-180, 180)], -75: [(-180, 180)], -80: [(-180, 180)], -85: [(-180, 180)],
}


def earthTexture(rows=72, cols=144):
    # Equirectangular colour map: ocean, green land, tan deserts, white ice
    tex = np.zeros((rows, cols, 3), np.float32)
    rng = np.random.RandomState(7)
    for r in range(rows):
        lat = 90 - (r + 0.5) * 180.0 / rows
        band = int(round(lat / 5.0)) * 5
        band = max(-85, min(85, band))
        for c in range(cols):
            lon = -180 + (c + 0.5) * 360.0 / cols
            land = any(a <= lon <= b for a, b in LAND[band])
            if not land:
                tex[r, c] = (10, 50, 150)
            elif abs(lat) >= 62:
                tex[r, c] = (230, 240, 250)
            elif (15 <= lat <= 35 and -15 <= lon <= 60) or (-30 <= lat <= -18 and 118 <= lon <= 145):
                tex[r, c] = (200, 160, 90)
            else:
                tex[r, c] = (40, 150 + rng.randint(-30, 30), 50)
    return tex


class Earth(Effect):
    # A shaded, tilted globe with real continents, spinning behind the text in a starfield
    name = 'Earth'
    TEXTURE = earthTexture()

    def __init__(self):
        r, cx, cy = 15.5, 128.0, 15.5
        nx, ny = (XX + 0.5 - cx) / r, (YY + 0.5 - cy) / r
        d2 = nx ** 2 + ny ** 2
        self.disc = d2 < 1
        nz = np.sqrt(np.clip(1 - d2, 0, 1))
        tilt = math.radians(23.4)
        # Tip the globe so the north pole leans toward the viewer
        y2 = ny * math.cos(tilt) - nz * math.sin(tilt)
        z2 = ny * math.sin(tilt) + nz * math.cos(tilt)
        lat = np.degrees(np.arcsin(np.clip(-y2, -1, 1)))
        lon = np.degrees(np.arctan2(nx, z2))
        rows, cols = self.TEXTURE.shape[:2]
        self.row = np.clip(((90 - lat) / 180.0 * rows).astype(int), 0, rows - 1)
        self.col = ((lon + 180) / 360.0 * cols).astype(int)
        # Sunlight from the upper left, plus a little ambient so the night side isn't black
        light = np.clip(-0.55 * nx - 0.45 * ny + 0.7 * nz, 0, 1)
        self.light = (0.15 + 0.85 * light)[:, :, None]
        # Thin blue atmosphere just outside the disc
        dist = np.sqrt(d2)
        self.halo = (np.clip(1 - (dist - 1) * 6, 0, 1) * (dist >= 1))[:, :, None] * np.array((40, 90, 255))
        rng = np.random.RandomState(3)
        self.stars = (rng.uniform(0, 1, (H, W)) > 0.985) & ~(dist < 1.3)
        self.twinkle = rng.uniform(0, 6.3, (H, W))

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        tw = (0.4 + 0.3 * np.sin(f.t * 3 + self.twinkle)) * self.stars
        out += tw[:, :, None] * 255
        out += self.halo * 0.8
        cols = self.TEXTURE.shape[1]
        spin = int(f.t * 18) % cols
        surface = self.TEXTURE[self.row, (self.col + spin) % cols] * self.light
        out[self.disc] = surface[self.disc] * 0.8
        paint(out, f.text, (255, 255, 255), alpha=min(1.0, f.age / 0.25))
        return out


class Lasers(Effect):
    # Laser beams streak across on the beat; new lines are written in by a laser scanner
    name = 'Lasers'
    COLORS = [(255, 20, 40), (0, 255, 80), (0, 200, 255), (255, 0, 220), (255, 230, 0)]

    def __init__(self):
        self.beams = []       # [row, head x, direction, speed, length, colour]
        self.lastBeat = -1

    def render(self, f):
        beat = beatNumber(f.t)
        if beat != self.lastBeat:
            self.lastBeat = beat
            for _ in range(random.randint(1, 3)):
                direction = random.choice((-1, 1))
                self.beams.append([random.randint(1, H - 2), -10 if direction > 0 else W + 10, direction,
                                   random.uniform(350, 650), random.randint(30, 90),
                                   np.array(random.choice(self.COLORS), np.float32)])
        elif random.random() < 0.04:
            direction = random.choice((-1, 1))
            self.beams.append([random.randint(1, H - 2), -10 if direction > 0 else W + 10, direction,
                               random.uniform(500, 800), random.randint(15, 40),
                               np.array(random.choice(self.COLORS), np.float32)])
        out = np.zeros((H, W, 3), np.float32)
        alive = []
        for beam in self.beams:
            beam[1] += beam[2] * beam[3] * f.dt
            row, head, direction, speed, length, color = beam
            tail = head - direction * length
            a, b = int(min(head, tail)), int(max(head, tail))
            if b < 0 or a >= W:
                continue
            alive.append(beam)
            xs = np.arange(max(0, a), min(W, b + 1))
            # Brightest at the head, fading toward the tail
            fade = 1 - np.abs(xs - head) / float(length)
            out[row, xs] += color * fade[:, None]
            for glowRow in (row - 1, row + 1):
                if 0 <= glowRow < H:
                    out[glowRow, xs] += color * fade[:, None] * 0.3
            hx = int(head)
            if 0 <= hx < W:
                out[row, hx] = 255
        self.beams = alive[-40:]
        # Scanner reveal: a vertical laser sweeps across, drawing the new line behind it
        sweep = f.age / 0.35
        text = f.text
        if sweep < 1:
            x = int(sweep * W)
            visible = XX < x
            text = Text.__new__(Text)
            text.mask, text.outline, text.shade = f.text.mask & visible, f.text.outline & visible, f.text.shade
            out[:, max(0, x - 1):x + 1] += (0, 230, 255)
        paint(out, text, (230, 250, 255))
        return out


class Matrix(Effect):
    # Green digital rain behind glowing green text
    name = 'Matrix'

    def __init__(self):
        self.columns = np.arange(0, W, 2)
        n = len(self.columns)
        self.head = np.random.uniform(-H, H, n).astype(np.float32)
        self.speed = np.random.uniform(12, 40, n).astype(np.float32)
        self.length = np.random.uniform(6, 22, n).astype(np.float32)
        self.glyphs = np.random.uniform(0.35, 1, (H, n)).astype(np.float32)

    def render(self, f):
        self.head += self.speed * f.dt
        done = self.head - self.length > H
        k = int(done.sum())
        self.head[done] = np.random.uniform(-12, 0, k)
        self.speed[done] = np.random.uniform(12, 40, k)
        # Glyphs flicker: a few cells change brightness each frame
        flip = np.random.uniform(0, 1, self.glyphs.shape) < 0.04
        self.glyphs[flip] = np.random.uniform(0.35, 1, int(flip.sum()))
        dist = self.head[None, :] - YY[:, :len(self.columns)]
        trail = np.clip(1 - dist / self.length[None, :], 0, 1) * (dist >= 0) * self.glyphs
        out = np.zeros((H, W, 3), np.float32)
        out[:, self.columns, 1] = trail * 170
        out[:, self.columns, 0] = trail * 20
        lead = (dist >= 0) & (dist < 1)
        out[:, self.columns][lead] = (180, 255, 180)
        heads = np.zeros((H, len(self.columns), 3), np.float32)
        heads[lead] = (180, 255, 180)
        out[:, self.columns] = np.maximum(out[:, self.columns], heads)
        out *= 0.6
        paint(out, f.text, (170, 255, 170), alpha=min(1.0, f.age / 0.2))
        return out


class Fireworks(Effect):
    # Rockets launch on the beat and burst into falling, fading sparks behind the text
    name = 'Fireworks'
    COLORS = [(255, 60, 60), (255, 200, 40), (60, 255, 120), (80, 160, 255), (255, 90, 255), (255, 255, 255)]
    MAX_SPARKS = 600

    def __init__(self):
        self.rockets = []     # [x, y, vy, burstHeight, colour]
        self.sparks = np.zeros((0, 8), np.float32)   # x, y, vx, vy, life, r, g, b
        self.lastBeat = -1

    def render(self, f):
        beat = beatNumber(f.t)
        if beat != self.lastBeat:
            self.lastBeat = beat
            if beat % 2 == 0 or random.random() < 0.3:
                self.rockets.append([random.uniform(20, W - 20), H, random.uniform(-38, -28),
                                     random.uniform(3, 12), random.choice(self.COLORS)])
        out = np.zeros((H, W, 3), np.float32)
        remaining = []
        for rocket in self.rockets:
            rocket[1] += rocket[2] * f.dt
            if rocket[1] <= rocket[3]:
                n = random.randint(40, 70)
                angle = np.random.uniform(0, 2 * math.pi, n)
                speed = np.random.uniform(8, 28, n)
                color = np.array(rocket[4], np.float32)
                if random.random() < 0.4:
                    color = np.array(random.choice(self.COLORS), np.float32)
                burst = np.column_stack([np.full(n, rocket[0]), np.full(n, rocket[1]),
                                         np.cos(angle) * speed * 1.6, np.sin(angle) * speed,
                                         np.random.uniform(0.9, 1.6, n),
                                         np.tile(color, (n, 1))]).astype(np.float32)
                self.sparks = np.vstack([self.sparks, burst])[-self.MAX_SPARKS:]
            else:
                remaining.append(rocket)
                y, x = int(rocket[1]), int(rocket[0])
                for k, trail in enumerate((1.0, 0.5, 0.25)):
                    if 0 <= y + k < H:
                        out[y + k, x] += np.array((255, 200, 120)) * trail
        self.rockets = remaining
        s = self.sparks
        if len(s):
            s[:, 0] += s[:, 2] * f.dt
            s[:, 1] += s[:, 3] * f.dt
            s[:, 3] += 18 * f.dt
            s[:, 2:4] *= 1 - 0.9 * f.dt
            s[:, 4] -= f.dt
            s = s[s[:, 4] > 0]
            fade = np.clip(s[:, 4], 0, 1)[:, None]
            # Sparks twinkle as they die
            twinkle = np.where(s[:, 4] < 0.4, np.random.uniform(0, 1, len(s)), 1.0)[:, None]
            additive(out, s[:, 1].astype(int), s[:, 0].astype(int), s[:, 5:8] * fade * twinkle)
            self.sparks = s
        paint(out, f.text, (255, 255, 255), alpha=min(1.0, f.age / 0.2))
        return out


class Synthwave(Effect):
    # Retro sunset: striped sun on the horizon and a neon grid floor rushing toward you
    name = 'Synthwave'
    HORIZON = 21

    def __init__(self):
        sky = gradient([(0, (10, 0, 30)), (0.7, (70, 0, 80)), (1, (150, 20, 90))], self.HORIZON)
        self.background = np.zeros((H, W, 3), np.float32)
        self.background[:self.HORIZON] = sky[:, None, :]
        # Sun: a disc sitting on the horizon, yellow to pink, with stripes cut out of its lower half
        cx, cy, r = 128, self.HORIZON, 21
        d = np.sqrt((XX - cx) ** 2 + ((YY - cy) * 1.0) ** 2)
        sunColors = gradient([(0, (255, 230, 60)), (1, (255, 40, 140))], H)
        sun = (d < r) & (YY < self.HORIZON)
        gaps = (YY > cy - 9) & (((YY - (cy - 9)) % 3) == 0)
        self.sun = sun & ~gaps
        self.background[self.sun] = sunColors[YY.astype(int)][self.sun] * 0.75
        self.background[self.HORIZON + 1:] = (12, 0, 25)
        # Floor lines converge on the vanishing point at the centre of the horizon
        floorRows = H - 1 - self.HORIZON
        for y in range(self.HORIZON + 1, H):
            spread = (y - self.HORIZON) / float(floorRows)
            for k in range(-24, 25):
                x = int(round(128 + k * 30 * spread))
                if 0 <= x < W:
                    self.background[y, x] = (180, 20, 150)
        self.background[self.HORIZON] = (255, 120, 220)

    def render(self, f):
        out = self.background.copy()
        # Cross lines rush toward the viewer, speeding up and spreading out as they come closer
        floorRows = H - 1 - self.HORIZON
        for i in range(4):
            p = ((i + f.t * 1.2) % 4) / 4.0
            y = self.HORIZON + 1 + int(p * p * floorRows)
            out[y] = (255, 40, 210)
        color = gradient([(0, (0, 240, 255)), (1, (255, 90, 230))], H)[YY.astype(int)]
        paint(out, f.text, color, alpha=min(1.0, f.age / 0.2))
        return out


class Disco(Effect):
    # Coloured spotlights sweep the panel like a disco ball, with sparkles; pulses on the beat
    name = 'Disco'
    COLORS = np.array([(255, 0, 120), (0, 160, 255), (255, 200, 0), (120, 255, 0), (180, 0, 255)], np.float32)

    def __init__(self):
        self.phase = np.random.uniform(0, 6.3, (len(self.COLORS), 2))
        self.speed = np.random.uniform(0.5, 1.3, (len(self.COLORS), 2))

    def render(self, f):
        pulse = 0.65 + 0.35 * math.exp(-beatPhase(f.t) * 5)
        xs, ys = XX[0], YY[:, 0]
        cx = 128 + 120 * np.sin(f.t * self.speed[:, 0] + self.phase[:, 0])
        cy = 16 + 14 * np.sin(f.t * self.speed[:, 1] * 1.7 + self.phase[:, 1])
        # Each round spotlight is a row profile times a column profile, so summing all of them
        # per colour channel is one small matrix product: (H x spots) @ (spots x W)
        rows = np.exp(-((ys[:, None] - cy[None, :]) / 10.0) ** 2)
        cols = np.exp(-((xs[None, :] - cx[:, None]) / 22.0) ** 2)
        out = np.empty((H, W, 3), np.float32)
        for c in range(3):
            out[:, :, c] = (rows * (self.COLORS[:, c] * 0.55 * pulse)) @ cols
        sparkle = np.random.uniform(0, 1, (H, W)) > 0.997
        out[sparkle] = 255
        paint(out, f.text, (255, 255, 255), alpha=min(1.0, f.age / 0.2))
        return out


class Storm(Effect):
    # Rain, and lightning bolts that light up the whole panel
    name = 'Storm'

    def __init__(self):
        self.drops = np.column_stack([np.random.uniform(0, W, 90), np.random.uniform(0, H, 90),
                                      np.random.uniform(50, 80, 90)]).astype(np.float32)
        self.nextStrike = 1.5
        self.strike = None    # (start time, bolt pixel ys, xs)

    def bolt(self):
        x = random.uniform(30, W - 30)
        ys, xs = [], []
        branches = [(x, 0.0)]
        while branches:
            x, y = branches.pop()
            while y < H:
                ys.append(int(y))
                xs.append(int(x))
                x += random.choice((-1, -1, 0, 1, 1)) * random.uniform(0.5, 2)
                y += 1
                if random.random() < 0.06 and len(branches) < 3:
                    branches.append((x, y))
        return np.array(ys), np.clip(np.array(xs), 0, W - 1)

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        out[:] = (6, 8, 18)
        d = self.drops
        d[:, 1] += d[:, 2] * f.dt
        d[:, 0] += d[:, 2] * 0.25 * f.dt
        wrap = d[:, 1] > H
        d[wrap, 1] -= H + 4
        d[wrap, 0] = np.random.uniform(-10, W, int(wrap.sum()))
        for k in range(3):
            additive(out, (d[:, 1] - k).astype(int), (d[:, 0] - k * 0.25).astype(int),
                     np.array((60, 80, 130), np.float32) * (1 - k * 0.3))
        if f.t >= self.nextStrike:
            self.strike = (f.t,) + self.bolt()
            self.nextStrike = f.t + random.uniform(2, 6)
        textColor = (235, 240, 255)
        if self.strike is not None:
            age = f.t - self.strike[0]
            flicker = [1, 0.2, 1, 0.6, 0.3]
            step = int(age / 0.05)
            if step < len(flicker):
                level = flicker[step]
                out += np.array((70, 70, 110), np.float32) * level
                out[self.strike[1], self.strike[2]] = np.array((230, 220, 255)) * level
                textColor = (200, 210, 255)
            else:
                self.strike = None
        paint(out, f.text, textColor, alpha=min(1.0, f.age / 0.2))
        return out


class Aurora(Effect):
    # Flowing northern-lights curtains over a faint starfield
    name = 'Aurora'
    COLORS = gradient([(0, (0, 0, 0)), (0.35, (0, 120, 60)), (0.7, (40, 255, 140)), (1, (180, 120, 255))])

    def __init__(self):
        rng = np.random.RandomState(5)
        self.stars = rng.uniform(0, 1, (H, W)) > 0.99

    def render(self, f):
        t = f.t
        # The curtain's lower edge waves across the panel; light fades upward from it
        edge = (20 + 5 * np.sin(XX[0] / 23.0 + t * 0.7) + 3 * np.sin(XX[0] / 9.0 - t * 1.3))
        brightness = 0.6 + 0.4 * np.sin(XX[0] / 17.0 + t * 0.9) * np.sin(XX[0] / 41.0 - t * 0.4)
        height = edge[None, :] - YY
        curtain = np.clip(1 - height / 22.0, 0, 1) * (height >= 0) * brightness[None, :]
        rays = 0.75 + 0.25 * np.sin(XX * 0.9 + t * 2)
        level = np.clip(curtain * rays, 0, 1)
        out = self.COLORS[(level * 255).astype(np.uint8)] * 0.7
        out[self.stars & (level < 0.1)] = 90
        paint(out, f.text, (255, 255, 255), alpha=min(1.0, f.age / 0.3))
        return out


class PacMan(Effect):
    # Pac-Man and two ghosts chomp across the old line, revealing the new one behind them
    name = 'Pac-Man'
    SPEED = 420.0

    def sprite(self, out, kind, cx, cy, t, color):
        r = 6.5
        y0, y1 = max(0, int(cy - 7)), min(H, int(cy + 8))
        x0, x1 = max(0, int(cx - 7)), min(W, int(cx + 8))
        if y0 >= y1 or x0 >= x1:
            return
        dx, dy = XX[y0:y1, x0:x1] - cx, YY[y0:y1, x0:x1] - cy
        region = out[y0:y1, x0:x1]
        if kind == 'pac':
            mouth = abs(math.sin(t * 18)) * 0.8
            angle = np.abs(np.arctan2(dy, dx))
            body = (dx ** 2 + dy ** 2 <= r * r) & (angle > mouth)
            region[body] = (255, 230, 0)
        else:
            head = (dx ** 2 + dy ** 2 <= r * r) & (dy <= 0)
            skirt = (np.abs(dx) <= r) & (dy > 0) & (dy <= r - (np.floor((dx + r + t * 20) / 2.5) % 2))
            region[head | skirt] = color
            for ex in (-2.5, 2.5):
                eye = ((dx - ex) ** 2 + (dy + 1.5) ** 2) <= 3.2
                region[eye] = (255, 255, 255)
                pupil = ((dx - ex - 1) ** 2 + (dy + 1.5) ** 2) <= 1.0
                region[pupil] = (30, 60, 255)

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        # Pellets along the bottom edge for atmosphere
        out[H - 2, 4::8] = (120, 100, 60)
        x = -10 + f.age * self.SPEED
        textColor = (255, 255, 255)
        if f.prev is not None and x < W + 60:
            # Old line still ahead of Pac-Man, new line already behind him
            behind = XX < x
            old = Text.__new__(Text)
            old.mask, old.outline, old.shade = f.prev.mask & ~behind, f.prev.outline & ~behind, f.prev.shade
            new = Text.__new__(Text)
            new.mask, new.outline, new.shade = f.text.mask & behind, f.text.outline & behind, f.text.shade
            paint(out, old, textColor)
            paint(out, new, textColor)
            cy = 16
            self.sprite(out, 'pac', x, cy, f.t, None)
            self.sprite(out, 'ghost', x - 22, cy, f.t, (255, 40, 40))
            self.sprite(out, 'ghost', x - 40, cy, f.t, (255, 140, 220))
        else:
            paint(out, f.text, textColor)
        return out


EFFECTS = [Wave, Earth, Lasers, Matrix, Fireworks, Synthwave, Disco, Storm, Bounce, Aurora, PacMan]

# Club effects for the lyrics display: high-energy, high-motion scenes for parties.
# Several of these flash quickly (Strobe, Bass Drop's snare roll, Sirens); see STROBE_FLASHES_PER_BEAT.
import math
import random
import numpy as np
from PIL import Image
from effects import Effect, Text, H, W, YY, XX, YI, XI, BPM, RAINBOW, gradient, paint, shift
from moreeffects import beatPhase, beatNumber, additive
from partyeffects import PARTY, fadeIn

# Strobe flashes per beat (2 = 4 flashes a second at 120 BPM). Lower it for a gentler strobe.
STROBE_FLASHES_PER_BEAT = 2


def beats(t):
    return t * BPM / 60.0


def kick(t, sharpness=6.0):
    # 1 on the beat, decaying to 0 before the next
    return math.exp(-beatPhase(t) * sharpness)


def shaken(text, amount):
    # The text nudged by up to 'amount' pixels in a random direction
    if amount <= 0:
        return text
    return text.moved(random.randint(-amount, amount), random.randint(-amount, amount))


class Strobe(Effect):
    # Constant strobe: the whole panel flashes on the beat subdivisions; the lyrics become a black
    # cut-out during each flash so they stay readable, with a faint afterglow between flashes
    name = 'Strobe'
    LIT = 0.13      # fraction of each flash interval that's lit (~30 ms at 120 BPM)

    def render(self, f):
        n = beats(f.t) * STROBE_FLASHES_PER_BEAT
        flash, phase = int(n), n % 1.0
        color = np.array((255, 255, 255) if flash % 8 != 7 else PARTY[(flash // 8) % 6], np.float32)
        if phase < self.LIT:
            out = np.empty((H, W, 3), np.float32)
            out[:] = color * 0.9
            paint(out, f.text, (0, 0, 0), outline=False)
        else:
            out = np.empty((H, W, 3), np.float32)
            out[:] = color * (0.12 * math.exp(-(phase - self.LIT) * 9))
            paint(out, f.text, (255, 255, 255))
        return out


class BassDrop(Effect):
    # A 16-beat loop: speed lines and a riser build the tension while the text shakes harder,
    # a snare-roll strobe speeds up, then the drop: white-out, shockwave and screen shake
    name = 'Bass Drop'

    def __init__(self):
        n = 70
        self.y = np.random.randint(0, H, n)
        self.x = np.random.uniform(0, 128, n).astype(np.float32)
        self.side = np.where(np.arange(n) % 2 == 0, -1, 1)
        self.radius = np.sqrt(((XX + 0.5 - 128) / 5.0) ** 2 + (YY + 0.5 - 16) ** 2)

    def render(self, f):
        c = beats(f.t) % 16
        out = np.zeros((H, W, 3), np.float32)
        if c < 2:
            # The drop: white-out fading into a rainbow shockwave, heavy shake
            out[:] = 255 * math.exp(-c * 5)
            ring = np.clip(1 - np.abs(self.radius - c * 30) / 2.5, 0, 1) * math.exp(-c * 1.2)
            out += RAINBOW[((self.radius * 6 - c * 200) % 256).astype(np.uint8)] * ring[:, :, None]
            text = shaken(f.text, int(3 * math.exp(-c * 2)))
            paint(out, text, (255, 255, 255) if c > 0.3 else (0, 0, 0), outline=c > 0.3)
            return out
        build = (c - 2) / 14.0
        # Speed lines rush in from both sides toward the centre, faster as the build rises
        speed = 60 + build * 520
        self.x += speed * f.dt
        self.x %= 128
        length = int(3 + build * 22)
        k = np.arange(length)
        xs = np.where(self.side[:, None] < 0, self.x[:, None] - k, W - 1 - self.x[:, None] + k).astype(int).ravel()
        ys = np.repeat(self.y, length)
        fade = np.tile(1 - k / float(length), len(self.y))[:, None] * (0.3 + build)
        additive(out, ys, xs, np.array((120, 150, 255), np.float32) * fade)
        # Riser bar along the bottom, filling from the centre outward and heating up
        half = int(build * 128)
        out[H - 1, 128 - half:128 + half] = np.array((255, 255 * (1 - build), 80 * (1 - build)))
        if c >= 12:
            # Snare roll: 1, 2, 4, then 8 flashes per beat
            rate = 2 ** int(c - 12)
            if (c * rate) % 1.0 < 0.25:
                out += 110
        paint(out, shaken(f.text, int(build * 2.5)), (255, 255, 255))
        return out


class Shockwave(Effect):
    # Every kick blasts a coloured ring out from the centre like a speaker cone; the text jolts
    name = 'Shockwave'

    def __init__(self):
        self.radius = np.sqrt(((XX + 0.5 - 128) / 5.0) ** 2 + (YY + 0.5 - 16) ** 2).ravel()
        self.glow = np.exp(-self.radius / 5.0).astype(np.float32)

    def render(self, f):
        b = beats(f.t)
        layers, colors = [], []
        for back in range(3):
            beat = int(b) - back
            age = b - beat
            layers.append(np.clip(1 - np.abs(self.radius - age * 42) * 0.5, 0, 1) * math.exp(-age * 1.2))
            colors.append(PARTY[beat % 6])
        layers.append(self.glow * (0.5 * kick(f.t, 8)))
        colors.append((255, 255, 255))
        # Every layer times its colour, summed, in one (3 x layers) @ (layers x pixels) product
        out = (np.array(colors, np.float32).T @ np.array(layers, np.float32)).T.reshape(H, W, 3).copy()
        jolt = 1 if beatPhase(f.t) < 0.08 else 0
        paint(out, f.text.moved(jolt) if jolt else f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class Rave(Effect):
    # A fast-spinning psychedelic rainbow spiral that surges on the beat
    name = 'Rave'

    def __init__(self):
        dx, dy = (XX + 0.5 - 128) / 3.0, YY + 0.5 - 16
        self.angle = np.arctan2(dy, dx)
        self.radius = np.sqrt(dx ** 2 + dy ** 2)
        self.spin = 0.0

    def render(self, f):
        self.spin += f.dt * (3 + 6 * kick(f.t, 4))
        arms = np.sin(self.angle * 5 + self.radius * 0.35 - self.spin * 2)
        hue = ((self.angle * (256 / math.pi) + self.radius * 4 - f.t * 120) % 256).astype(np.uint8)
        out = RAINBOW[hue] * (np.clip(arms * 0.5 + 0.5, 0, 1) ** 2 * 0.5)[:, :, None]
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class LaserFan(Effect):
    # Two club laser projectors fan their beams across each other, spreading on the beat
    name = 'Laser Fan'
    BEAMS = 7

    def __init__(self):
        self.sources = []
        for sx in (64.0, 192.0):
            dx, dy = XX + 0.5 - sx, YY + 0.5 + 3
            self.sources.append((np.arctan2(dx, dy), np.sqrt(dx ** 2 + dy ** 2)))

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        spacing = 0.1 + 0.08 * kick(f.t, 5)
        half = self.BEAMS // 2
        for s, (angle, dist) in enumerate(self.sources):
            aim = 0.55 * math.sin(f.t * 0.9 + s * math.pi)
            rel = (angle - aim) / spacing
            index = np.round(rel)
            # Distance (in pixels) from the nearest beam in the fan
            off = np.abs(rel - index) * spacing * dist
            lit = np.clip(1 - off / 0.8, 0, 1) * (np.abs(index) <= half)
            table = RAINBOW[(np.arange(-half, half + 1) * 36 + f.t * 60 + s * 128).astype(int) % 256] * 0.9
            out += table[np.clip(index + half, 0, 2 * half).astype(int)] * lit[:, :, None]
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class LEDWall(Effect):
    # A club video wall: coloured tiles that switch pattern every bar
    name = 'LED Wall'
    TILE = 8

    def __init__(self):
        self.rows, self.cols = H // self.TILE, W // self.TILE
        self.sparkle = np.zeros((self.rows, self.cols), np.float32)
        gap = ((XI % self.TILE) == self.TILE - 1) | ((YI % self.TILE) == self.TILE - 1)
        self.face = (~gap).astype(np.float32)[:, :, None]
        self.tx, self.ty = np.meshgrid(np.arange(self.cols), np.arange(self.rows))

    def render(self, f):
        b = beats(f.t)
        beat, bar = int(b), int(b) // 4
        pattern = bar % 5
        level = np.zeros((self.rows, self.cols), np.float32)
        hue = np.zeros((self.rows, self.cols), np.float32)
        if pattern == 0:      # checkerboard swapping on the beat
            level[:] = ((self.tx + self.ty + beat) % 2 == 0) * (0.5 + 0.5 * kick(f.t, 4))
            hue[:] = (beat * 40) % 256
        elif pattern == 1:    # chase sweeping across each beat
            head = (b % 1.0) * self.cols
            behind = (head - self.tx) % self.cols
            level[:] = np.clip(1 - behind / 6.0, 0, 1)
            hue[:] = (self.tx * 8 + beat * 50) % 256
        elif pattern == 2:    # random sparkle
            self.sparkle *= 1 - 4 * f.dt
            pick = np.random.uniform(0, 1, self.sparkle.shape) < 0.08
            self.sparkle[pick] = 1
            level[:] = self.sparkle
            hue[:] = (self.tx * 13 + self.ty * 29 + beat * 20) % 256
        elif pattern == 3:    # a lit row bouncing up and down
            row = int(abs(((b * 2) % 2) - 1) * (self.rows - 1) + 0.5)
            level[row] = 1
            level += 0.15
            hue[:] = (beat * 60 + self.ty * 30) % 256
        else:                 # rainbow wipe
            level[:] = 0.9
            hue[:] = (self.tx * 8 + self.ty * 16 - f.t * 200) % 256
        colors = RAINBOW[hue.astype(np.uint8)] * (level * 0.55)[:, :, None]
        out = np.repeat(np.repeat(colors, self.TILE, axis=0), self.TILE, axis=1) * self.face
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class Crowd(Effect):
    # A backlit crowd jumps on the beat with hands up (some holding phone lights)
    name = 'Crowd'
    WASHES = [(120, 0, 160), (0, 60, 200), (200, 0, 80), (0, 140, 140), (220, 90, 0)]

    def __init__(self):
        rng = np.random.RandomState(21)
        self.people = []
        x = 4.0
        while x < W - 2:
            self.people.append({'x': x, 'head': rng.randint(22, 26), 'late': rng.uniform(0, 0.12),
                                'hands': rng.choice(['both', 'left', 'right', 'both']),
                                'phone': rng.uniform() < 0.3, 'wave': rng.uniform(0, 6.3)})
            x += rng.uniform(8, 13)
        sky = gradient([(0, (0, 0, 0)), (1, (1, 1, 1))], H)
        self.fade = sky[:, :1][:, None, :]
        # Each person's silhouette pixels for three arm-sway poses, relative to standing height;
        # per frame they only need shifting up by the jump and drawing together
        for p in self.people:
            p['poses'] = [self.silhouette(p, sway) for sway in (-1.5, 0.0, 1.5)]

    @staticmethod
    def silhouette(p, sway):
        hx, hy = int(p['x']), p['head']
        pixels = set()
        for y in range(hy - 2, hy + 2):
            for x in range(hx - 1, hx + 2):
                pixels.add((y, x))
        for y in range(hy - 1, hy + 1):
            for x in range(hx - 2, hx + 3):
                pixels.add((y, x))
        for y in range(hy + 2, H + 3):
            for x in range(hx - 2, hx + 3):
                pixels.add((y, x))
        phone = None
        for side in (-1, 1):
            if p['hands'] == 'both' or (p['hands'] == 'left') == (side < 0):
                handX, handY = hx + side * (4 + sway * side), hy - 5
                for k in np.linspace(0, 1, 7):
                    pixels.add((int(round(hy + 3 + (handY - hy - 3) * k)),
                                int(round(hx + side * 2 + (handX - hx - side * 2) * k))))
                if p['phone'] and side > 0:
                    phone = (int(handY) - 1, int(round(handX)))
        ys, xs = np.array(sorted(pixels)).T
        return ys, xs, phone

    def render(self, f):
        b = beats(f.t)
        beat = int(b)
        wash = np.array(self.WASHES[(beat // 4) % len(self.WASHES)], np.float32)
        out = np.ones((H, W, 3), np.float32) * wash * self.fade * (0.35 + 0.35 * kick(f.t, 4))
        # Two stage beams sweeping down from above
        for i, sx in enumerate((70, 186)):
            aim = 0.5 * math.sin(f.t * 1.3 + i * 2)
            angle = np.arctan2(XX[0] - sx, 30.0)
            beam = np.clip(1 - np.abs(angle - aim) / 0.12, 0, 1)
            out += beam[None, :, None] * np.array((255, 255, 255), np.float32) * 0.25
        allY, allX, phones = [], [], []
        for p in self.people:
            hop = -int(round(2.5 * math.exp(-((b - p['late']) % 1.0) * 6)))
            pose = int(round(math.sin(f.t * 5 + p['wave']))) + 1
            ys, xs, phone = p['poses'][pose]
            allY.append(ys + hop)
            allX.append(xs)
            if phone:
                phones.append((phone[0] + hop, phone[1]))
        ys, xs = np.concatenate(allY), np.concatenate(allX)
        ok = (ys >= 0) & (ys < H) & (xs >= 0) & (xs < W)
        out[ys[ok], xs[ok]] = 0
        for y, x in phones:
            if 0 <= y < H and 0 <= x < W:
                out[y, x] = (255, 255, 230)
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class Sirens(Effect):
    # Red and blue police-style triple flashes alternating sides, with spinning beacon sweeps
    name = 'Sirens'
    RED, BLUE = np.array((255, 0, 20), np.float32), np.array((0, 60, 255), np.float32)

    def __init__(self):
        self.fromLeft = np.exp(-XX / 70.0)[:, :, None]
        self.fromRight = np.exp(-(W - 1 - XX) / 70.0)[:, :, None]

    def render(self, f):
        phase = beatPhase(f.t)
        out = np.zeros((H, W, 3), np.float32)
        # Three quick flashes per half beat: red side first, then blue
        for start, color, side in ((0.0, self.RED, self.fromLeft), (0.5, self.BLUE, self.fromRight)):
            p = phase - start
            if 0 <= p < 0.36 and (p % 0.12) < 0.06:
                out += color * side * 0.9
        # Rotating beacons: a bright band sweeping back and forth from each side
        for i, (color, origin) in enumerate(((self.RED, 0), (self.BLUE, W - 1))):
            x = origin + (W / 2.0) * (0.5 - 0.5 * math.cos(f.t * 4 + i * math.pi)) * (1 if origin == 0 else -1)
            band = np.clip(1 - np.abs(XX[0] - x) / 10.0, 0, 1)
            out += band[None, :, None] * color * 0.35
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class GlowSticks(Effect):
    # Neon glow sticks tumbling through the air, bouncing, thrown up again on the beat
    name = 'Glow Sticks'
    COLORS = [(0, 255, 120), (255, 0, 200), (0, 200, 255), (255, 230, 0), (255, 90, 0), (170, 0, 255)]
    COUNT = 12

    def __init__(self):
        n = self.COUNT
        self.x = np.random.uniform(10, W - 10, n)
        self.y = np.random.uniform(4, H - 4, n)
        self.vx = np.random.uniform(-40, 40, n)
        self.vy = np.random.uniform(-30, 10, n)
        self.angle = np.random.uniform(0, math.pi, n)
        self.spin = np.random.uniform(-6, 6, n)
        self.length = np.random.uniform(8, 13, n)
        self.color = np.array([self.COLORS[i % len(self.COLORS)] for i in range(n)], np.float32)
        self.lastBeat = -1

    def render(self, f):
        beat = beatNumber(f.t)
        if beat != self.lastBeat:
            self.lastBeat = beat
            thrown = np.random.uniform(0, 1, self.COUNT) < 0.5
            self.vy[thrown] -= np.random.uniform(25, 45, int(thrown.sum()))
            self.spin[thrown] += np.random.uniform(-5, 5, int(thrown.sum()))
        self.vy += 35 * f.dt
        self.x += self.vx * f.dt
        self.y += self.vy * f.dt
        self.angle += self.spin * f.dt
        floor = self.y > H - 2
        self.y[floor], self.vy[floor] = H - 2, -np.abs(self.vy[floor]) * 0.7
        walls = (self.x < 2) | (self.x > W - 3)
        self.vx[walls] *= -1
        self.x = np.clip(self.x, 2, W - 3)
        self.y = np.maximum(self.y, -10)
        k = np.linspace(-0.5, 0.5, 16)
        xs = (self.x[:, None] + np.cos(self.angle)[:, None] * self.length[:, None] * k).ravel()
        ys = (self.y[:, None] + np.sin(self.angle)[:, None] * self.length[:, None] * k).ravel()
        colors = np.repeat(self.color, len(k), axis=0)
        out = np.zeros((H, W, 3), np.float32)
        xi, yi = np.round(xs).astype(int), np.round(ys).astype(int)
        additive(out, np.concatenate([yi, yi - 1, yi + 1]), np.concatenate([xi, xi, xi]),
                 np.concatenate([colors * 0.85, colors * 0.25, colors * 0.25]))
        np.clip(out, 0, 255, out=out)
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class Pulse(Effect):
    # The lyrics punch bigger on every kick (with an RGB split at the peak) over a rotating burst
    name = 'Pulse'
    LEVELS = 7
    MAX_ZOOM = 0.22

    def __init__(self):
        dx, dy = (XX + 0.5 - 128) / 4.0, YY + 0.5 - 16
        self.angle = np.arctan2(dy, dx)
        self.radius = np.sqrt(dx ** 2 + dy ** 2)
        self.zoomFor, self.zoomed = None, {}

    def zoom(self, text, level):
        # The text's mask scaled up about the centre (built once per line and zoom level)
        if self.zoomFor is not text:
            self.zoomFor, self.zoomed = text, {}
        if level not in self.zoomed:
            s = 1 + self.MAX_ZOOM * level / (self.LEVELS - 1)
            w, h = int(round(W * s)), int(round(H * s))
            big = text.maskImage.resize((w, h), Image.NEAREST)
            left, top = (w - W) // 2, (h - H) // 2
            self.zoomed[level] = np.asarray(big.crop((left, top, left + W, top + H))) > 127
        return self.zoomed[level]

    def render(self, f):
        k = kick(f.t, 7)
        rays = (((self.angle / (2 * math.pi)) * 16 + f.t * 0.6) % 1.0) < 0.5
        out = RAINBOW[np.full((H, W), int(beatNumber(f.t) * 37 % 256), np.uint8)] * \
            (rays * np.clip(1 - self.radius / 40.0, 0, 1) * (0.15 + 0.35 * k))[:, :, None]
        if not hasattr(f.text, 'maskImage'):
            paint(out, f.text, (255, 255, 255))
            return out
        mask = self.zoom(f.text, int(round(k * (self.LEVELS - 1))))
        out[shift(mask, 1) | shift(mask, -1) | shift(mask, 0, 1) | shift(mask, 0, -1)] *= 0.2
        split = 2 if k > 0.6 else 0
        out[:, :, 0] = np.where(shift(mask, 0, -split), 255, out[:, :, 0])
        out[:, :, 1] = np.where(mask, 255, out[:, :, 1])
        out[:, :, 2] = np.where(shift(mask, 0, split), 255, out[:, :, 2])
        return out


EFFECTS = [Strobe, BassDrop, Shockwave, Rave, LaserFan, LEDWall, Crowd, Sirens, GlowSticks, Pulse]

# Party effects for the lyrics display, in the style of the favourites (Fire, Hyperspace,
# Equalizer, Storm, Fireworks, Disco): busy animated scenes behind readable white text.
import math
import random
import numpy as np
from effects import Effect, Text, H, W, YY, XX, YI, XI, RAINBOW, FIRE, gradient, ease, shift, paint
from moreeffects import Storm, beatPhase, beatNumber, additive

PARTY = [(255, 50, 90), (255, 200, 30), (60, 230, 110), (40, 170, 255), (190, 90, 255), (255, 120, 40),
         (255, 255, 255)]


def fadeIn(f, seconds=0.2):
    return min(1.0, f.age / seconds)


class Confetti(Effect):
    # Confetti flutters down, catching the light as it flips; cannons fire every 4 beats
    name = 'Confetti'
    AMBIENT = 110

    def __init__(self):
        self.p = np.zeros((0, 9), np.float32)   # x, y, vx, vy, phase, spin, r, g, b
        self.lastBeat = -1
        self.add(self.AMBIENT, np.random.uniform(0, W, self.AMBIENT), np.random.uniform(-H, H, self.AMBIENT),
                 0, np.random.uniform(6, 14, self.AMBIENT))

    def add(self, n, x, y, vx, vy):
        colors = np.array(PARTY, np.float32)[np.random.randint(0, len(PARTY), n)]
        new = np.column_stack([np.broadcast_to(x, n), np.broadcast_to(y, n), np.broadcast_to(vx, n),
                               np.broadcast_to(vy, n), np.random.uniform(0, 6.3, n),
                               np.random.uniform(3, 9, n), colors]).astype(np.float32)
        self.p = np.vstack([self.p, new])[-500:]

    def render(self, f):
        beat = beatNumber(f.t)
        if beat != self.lastBeat:
            self.lastBeat = beat
            if beat % 4 == 0:
                for side in (0, 1):
                    n = 45
                    x = np.full(n, 1.0 if side == 0 else W - 2.0)
                    vx = np.random.uniform(70, 170, n) * (1 if side == 0 else -1)
                    self.add(n, x, np.full(n, H - 1.0), vx, np.random.uniform(-75, -40, n))
        p = self.p
        p[:, 3] = np.minimum(p[:, 3] + 45 * f.dt, 13)        # gravity, then flutter at terminal speed
        p[:, 2] *= 1 - 1.8 * f.dt
        p[:, 0] += (p[:, 2] + np.sin(f.t * 2 + p[:, 4]) * 7) * f.dt
        p[:, 1] += p[:, 3] * f.dt
        p = p[p[:, 1] < H + 2]
        missing = self.AMBIENT - int((p[:, 3] > 0).sum())
        self.p = p
        if missing > 0 and random.random() < 0.5:
            self.add(min(missing, 3), np.random.uniform(0, W, min(missing, 3)), -2.0, 0,
                     np.random.uniform(6, 14, min(missing, 3)))
        p = self.p
        flip = np.cos(f.t * p[:, 5] + p[:, 4])
        bright = (0.3 + 0.7 * np.abs(flip))[:, None]
        x, y = p[:, 0].astype(int), p[:, 1].astype(int)
        out = np.zeros((H, W, 3), np.float32)
        colors = p[:, 6:9] * bright
        ok = (x >= 0) & (x < W - 1) & (y >= 0) & (y < H - 1)
        out[y[ok], x[ok]] = colors[ok]
        wide = ok & (np.abs(flip) > 0.5)
        out[y[wide], x[wide] + 1] = colors[wide]
        tall = ok & ~wide
        out[y[tall] + 1, x[tall]] = colors[tall]
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class ClubLights(Effect):
    # Stage beams sweep up from the floor through the haze, changing colour on the beat, with
    # strobe hits every few bars
    name = 'Club Lights'
    FIXTURES = [32, 96, 160, 224]

    def __init__(self):
        # Beams are smooth, so they're computed at half horizontal resolution and doubled up
        fy = H + 3.0
        x2, y2 = XX[:, ::2] + 0.5, YY[:, ::2]
        self.angle = np.stack([np.arctan2(x2 - fx, fy - y2) for fx in self.FIXTURES]).reshape(len(self.FIXTURES), -1)
        self.falloff = np.stack([1.0 / (1.0 + np.sqrt((x2 - fx) ** 2 + (fy - y2) ** 2) / 45.0)
                                 for fx in self.FIXTURES]).reshape(len(self.FIXTURES), -1)
        self.speed = np.random.uniform(0.6, 1.2, len(self.FIXTURES))
        self.phase = np.random.uniform(0, 6.3, len(self.FIXTURES))
        self.haze = np.random.uniform(0.85, 1.0, (H, W)).astype(np.float32)

    def render(self, f):
        beat = beatNumber(f.t)
        aim = (0.8 * np.sin(f.t * self.speed + self.phase)).astype(np.float32)[:, None]
        # Smooth bump of width ~0.2 rad (cheaper than exp on the Pi, looks the same)
        q = np.clip(1 - ((self.angle - aim) * 5.0) ** 2, 0, 1)
        beams = q * q * self.falloff
        colors = np.array([PARTY[(beat // 2 + i) % (len(PARTY) - 1)] for i in range(len(self.FIXTURES))],
                          np.float32) * 0.9
        # Sum of all beams in every colour channel at once: (3 x fixtures) @ (fixtures x pixels)
        half = (colors.T @ beams).reshape(3, H, W // 2).transpose(1, 2, 0)
        out = np.repeat(half, 2, axis=1)
        out *= self.haze[:, :, None]
        # Strobe for the last two beats of every 16
        if beat % 16 >= 14 and (f.t * 120 / 60.0 * 4) % 1.0 < 0.3:
            out += 150
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class Meteors(Effect):
    # A meteor shower: glowing streaks with long fading tails over twinkling stars;
    # a big fireball every 8 beats
    name = 'Meteors'

    def __init__(self):
        rng = np.random.RandomState(9)
        self.stars = rng.uniform(0, 1, (H, W)) > 0.985
        self.twinkle = rng.uniform(0, 6.3, (H, W))
        self.meteors = []
        self.nextMeteor = 0.2
        self.lastBeat = -1

    def spawn(self, big=False):
        speed = random.uniform(140, 220)
        angle = random.uniform(0.12, 0.28)
        self.meteors.append({'x': random.uniform(60, W + 80), 'y': random.uniform(-6, 4),
                             'vx': -speed * math.cos(angle), 'vy': speed * math.sin(angle),
                             'length': random.randint(50, 80) if big else random.randint(18, 40),
                             'big': big, 'color': random.choice([(255, 200, 120), (170, 210, 255), (200, 255, 210)])})

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        out += ((0.35 + 0.25 * np.sin(f.t * 2.5 + self.twinkle)) * self.stars)[:, :, None] * 255
        if f.t >= self.nextMeteor:
            self.spawn()
            self.nextMeteor = f.t + random.uniform(0.15, 0.7)
        beat = beatNumber(f.t)
        if beat != self.lastBeat:
            self.lastBeat = beat
            if beat % 8 == 0:
                self.spawn(big=True)
        alive = []
        for m in self.meteors:
            m['x'] += m['vx'] * f.dt
            m['y'] += m['vy'] * f.dt
            if m['x'] < -m['length'] or m['y'] > H + 4:
                continue
            alive.append(m)
            speed = math.hypot(m['vx'], m['vy'])
            k = np.arange(m['length'], dtype=np.float32)
            xs = (m['x'] - m['vx'] / speed * k).astype(int)
            ys = (m['y'] - m['vy'] / speed * k).astype(int)
            fade = ((1 - k / m['length']) ** 2)[:, None]
            color = np.array(m['color'], np.float32)
            additive(out, ys, xs, color * fade)
            if m['big']:
                additive(out, ys + 1, xs, np.array((255, 110, 30), np.float32) * fade * 0.6)
                additive(out, ys - 1, xs, np.array((255, 110, 30), np.float32) * fade * 0.4)
            additive(out, np.array([int(m['y'])]), np.array([int(m['x'])]), np.array([[255, 255, 255]], np.float32))
        self.meteors = alive
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class Embers(Effect):
    # Hundreds of glowing embers swirl upward on a turbulent draft, cooling as they rise
    name = 'Embers'
    COUNT = 300

    def __init__(self):
        n = self.COUNT
        self.x = np.random.uniform(0, W, n).astype(np.float32)
        self.y = np.random.uniform(0, H, n).astype(np.float32)
        self.vx = np.zeros(n, np.float32)
        self.vy = np.random.uniform(-25, -8, n).astype(np.float32)
        self.heat = np.random.uniform(0.2, 1, n).astype(np.float32)
        self.cool = np.random.uniform(0.25, 0.55, n).astype(np.float32)

    def render(self, f):
        flow = np.sin(self.x / 23.0 + f.t * 0.9) * np.cos(self.y / 6.0 - f.t * 1.4) * 30
        self.vx += (flow - self.vx) * 2.5 * f.dt
        self.vy = np.maximum(self.vy - 6 * f.dt, -35)
        self.x += self.vx * f.dt
        self.y += self.vy * f.dt
        self.heat -= self.cool * f.dt
        dead = (self.heat <= 0) | (self.y < -1)
        n = int(dead.sum())
        self.x[dead] = np.random.uniform(0, W, n)
        self.y[dead] = H - 1
        self.vy[dead] = np.random.uniform(-25, -8, n)
        self.vx[dead] = 0
        self.heat[dead] = np.random.uniform(0.7, 1, n)
        out = np.zeros((H, W, 3), np.float32)
        # A low glow along the bottom, flickering
        glow = (0.25 + 0.15 * np.sin(XX[0] / 13.0 + f.t * 3) * np.sin(XX[0] / 7.0 - f.t * 2.3))
        for k, row in enumerate(range(H - 4, H)):
            out[row] = FIRE[np.clip((glow * (k + 1) / 4.0) * 255, 0, 255).astype(np.uint8)] * 0.6
        flicker = np.random.uniform(0.7, 1.0, self.COUNT)
        color = FIRE[np.clip(self.heat * 255 * 0.9 + 25, 0, 255).astype(np.uint8)] * flicker[:, None]
        additive(out, self.y.astype(int), self.x.astype(int), color)
        paint(out, f.text, (255, 245, 220), alpha=fadeIn(f))
        return out


class Inferno(Effect):
    # A full wall of flames roaring up from the bottom, surging on the beat, throwing sparks
    name = 'Inferno'

    POOL = 4 * W

    def __init__(self):
        self.heat = np.zeros((H, W), np.float32)
        self.sparks = []
        # Generating ~30k random numbers per frame is slow on the Pi, so random slices of a
        # pre-generated pool are used instead
        self.driftPool = np.random.randint(-1, 2, (H - 1, self.POOL + W))
        self.decayPool = np.random.uniform(0, 0.06, (H - 1, self.POOL + W)).astype(np.float32)
        self.basePool = np.random.uniform(0.75, 1.0, self.POOL + W).astype(np.float32)

    def render(self, f):
        kick = math.exp(-beatPhase(f.t) * 5)
        for _ in range(2):
            o = random.randrange(self.POOL)
            self.heat[H - 1] = self.basePool[o:o + W] * (0.85 + 0.15 * kick)
            o = random.randrange(self.POOL)
            drift = self.driftPool[:, o:o + W]
            below = self.heat[1:]
            gathered = below[YI[:-1], np.clip(XI[:-1] + drift, 0, W - 1)]
            o = random.randrange(self.POOL)
            decay = self.decayPool[:, o:o + W] * (1.15 - 0.3 * kick)
            self.heat[:-1] = np.clip(gathered - decay, 0, 1)
        out = FIRE[(self.heat * 255).astype(np.uint8)] * 0.8
        if random.random() < 0.35:
            self.sparks.append([random.uniform(0, W), H - 4.0, random.uniform(-15, 15), random.uniform(-45, -25), 1.0])
        alive = []
        for s in self.sparks:
            s[0] += s[2] * f.dt
            s[1] += s[3] * f.dt
            s[4] -= f.dt * 0.8
            if s[4] > 0 and s[1] >= 0:
                alive.append(s)
                x, y = int(s[0]), int(s[1])
                if 0 <= x < W and 0 <= y < H:
                    out[y, x] = np.array((255, 230, 120)) * s[4]
        self.sparks = alive[-40:]
        paint(out, f.text, (255, 250, 220), alpha=fadeIn(f))
        return out


class WarpTunnel(Effect):
    # Neon rings rush out of a spinning tunnel, cycling through colours
    name = 'Warp Tunnel'

    def __init__(self):
        dx, dy = (XX + 0.5 - 128) / 6.0, YY + 0.5 - 16
        r = np.sqrt(dx ** 2 + dy ** 2) + 0.3
        self.depth = 10.0 / r
        self.fade = np.clip(r / 4.0, 0, 1)
        self.spokeAngle = (np.arctan2(dy, dx) / (2 * math.pi)) * 12

    def render(self, f):
        travel = self.depth + f.t * 2.4
        ring = travel % 1.0
        rings = np.exp(-((ring - 0.5) / 0.12) ** 2)
        hue = ((np.floor(travel) * 41 + f.t * 25) % 256).astype(np.uint8)
        out = RAINBOW[hue] * (rings * self.fade * 0.75)[:, :, None]
        spokes = ((self.spokeAngle + f.t * 0.6) % 1.0) < 0.07
        out[spokes] += np.array((90, 40, 170), np.float32) * self.fade[spokes][:, None]
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class CityStorm(Storm):
    # Storm over a city skyline: flickering windows, rooftops lit up by the lightning
    name = 'City Storm'

    def __init__(self):
        Storm.__init__(self)
        rng = np.random.RandomState(17)
        heights = np.zeros(W, int)
        x = 0
        while x < W:
            width = rng.randint(6, 19)
            heights[x:x + width] = rng.randint(5, 17)
            x += width + rng.randint(0, 3)
        self.building = YY >= (H - heights)[None, :]
        self.roof = self.building & ~shift(self.building, 1)
        windowGrid = ((XI % 3) == 1) & ((YI % 3) == 0) & self.building & ~self.roof
        self.windows = windowGrid & (rng.uniform(0, 1, (H, W)) < 0.35)
        self.windowGrid = windowGrid
        # Hazy city glow: the sky brightens toward the skyline (built once; zero behind buildings)
        sky = gradient([(0, (6, 8, 22)), (1, (40, 30, 70))], H)[:, None, :] * np.ones((1, W, 1), np.float32)
        self.sky = sky * ~self.building[:, :, None]
        self.open = (~self.building).astype(np.float32)[:, :, None]
        self.roofLight = self.roof.astype(np.float32)[:, :, None] * np.array((150, 150, 200), np.float32)
        self.buildingLight = self.building.astype(np.float32)[:, :, None] * np.array((25, 25, 40), np.float32)
        self.windowSpots = np.argwhere(windowGrid)

    def scenery(self, out, flash):
        out *= self.open
        out += self.sky * (1 - 0.5 * flash)
        if flash:
            out += self.buildingLight * flash + self.roofLight * flash
        # A few windows switch on or off each frame
        for y, x in self.windowSpots[np.random.randint(0, len(self.windowSpots), 2)]:
            self.windows[y, x] = not self.windows[y, x]
        out[self.windows] = (200, 150, 60)


class Electric(Effect):
    # Crackling arcs jump between the letters; a big discharge crosses the panel on each beat
    name = 'Electric'

    ARCS = 5

    def __init__(self):
        self.arcs = []
        self.nextArc = 0
        self.lastBeat = -1

    @staticmethod
    def arc(x0, y0, x1, y1):
        n = max(2, int(abs(x1 - x0)))
        xs = np.linspace(x0, x1, n)
        wander = np.cumsum(np.random.randint(-1, 2, n))
        wander = wander - np.linspace(0, wander[-1], n)          # end where it should
        ys = np.clip(np.round(np.linspace(y0, y1, n) + wander), 0, H - 1).astype(int)
        return ys, np.clip(xs.astype(int), 0, W - 1)

    def render(self, f):
        out = np.zeros((H, W, 3), np.float32)
        out[:] = (3, 3, 12)
        # Replace one arc per frame (rather than all at once) so the work is spread evenly;
        # each arc lives about ARCS frames
        if getattr(self, 'arcsFor', None) is not f.text:
            self.arcsFor, self.points = f.text, np.nonzero(f.text.mask)
            self.arcs = []
        ys, xs = self.points
        if len(xs):
            a = random.randrange(len(xs))
            near = np.nonzero(np.abs(xs - xs[a]) < 50)[0]
            b = near[random.randrange(len(near))]
            arc = self.arc(xs[a], ys[a], xs[b], ys[b])
            if len(self.arcs) < self.ARCS:
                self.arcs.append(arc)
            else:
                self.arcs[self.nextArc % self.ARCS] = arc
                self.nextArc += 1
        beat = beatNumber(f.t)
        surge = beatPhase(f.t) < 0.1
        if surge and beat != self.lastBeat:
            self.lastBeat = beat
            self.bigArc = self.arc(0, random.randint(4, H - 5), W - 1, random.randint(4, H - 5))
        if self.arcs:
            ay = np.concatenate([a[0] for a in self.arcs])
            ax = np.concatenate([a[1] for a in self.arcs])
            core = np.broadcast_to(np.array((170, 190, 255), np.float32), (len(ax), 3))
            halo = np.broadcast_to(np.array((40, 50, 160), np.float32), (len(ax), 3))
            additive(out, np.concatenate([ay, ay - 1, ay + 1]), np.concatenate([ax, ax, ax]),
                     np.concatenate([core, halo, halo]))
        if surge and getattr(self, 'bigArc', None) is not None:
            ay, ax = self.bigArc
            n = len(ax)
            colors = np.concatenate([np.broadcast_to(np.array((220, 230, 255), np.float32), (n, 3)),
                                     np.broadcast_to(np.array((80, 90, 220), np.float32), (2 * n, 3))])
            additive(out, np.concatenate([ay, ay - 1, ay + 1]), np.concatenate([ax, ax, ax]), colors)
        brightness = random.uniform(0.85, 1.0) if not surge else 1.0
        paint(out, f.text, np.array((190, 215, 255)) * brightness, alpha=fadeIn(f))
        return out


class Particles(Effect):
    # Each old line shatters into falling sparks while the new one flies together from a burst
    name = 'Particles'

    def __init__(self):
        self.current = None
        self.lastAge = 0.0
        self.debris = np.zeros((0, 8), np.float32)   # x, y, vx, vy, life, r, g, b

    def render(self, f):
        # A new screen starts when its age resets (scrolling lines are rebuilt every frame, so
        # comparing Text objects wouldn't work)
        newScreen = self.current is None or f.age < self.lastAge
        self.lastAge = f.age
        if newScreen:
            if self.current is not None:
                ys, xs = np.nonzero(self.current.mask)
                if len(xs):
                    cx, cy = xs.mean(), ys.mean()
                    n = len(xs)
                    vx = (xs - cx) * 0.6 + np.random.uniform(-30, 30, n)
                    vy = (ys - cy) * 2.0 + np.random.uniform(-45, -5, n)
                    colors = RAINBOW[((xs * 1.5) % 256).astype(np.uint8)]
                    debris = np.column_stack([xs, ys, vx, vy, np.random.uniform(0.6, 1.2, n), colors])
                    self.debris = np.vstack([self.debris, debris.astype(np.float32)])[-2500:]
            self.current = f.text
            self.targetY, self.targetX = np.nonzero(f.text.mask)
            n = len(self.targetX)
            burstX, burstY = random.uniform(60, W - 60), random.uniform(8, H - 8)
            angle = np.random.uniform(0, 2 * math.pi, n)
            self.startX = burstX + np.cos(angle) * np.random.uniform(0, 30, n)
            self.startY = burstY + np.sin(angle) * np.random.uniform(0, 10, n)
            self.delay = np.random.uniform(0, 0.25, n)
            self.colors = RAINBOW[((self.targetX * 1.5) % 256).astype(np.uint8)]
            self.arrivedAt = None
        out = np.zeros((H, W, 3), np.float32)
        d = self.debris
        if len(d):
            d[:, 0] += d[:, 2] * f.dt
            d[:, 1] += d[:, 3] * f.dt
            d[:, 3] += 70 * f.dt
            d[:, 4] -= f.dt
            d = d[d[:, 4] > 0]
            additive(out, d[:, 1].astype(int), d[:, 0].astype(int), d[:, 5:8] * np.clip(d[:, 4], 0, 1)[:, None])
            self.debris = d
        p = np.clip((f.age - self.delay) / 0.45, 0, 1)
        if p.size and p.min() < 1:
            e = 1 - (1 - p) ** 3
            x = (self.startX + (self.targetX - self.startX) * e).astype(int)
            y = (self.startY + (self.targetY - self.startY) * e).astype(int)
            color = self.colors * (1 - p)[:, None] + 255 * p[:, None]
            additive(out, y, x, color * f.text.shade[self.targetY, self.targetX][:, None])
        else:
            paint(out, f.text, (255, 255, 255))
            sparkle = f.text.mask & (np.random.uniform(0, 1, (H, W)) < 0.01)
            out[sparkle] = (255, 255, 160)
        return out


class MirrorEQ(Effect):
    # Rainbow spectrum bars grow up and down from the middle, kicking on the beat
    name = 'Mirror EQ'
    BARS, BAR_WIDTH = 64, 4

    def __init__(self):
        self.level = np.zeros(self.BARS, np.float32)
        self.target = np.zeros(self.BARS, np.float32)
        centre = (self.BARS - 1) / 2.0
        self.bass = (1 - np.abs(np.arange(self.BARS) - centre) / centre) ** 2

    def render(self, f):
        kick = math.exp(-beatPhase(f.t) * 6)
        self.target = 0.55 * self.target + 0.45 * np.random.uniform(0.05, 1.0, self.BARS) ** 1.3
        goal = np.clip(self.target * 0.8 + kick * self.bass * 0.7, 0, 1)
        self.level += (goal - self.level) * 0.5
        bar = (XX // self.BAR_WIDTH).astype(int)
        inBar = (XX % self.BAR_WIDTH) < self.BAR_WIDTH - 1
        reach = self.level[bar] * 16
        fromMiddle = np.abs(YY + 0.5 - 16)
        lit = inBar & (fromMiddle < reach)
        hue = ((bar * 4 + f.t * 40) % 256).astype(np.uint8)
        tip = np.clip(fromMiddle / np.maximum(reach, 1e-3), 0, 1)
        out = RAINBOW[hue] * ((0.25 + 0.5 * tip) * lit)[:, :, None]
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


class Bubbles(Effect):
    # Soap bubbles wobble upward and pop into sparkles
    name = 'Bubbles'
    MAX = 30
    TINTS = [(150, 220, 255), (255, 170, 230), (180, 255, 200), (255, 230, 150), (210, 180, 255)]

    def __init__(self):
        self.bubbles = []
        self.sparks = []
        self.nextBubble = 0.0
        self.background = gradient([(0, (0, 10, 25)), (1, (0, 30, 45))], H)[:, None, :] * np.ones((1, W, 1))

    def render(self, f):
        if f.t >= self.nextBubble and len(self.bubbles) < self.MAX:
            r = random.uniform(1.5, 4.5)
            self.bubbles.append([random.uniform(5, W - 5), H + r, r, random.uniform(-14, -6),
                                 random.uniform(0, 6.3), random.choice(self.TINTS)])
            self.nextBubble = f.t + random.uniform(0.05, 0.25)
        out = self.background.astype(np.float32)
        alive = []
        for b in self.bubbles:
            b[1] += b[3] * f.dt
            x = b[0] + math.sin(f.t * 3 + b[4]) * 2
            r = b[2]
            if b[1] < r + 1 or random.random() < 0.002:
                for _ in range(6):
                    a = random.uniform(0, 2 * math.pi)
                    self.sparks.append([x, b[1], math.cos(a) * 25, math.sin(a) * 12, 0.35])
                continue
            alive.append(b)
            y0, y1 = max(0, int(b[1] - r - 1)), min(H, int(b[1] + r + 2))
            x0, x1 = max(0, int(x - r - 1)), min(W, int(x + r + 2))
            if y0 >= y1 or x0 >= x1:
                continue
            d = np.sqrt((XX[y0:y1, x0:x1] - x) ** 2 + (YY[y0:y1, x0:x1] - b[1]) ** 2)
            ring = np.abs(d - r) < 0.6
            region = out[y0:y1, x0:x1]
            region[ring] = np.maximum(region[ring], np.array(b[5], np.float32) * 0.8)
            hx, hy = int(x - r * 0.45), int(b[1] - r * 0.45)
            if 0 <= hx < W and 0 <= hy < H and r > 2:
                out[hy, hx] = 255
        self.bubbles = alive
        live = []
        for s in self.sparks:
            s[0] += s[2] * f.dt
            s[1] += s[3] * f.dt
            s[4] -= f.dt
            if s[4] > 0:
                live.append(s)
                x, y = int(s[0]), int(s[1])
                if 0 <= x < W and 0 <= y < H:
                    out[y, x] = 255 * min(1.0, s[4] * 3)
        self.sparks = live
        paint(out, f.text, (255, 255, 255), alpha=fadeIn(f))
        return out


EFFECTS = [Confetti, ClubLights, Meteors, Embers, Inferno, WarpTunnel, CityStorm, Electric, Particles,
           MirrorEQ, Bubbles]

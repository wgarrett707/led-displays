# The LED strips (WLED, along the wall/ceiling seam on both sides of the matrix), driven in time
# with the song's beats from beatsync. Frames go to WLED over DDP; when there's nothing to follow
# (no analysis for the song, paused, or this program stops) WLED goes back to its own effects
# by itself after a couple of seconds.
import colorsys
import math
import socket
import struct
import threading
import time
import numpy as np

WLED_IP = '192.168.10.11'   # replaced by the address WLED's audio packets come from
DDP_PORT = 4048
FPS = 42
# Frames are drawn this far ahead to make up for the network and WLED's own frame
LEAD = 0.03
# Both strips are fed from their far ends: (first LED, LEDs on the strip, LEDs on the main wall). The
# last LEDs of each (the matrix end) curve round onto the other wall and are left dark, so the lights
# start from the corner: strip 1 is lit up to its LED 207, strip 2 up to its LED 205. Both strips have
# the same LED spacing, so they're drawn LED for LED and mirror each other.
STRIPS = [(0, 224, 207), (224, 224, 205)]
LONGEST = max(lit for s, n, lit in STRIPS)
# Pulses cross the longest strip in this many beats
CROSS_BEATS = 1.25
# After a drop: a white hit, then a strobe on the beat for this many bars (0 = no strobe).
# Never faster than MAX_FLASHES a second (every other beat for fast songs).
DROP_STROBE_BARS = 2
MAX_FLASHES = 3.0
FLASH_ON = 0.05
# Hue ranges (degrees, start..end, may run past 360) per section label; the chorus always gets HOT, so it looks the same each time
PALETTES = [(205, 265), (165, 215), (265, 320), (25, 50), (95, 160), (330, 375), (185, 240), (45, 110)]
HOT = (310, 400)
GAMMA = 2.2
# Calmer look: a steady glow in the section's colours (AMBIENT, a little more in loud parts) under
# everything, with the effects on top scaled by OVERLAY and run through a soft limiter that tops out at
# CEILING, so a pulse is a few times brighter than the glow rather than full white on black. Drops,
# the strobe pattern and 'off' are left as they are; build-ups climb back to full contrast by the drop.
AMBIENT = 0.34
AMBIENT_ENERGY = 0.10
OVERLAY = 0.9
CEILING = 1.0
# Sections quieter than this (0-1, relative to the rest of the song) get a calm pattern unless one was
# chosen in the editor
CALM_BELOW = 0.35
CALM_PATTERN = 'drift'
# The 'balls' effect: balls this many LEDs long (so about LONGEST / BALL_WIDTH of them fill the strip),
# starting with BALL_START of them; simulated in steps of BALL_STEP seconds
BALL_WIDTH = 6
BALL_START = 3
BALL_STEP = 1 / 200.0
# Chart notes held longer than this (s) are looked for no further back
NOTE_HOLD_MAX = 8.0


def rgb(hue, sat, val):
    return np.array(colorsys.hsv_to_rgb((hue % 360) / 360.0, sat, val), np.float32)


def hsvArray(hue, sat, val):
    # rgb() for an array of hues (degrees)
    h6 = (np.asarray(hue, np.float32) % 360) / 60.0
    c = val * sat
    x = c * (1 - np.abs(h6 % 2 - 1))
    z = np.zeros_like(h6)
    c = z + c
    i = np.floor(h6).astype(int) % 6
    r = np.choose(i, [c, x, z, z, x, c])
    g = np.choose(i, [x, c, c, x, z, z])
    b = np.choose(i, [z, z, x, c, c, x])
    return np.stack([r, g, b], 1) + (val - c)[:, None]


def buildFirings(d, total):
    # When a drop's build-up fires its pulses, as beats before the drop (ascending). 'total' is the
    # build-up's length in beats. The drop's 'stages' are [beats before the drop, pulses per beat]: each
    # rate holds from that point until the next stage; without stages it's 1 a beat, then 2 from halfway,
    # then 4 for the last fifth. Pulses fall on whole fractions of a beat counted back from the drop, so
    # they lock to the beat. With 'smooth', each stage speeds up gradually into the next instead of
    # jumping. The editor (editor.html, firings) works this out the same way to show the pulses.
    stages = d.get('stages') or [[total, 1], [0.5 * total, 2], [0.2 * total, 4]]
    st = sorted([(min(float(b), total), float(r)) for b, r in stages if min(float(b), total) > 0 and float(r) > 0], reverse=True)
    out = []
    for i, (b, r) in enumerate(st):
        end = st[i + 1][0] if i + 1 < len(st) else 0.0
        if d.get('smooth') and i + 1 < len(st):
            r2, seg = st[i + 1][1], b - end
            n = max(2, int(math.floor(seg * 128)) + 1)
            us = b + (end - b) * np.arange(n) / (n - 1)
            mids = (us[:-1] + us[1:]) / 2
            phase = np.concatenate([[0.0], np.cumsum(r * (r2 / r) ** ((b - mids) / seg) * (us[:-1] - us[1:]))])
            k = max(1, int(round(phase[-1])))
            phase *= k / phase[-1]
            out += list(us[np.minimum(np.searchsorted(phase, np.arange(k) - 1e-9), n - 1)])
        else:
            m = int(math.floor(b * r + 1e-9))
            while m >= 1 and m / r > end + 1e-9:
                out.append(m / r)
                m -= 1
    return np.array(sorted(out))


class Balls:
    # One 'balls' effect: balls bounce along the strip, off its ends and off each other (all the same
    # weight, so two that collide swap speeds). A new one drops into the biggest gap on the beat, the
    # number growing steadily until they fill the strip by the effect's end. Simulated in small fixed
    # steps from the effect's start, so it's always the same; jumping back starts it again.
    def __init__(self, e, beats, period):
        self.e = e
        start, end = e['time'], e['end']
        n = max(BALL_START + 1, int(LONGEST // BALL_WIDTH))
        # New balls on beats spread evenly over the first 85% (evenly in time if the beats run out)
        k = n - BALL_START
        on = beats[(beats > start) & (beats < start + 0.85 * (end - start))]
        if len(on) >= k:
            self.spawn = list(on[np.round(np.linspace(0, len(on) - 1, k)).astype(int)])
        else:
            self.spawn = list(start + np.linspace(0, 0.85 * (end - start), k + 1)[1:])
        rng = np.random.RandomState(int(start * 1000) & 0x7fffffff)
        # About a quarter of the strip a beat, either way
        self.speeds = rng.uniform(0.6, 1.3, n) * (LONGEST / (4 * period)) * rng.choice([-1.0, 1.0], n)
        self.shade = (np.arange(n) * 0.618) % 1.0        # each ball's place in the section's colour range
        self.reset()

    def reset(self):
        self.t = self.e['time']
        self.x = (np.arange(BALL_START) + 0.5) * LONGEST / BALL_START
        self.v = self.speeds[:BALL_START].copy()
        self.ids = np.arange(BALL_START)
        self.hit = np.full(BALL_START, -9.0)
        self.next = 0

    def advance(self, t):
        if t < self.t - 0.25:
            self.reset()
        while self.t + BALL_STEP <= t:
            # Catching up after a jump: coarser steps, so the strips don't stall
            step = BALL_STEP * 4 if t - self.t > 1.0 else BALL_STEP
            self.t += step
            while self.next < len(self.spawn) and self.spawn[self.next] <= self.t:
                self.add()
            self.step(step)

    def add(self):
        # Into the middle of the biggest gap
        w = BALL_WIDTH
        edges = np.concatenate([[0.0], np.repeat(self.x, 2) + np.tile([-w / 2.0, w / 2.0], len(self.x)), [float(LONGEST)]])
        gaps = edges[1::2] - edges[0::2]
        g = int(np.argmax(gaps))
        x = (edges[2 * g] + edges[2 * g + 1]) / 2
        i = BALL_START + self.next
        self.x = np.insert(self.x, g, x)
        self.v = np.insert(self.v, g, self.speeds[i])
        self.ids = np.insert(self.ids, g, i)
        self.hit = np.insert(self.hit, g, self.t)
        self.next += 1

    def step(self, dt):
        w, x, v = BALL_WIDTH, self.x, self.v
        x += v * dt
        lo, hi = x < w / 2.0, x > LONGEST - w / 2.0
        x[lo], v[lo] = w - x[lo], np.abs(v[lo])
        x[hi], v[hi] = 2 * (LONGEST - w / 2.0) - x[hi], -np.abs(v[hi])
        for i in range(len(x) - 1):
            if x[i + 1] - x[i] < w:
                if v[i] > v[i + 1]:
                    v[i], v[i + 1] = v[i + 1], v[i]
                    self.hit[i] = self.hit[i + 1] = self.t
                mid = (x[i] + x[i + 1]) / 2
                x[i], x[i + 1] = mid - w / 2.0, mid + w / 2.0
        np.clip(x, w / 2.0, LONGEST - w / 2.0, out=x)


class Strips(threading.Thread):
    def __init__(self, clock):
        threading.Thread.__init__(self, daemon=True)
        self.clock = clock
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0
        self.d = np.arange(LONGEST, dtype=np.float32)   # distance from the matrix, in LEDs
        # Where each drum hit's sparkles land (the same LEDs every time the hit plays)
        self.spots = np.random.RandomState(1).randint(0, LONGEST, (4096, 40))
        self.raw = np.zeros((sum(n for s, n, lit in STRIPS), 3), np.uint8)   # the curved LEDs stay 0

    def run(self):
        frame = 1.0 / FPS
        next_ = time.monotonic()
        while True:
            try:
                st = self.clock.state(time.monotonic(), LEAD)
                if st is None:
                    # Nothing to follow: stop sending and WLED takes its own effects back
                    time.sleep(0.1)
                    next_ = time.monotonic()
                    continue
                self.send(self.render(st))
            except Exception as e:
                print('Strips: %r' % e, flush=True)
                time.sleep(1)
            next_ += frame
            delay = next_ - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_ = time.monotonic()

    # ------------------------------------------------------------ drawing (by distance from the matrix)

    def palette(self, st):
        # A section's own colours (set in the editor), else by label; the chorus is always HOT
        if st.section.get('hues'):
            return tuple(st.section['hues'])
        if st.section.get('chorus'):
            return HOT
        return PALETTES[(ord(st.section['label']) - 65) % len(PALETTES)]

    def pulse(self, out, pos, color, width=4.0, tail=30.0, inward=False):
        # A bright head at 'pos' with a fading tail behind it (towards the matrix, or away from it
        # for a pulse travelling inwards)
        x = pos - self.d if inward else self.d - pos
        shape = np.where(x > 0, np.exp(-(x / width) ** 2), np.exp(x / tail))
        out += shape[:, None] * color[None, :]

    def note(self, k):
        # Melody note (0-11, or -1) on half beat k of the bar-aligned count
        a = self.clock.analysis
        if a is None:
            return -1
        half = 2 * a.downbeat + k
        return int(a.notes[half]) if 0 <= half < len(a.notes) else -1

    def render(self, st):
        out = np.zeros((LONGEST, 3), np.float32)
        hues = self.palette(st)
        level = 0.35 + 0.65 * st.energy
        a = self.clock.analysis
        # The section's pattern from the editor; otherwise a calm one for quiet sections, else the song's
        # Clone Hero chart notes when it has a chart, else beat pulses
        pattern = st.section.get('pattern')
        if not pattern:
            if st.section.get('energy', 1.0) < CALM_BELOW and st.build is None:
                pattern = CALM_PATTERN
            else:
                pattern = 'notes' if a is not None and a.hasNotes else 'pulses'
        if st.balls is not None:
            # A 'balls' effect marked in the editor takes over from the pattern while it runs
            self.drawBalls(out, st, hues, level)
            pattern = 'balls'
        elif st.build is not None and pattern != 'off':
            self.buildUp(out, st, hues, level)
        else:
            getattr(self, 'draw_' + pattern, self.draw_pulses)(out, st, hues, level)

        if st.sinceLift is not None and st.sinceLift < 0.6:
            # A lift (a big entrance that isn't quite a drop): one wide wave of colour
            self.pulse(out, st.sinceLift / (st.period * CROSS_BEATS) * LONGEST * 1.2, rgb(hues[1], 0.6, 1.0), width=25, tail=60)

        if pattern not in ('off', 'strobe'):
            out = self.soften(out, st, hues)

        if st.sinceDrop is not None:
            beatsSince = st.sinceDrop / st.period
            out += math.exp(-st.sinceDrop / 0.3) * 1.2   # white hit
            if beatsSince < 4 * DROP_STROBE_BARS:
                every = 1 if 1.0 / st.period <= MAX_FLASHES else 2
                if int(math.floor(beatsSince)) % every == 0 and (beatsSince % 1.0) * st.period < FLASH_ON:
                    out = np.maximum(out, 0.9)
        if st.fade < 1.0:
            # A fade-out marked in the editor: everything fades to black (and stays dark)
            out = out * st.fade
        return out

    def drawBalls(self, out, st, hues, level):
        # The 'balls' effect: see Balls. Each ball has its own colour from the section's range and flashes
        # whiter when it hits another; for the last few percent the strip fills in completely.
        a, e = self.clock.analysis, st.balls
        key = (e['time'], e['end'], len(a.beats))
        sims = getattr(self, '_balls', {})
        if key not in sims:
            sims = {key: Balls(e, a.beats, st.period)}
            self._balls = sims
        sim = sims[key]
        sim.advance(st.time)
        p = (st.time - e['time']) / (e['end'] - e['time'])
        out += rgb(hues[0], 0.9, 0.03)
        if len(sim.x):
            flash = np.exp(-np.maximum(0.0, st.time - sim.hit) / 0.12)
            hue = hues[0] + (hues[1] - hues[0]) * sim.shade[sim.ids]
            colors = hsvArray(hue, 1.0, 1.0) * (1 - flash[:, None]) * 0.85 + flash[:, None]
            # Each ball lit across its width, with soft half-LED edges
            dist = np.abs(self.d[None, :] - sim.x[:, None])
            shape = np.clip(BALL_WIDTH / 2.0 + 0.5 - dist, 0, 1)
            out += (shape.T @ colors).astype(np.float32) * level
        if p > 0.92:
            q = (p - 0.92) / 0.08
            mix = (self.d / LONGEST)[:, None]
            full = ((1 - mix) * rgb(hues[0], 0.85, 1.0) + mix * rgb(hues[1], 0.85, 1.0)) * level
            out[:] = out * (1 - q) + full * q

    def soften(self, out, st, hues):
        # The glow under everything, the effects brought closer to it, and a soft limiter on top. A
        # build-up climbs back to full contrast as its drop gets close.
        p = st.build ** 2 if st.build is not None else 0.0
        gain = OVERLAY + (1 - OVERLAY) * p
        ceiling = CEILING + (1.2 - CEILING) * p
        mix = (self.d / LONGEST)[:, None]
        glow = (1 - mix) * rgb(hues[0], 0.8, 1.0) + mix * rgb(hues[1], 0.8, 1.0)
        out = glow * (AMBIENT + AMBIENT_ENERGY * st.energy) + gain * out
        return ceiling * (1 - np.exp(-out / ceiling))

    def noteHue(self, hues, note):
        return hues[0] + (hues[1] - hues[0]) * (note / 11.0) if note >= 0 else hues[0]

    # ------------------------------------------------------------ patterns (chosen per section in the editor)

    def buildUp(self, out, st, hues, level):
        # Pulses rush in from the far ends, faster and whiter as the drop gets close. How fast they fire
        # comes from the drop's build-up speeds (set in the editor), see buildFirings.
        p = st.build
        speed = LONGEST / CROSS_BEATS
        out += rgb(hues[0], 0.9, 0.04 + 0.10 * st.energy)
        a = self.clock.analysis
        if a is not None and st.buildDrop is not None:
            fire = self.firings(st.buildDrop, a)
            u = st.beatsToDrop
            reach = LONGEST / (speed * 1.4) + 0.3        # beats a pulse takes to cross the strip
            for f in fire[np.searchsorted(fire, u):np.searchsorted(fire, u + reach)]:
                pos = LONGEST - (f - u) * speed * 1.4
                if pos < -20:
                    continue
                self.pulse(out, pos, rgb(hues[0] + 40 * p, 1.0 - 0.8 * p, 0.4 + 0.6 * p) * level, width=3.0, tail=12.0, inward=True)
        out += (p ** 2 * 0.3) * (self.d / LONGEST)[:, None] * rgb(0, 0, 1)

    def firings(self, d, a):
        key = (d['time'], d['buildStart'], repr(d.get('stages')), bool(d.get('smooth')), len(a.beats), float(a.beats[0]))
        cache = getattr(self, '_firings', {})
        if key not in cache:
            if len(cache) > 32:
                cache.clear()
            cache[key] = buildFirings(d, round(a.beatAt(d['time'])) - a.beatAt(d['buildStart']))
            self._firings = cache
        return cache[key]

    def draw_pulses(self, out, st, hues, level):
        # Beats leave the matrix as pulses; each coloured by the melody note on that beat
        speed = LONGEST / CROSS_BEATS
        out += rgb(hues[0], 0.9, 0.04 + 0.10 * st.energy)
        first = int(math.floor(st.beat))
        for k in range(first - int(CROSS_BEATS) - 2, first + 1):
            age = st.beat - k
            if age < 0:
                continue
            note = self.note(2 * k)
            strength = (1.0 if k % 4 == 0 else 0.7) * level
            self.pulse(out, age * speed, rgb(self.noteHue(hues, note), 0.85, strength), tail=20 + 40 * st.energy)
            if st.energy > 0.65 and age > 0.5:
                # Busy parts: a smaller pulse on the off-beat too
                note2 = self.note(2 * k + 1)
                self.pulse(out, (age - 0.5) * speed, rgb(self.noteHue(hues, note2 if note2 >= 0 else note), 0.9, 0.45 * strength),
                           width=2.5, tail=12)

    def draw_notes(self, out, st, hues, level):
        # The notes from the song's Clone Hero chart. Each melody note (guitar, else keys or bass) leaves
        # the matrix as a pulse coloured by its lane, and a held note leaves a streak behind it for as
        # long as it's held. Kicks swell the whole strip, snares throw pale sparkles everywhere, hi-hats
        # and cymbals sparkle. Where the chart has nothing (an intro, a breakdown), beat pulses instead.
        a = self.clock.analysis
        if a is None or not a.hasNotes:
            return self.draw_pulses(out, st, hues, level)
        t = st.time
        speed = LONGEST / (CROSS_BEATS * st.period)   # LEDs a second
        window = 1.3 * CROSS_BEATS * st.period          # how long a pulse takes to leave the strip
        lead = a.lead
        i0 = int(np.searchsorted(lead[:, 0], t - window - NOTE_HOLD_MAX))
        i1 = int(np.searchsorted(lead[:, 0], t, 'right'))
        notes = lead[i0:i1]
        j0 = int(np.searchsorted(a.drumTimes, t - 0.6))
        j1 = int(np.searchsorted(a.drumTimes, t, 'right'))
        quiet = 2 * st.period
        busy = (len(notes) and (t - notes[-1, 0] < quiet or np.any(notes[:, 0] + notes[:, 2] > t))) or                (j1 > 0 and t - a.drumTimes[j1 - 1] < quiet)
        if not busy:
            return self.draw_pulses(out, st, hues, level)
        out += rgb(hues[0], 0.9, 0.04 + 0.08 * st.energy)
        # All the notes at once: one row per note still on the strip
        ages = t - notes[:, 0]
        held = notes[:, 2]
        heads = ages * speed
        tails = np.maximum(0.0, ages - held) * speed
        live = (ages < window) | ((held > 0) & (tails < LONGEST))
        if live.any():
            lanes, ages, held, heads, tails = notes[live, 1], ages[live], held[live], heads[live], tails[live]
            hue = hues[0] + (hues[1] - hues[0]) * np.maximum(lanes, 0) / 4.0
            # An open note (lane -1) is all lanes at once: nearly white
            colors = np.where((lanes >= 0)[:, None], hsvArray(hue, 0.85, level), hsvArray(hue, 0.3, level))
            x = self.d[None, :] - heads[:, None]
            shape = np.where(x > 0, np.exp(-(x / 3.0) ** 2), np.exp(np.minimum(x, 0) / 10.0)) * (ages < window)[:, None]
            # A held note's streak runs from where it started to where it is now
            shape += 0.4 * ((self.d[None, :] >= tails[:, None]) & (x <= 0) & ((held > 0) & (heads - tails > 1))[:, None])
            out += (shape.T @ colors).astype(np.float32)
        for k in range(j0, j1):
            age = t - a.drumTimes[k]
            lane = a.drumLanes[k]
            if lane == 0:
                if a.drumAccent[k]:
                    out += rgb(hues[0], 0.85, 0.3 * level * math.exp(-age / 0.18))
                continue
            if lane == 1 and not a.drumAccent[k]:
                continue
            count, sat, strength, fade = {1: (40, 0.2, 0.9, 0.12), 2: (6, 0.3, 0.35, 0.12)}.get(lane, (14, 0.3, 0.8, 0.3))
            out[self.spots[k % len(self.spots), :count]] += rgb(hues[1], sat, 1.0) * (level * strength * math.exp(-age / fade))

    def draw_breathe(self, out, st, hues, level):
        # The whole strip swells on each beat, shading from one colour at the matrix to the other at the ends
        phase = st.beat % 1.0
        bar = 1.0 if int(math.floor(st.beat)) % 4 == 0 else 0.75
        swell = level * bar * (0.2 + 0.8 * math.exp(-phase * 3.5))
        mix = (self.d / LONGEST)[:, None]
        out += ((1 - mix) * rgb(hues[0], 0.85, 1.0) + mix * rgb(hues[1], 0.85, 1.0)) * swell

    def draw_chase(self, out, st, hues, level):
        # A bright comet runs the full length on every beat
        k = int(math.floor(st.beat))
        phase = st.beat - k
        out += rgb(hues[0], 0.9, 0.05)
        self.pulse(out, phase * LONGEST * 1.1, rgb(self.noteHue(hues, self.note(2 * k)), 0.8, level), width=6, tail=70)

    def draw_sparkle(self, out, st, hues, level):
        # Twinkles land on every half beat and fade
        out += rgb(hues[0], 0.9, 0.03)
        now = st.beat * 2
        for k in range(int(math.floor(now)) - 3, int(math.floor(now)) + 1):
            age = (now - k) / 2 * st.period
            rng = np.random.RandomState(k & 0x7fffffff)
            spots = rng.randint(0, LONGEST, 18)
            colors = np.array([rgb(hues[0] + (hues[1] - hues[0]) * f, 0.6, 1.0) for f in rng.rand(18)], np.float32)
            out[spots] += colors * (level * math.exp(-age / 0.25))

    def draw_rainbow(self, out, st, hues, level):
        # A rainbow sliding away from the matrix, a step per beat, brightening on the beat
        phase = st.beat % 1.0
        out += hsvArray(self.d * 1.2 - st.beat * 40.0, 1.0, level * (0.35 + 0.65 * math.exp(-phase * 4)))

    def draw_solid(self, out, st, hues, level):
        # Steady colour with a small lift on each beat
        phase = st.beat % 1.0
        out += rgb(hues[0], 0.85, 1.0) * (0.45 * level + 0.2 * math.exp(-phase * 5))

    def draw_strobe(self, out, st, hues, level):
        # A white flash on the beat (every other beat for fast songs: never over MAX_FLASHES a second)
        every = 1 if 1.0 / st.period <= MAX_FLASHES else 2
        k = int(math.floor(st.beat))
        out += rgb(hues[0], 0.9, 0.03)
        if k % every == 0 and (st.beat - k) * st.period < FLASH_ON:
            out[:] = np.maximum(out, 0.9)

    # ------------------------------------------------------------ calm patterns (quiet sections get one by default)

    def draw_drift(self, out, st, hues, level):
        # The section's two colours in long bands drifting slowly out from the matrix (one band every
        # 8 bars), swelling very slightly on each bar
        pos = self.d / LONGEST * 1.5 - st.beat / 32.0
        f = (0.5 + 0.5 * np.sin(2 * np.pi * pos))[:, None]
        swell = 0.85 + 0.15 * math.exp(-(st.beat % 4.0) * 1.5)
        out += ((1 - f) * rgb(hues[0], 0.85, 1.0) + f * rgb(hues[1], 0.85, 1.0)) * (0.45 * level * swell)

    def draw_waves(self, out, st, hues, level):
        # A soft, wide wave rolls out from the matrix on each bar, alternating between the two colours
        bar = st.beat / 4.0
        for k in range(int(math.floor(bar)) - 2, int(math.floor(bar)) + 1):
            age = bar - k
            if age < 0:
                continue
            pos = age * LONGEST / 1.5
            color = rgb(hues[k % 2], 0.8, 0.45 * level * max(0.0, 1 - age / 2.5))
            out += np.exp(-((self.d - pos) / 35.0) ** 2)[:, None] * color

    def draw_aurora(self, out, st, hues, level):
        # Slow shimmering curtains in the section's colours, like the northern lights; barely follows the beat
        t = st.time
        d = self.d / LONGEST
        v = (np.sin(2 * np.pi * (d * 2.3 + t * 0.07)) + np.sin(2 * np.pi * (d * 5.1 - t * 0.11))
             + 0.6 * np.sin(2 * np.pi * (d * 9.7 + t * 0.17)))
        bright = np.clip(0.5 + v / 5.2, 0, 1) ** 1.5
        hue = hues[0] + (hues[1] - hues[0]) * np.clip(0.5 + np.sin(2 * np.pi * (d * 1.3 - t * 0.05)) / 2, 0, 1)
        out += hsvArray(hue, 0.8, 1.0) * (bright * 0.5 * level)[:, None]

    def draw_off(self, out, st, hues, level):
        pass

    # ------------------------------------------------------------ output

    def send(self, frame):
        # Map distance-from-matrix to each strip's own LED order, gamma-correct, and send over DDP
        values = (np.clip(frame, 0, 1) ** GAMMA * 255).astype(np.uint8)
        for start, n, lit in STRIPS:
            self.raw[start:start + lit] = values[:lit][::-1]
        data = self.raw.tobytes()
        ip = getattr(self.clock.mic, 'source', None) or WLED_IP
        self.seq = self.seq % 15 + 1
        for offset in range(0, len(data), 1440):
            chunk = data[offset:offset + 1440]
            last = offset + 1440 >= len(data)
            # DDP: version 1 (+ push on the last packet), sequence, RGB 8-bit, display 1, offset, length
            header = struct.pack('>BBBBIH', 0x41 if last else 0x40, self.seq, 0x0B, 1, offset, len(chunk))
            self.sock.sendto(header + chunk, (ip, DDP_PORT))

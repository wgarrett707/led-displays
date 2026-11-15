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
# Both strips are fed from their far ends: (first LED, LED count); the last LED is at the matrix
STRIPS = [(0, 224), (224, 440)]
LONGEST = max(n for s, n in STRIPS)
# Pulses cross the longest strip in this many beats
CROSS_BEATS = 2.5
# After a drop: a white hit, then a strobe on the beat for this many bars (0 = no strobe).
# Never faster than MAX_FLASHES a second (every other beat for fast songs).
DROP_STROBE_BARS = 2
MAX_FLASHES = 3.0
FLASH_ON = 0.05
# Hue ranges (degrees, start..end, may run past 360) per section label; the chorus always gets HOT, so it looks the same each time
PALETTES = [(205, 265), (165, 215), (265, 320), (25, 50), (95, 160), (330, 375), (185, 240), (45, 110)]
HOT = (310, 400)
GAMMA = 2.2
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


class Strips(threading.Thread):
    def __init__(self, clock):
        threading.Thread.__init__(self, daemon=True)
        self.clock = clock
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0
        self.d = np.arange(LONGEST, dtype=np.float32)   # distance from the matrix, in LEDs
        # Where each drum hit's sparkles land (the same LEDs every time the hit plays)
        self.spots = np.random.RandomState(1).randint(0, LONGEST, (4096, 40))
        self.raw = np.zeros((sum(n for s, n in STRIPS), 3), np.uint8)

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
        # Songs with a Clone Hero chart play its notes unless the section's pattern was set in the editor
        pattern = st.section.get('pattern') or ('notes' if a is not None and a.hasNotes else 'pulses')
        if st.build is not None and pattern != 'off':
            self.buildUp(out, st, hues, level)
        else:
            getattr(self, 'draw_' + pattern, self.draw_pulses)(out, st, hues, level)

        if st.sinceLift is not None and st.sinceLift < 0.6:
            # A lift (a big entrance that isn't quite a drop): one wide wave of colour
            self.pulse(out, st.sinceLift / (st.period * CROSS_BEATS) * LONGEST * 1.2, rgb(hues[1], 0.6, 1.0), width=25, tail=60)

        if st.sinceDrop is not None:
            beatsSince = st.sinceDrop / st.period
            out += math.exp(-st.sinceDrop / 0.3) * 1.2   # white hit
            if beatsSince < 4 * DROP_STROBE_BARS:
                every = 1 if 1.0 / st.period <= MAX_FLASHES else 2
                if int(math.floor(beatsSince)) % every == 0 and (beatsSince % 1.0) * st.period < FLASH_ON:
                    out = np.maximum(out, 0.9)
        return out

    def noteHue(self, hues, note):
        return hues[0] + (hues[1] - hues[0]) * (note / 11.0) if note >= 0 else hues[0]

    # ------------------------------------------------------------ patterns (chosen per section in the editor)

    def buildUp(self, out, st, hues, level):
        # Pulses rush in from the far ends, faster and whiter as the drop gets close
        p = st.build
        speed = LONGEST / CROSS_BEATS
        out += rgb(hues[0], 0.9, 0.04 + 0.10 * st.energy)
        sub = 1 if p < 0.5 else 2 if p < 0.8 else 4
        count = st.beat * sub
        for k in range(int(math.floor(count)) - 6 * sub, int(math.floor(count)) + 1):
            age = (count - k) / sub
            pos = LONGEST - age * speed * 1.4
            if pos < -20:
                continue
            self.pulse(out, pos, rgb(hues[0] + 40 * p, 1.0 - 0.8 * p, 0.4 + 0.6 * p) * level, width=3.0, tail=12.0, inward=True)
        out += (p ** 2 * 0.3) * (self.d / LONGEST)[:, None] * rgb(0, 0, 1)

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

    def draw_off(self, out, st, hues, level):
        pass

    # ------------------------------------------------------------ output

    def send(self, frame):
        # Map distance-from-matrix to each strip's own LED order, gamma-correct, and send over DDP
        values = (np.clip(frame, 0, 1) ** GAMMA * 255).astype(np.uint8)
        for start, n in STRIPS:
            self.raw[start:start + n] = values[:n][::-1]
        data = self.raw.tobytes()
        ip = getattr(self.clock.mic, 'source', None) or WLED_IP
        self.seq = self.seq % 15 + 1
        for offset in range(0, len(data), 1440):
            chunk = data[offset:offset + 1440]
            last = offset + 1440 >= len(data)
            # DDP: version 1 (+ push on the last packet), sequence, RGB 8-bit, display 1, offset, length
            header = struct.pack('>BBBBIH', 0x41 if last else 0x40, self.seq, 0x0B, 1, offset, len(chunk))
            self.sock.sendto(header + chunk, (ip, DDP_PORT))

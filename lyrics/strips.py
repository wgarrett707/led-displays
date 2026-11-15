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


def rgb(hue, sat, val):
    return np.array(colorsys.hsv_to_rgb((hue % 360) / 360.0, sat, val), np.float32)


class Strips(threading.Thread):
    def __init__(self, clock):
        threading.Thread.__init__(self, daemon=True)
        self.clock = clock
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0
        self.d = np.arange(LONGEST, dtype=np.float32)   # distance from the matrix, in LEDs
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
        if st.section.get('chorus'):
            return HOT
        return PALETTES[(ord(st.section['label']) - 65) % len(PALETTES)]

    def pulse(self, out, pos, color, width=4.0, tail=30.0, inward=False):
        # A bright head at 'pos' with a fading tail behind it (towards the matrix, or away from it
        # for a pulse travelling inwards)
        x = pos - self.d if inward else self.d - pos
        shape = np.where(x > 0, np.exp(-(x / width) ** 2), np.exp(x / tail))
        out += shape[:, None] * color[None, :]

    def render(self, st):
        out = np.zeros((LONGEST, 3), np.float32)
        hueA, hueB = self.palette(st)
        energy = st.energy
        level = 0.35 + 0.65 * energy
        speed = LONGEST / CROSS_BEATS
        out += rgb(hueA, 0.9, 0.04 + 0.10 * energy)

        def noteHue(note):
            return hueA + (hueB - hueA) * (note / 11.0) if note >= 0 else hueA

        a = self.clock.analysis
        notes = a.notes if a is not None else np.array([])

        if st.build is not None:
            # Build-up: pulses rush in from the far ends, faster and whiter as the drop gets close
            p = st.build
            sub = 1 if p < 0.5 else 2 if p < 0.8 else 4
            count = st.beat * sub
            for k in range(int(math.floor(count)) - 6 * sub, int(math.floor(count)) + 1):
                age = (count - k) / sub
                pos = LONGEST - age * speed * 1.4
                if pos < -20:
                    continue
                color = rgb(hueA + 40 * p, 1.0 - 0.8 * p, 0.4 + 0.6 * p)
                self.pulse(out, pos, color * level, width=3.0, tail=12.0, inward=True)
            out += (p ** 2 * 0.3) * (self.d / LONGEST)[:, None] * rgb(0, 0, 1)
        else:
            # Beats leave the matrix as pulses; each one coloured by the melody note on that beat
            first = int(math.floor(st.beat))
            for k in range(first - int(CROSS_BEATS) - 2, first + 1):
                age = st.beat - k
                if age < 0:
                    continue
                index = k + a.downbeat if a is not None else k
                half = 2 * index
                note = int(notes[half]) if 0 <= half < len(notes) else -1
                strength = (1.0 if k % 4 == 0 else 0.7) * level
                self.pulse(out, age * speed, rgb(noteHue(note), 0.85, strength), tail=20 + 40 * energy)
                if energy > 0.65 and age > 0.5:
                    # Busy parts: a smaller pulse on the off-beat too
                    note2 = int(notes[half + 1]) if 0 <= half + 1 < len(notes) else note
                    self.pulse(out, (age - 0.5) * speed, rgb(noteHue(note2), 0.9, 0.45 * strength), width=2.5, tail=12)

        if st.sinceLift is not None and st.sinceLift < 0.6:
            # A lift (a big entrance that isn't quite a drop): one wide wave of colour
            self.pulse(out, st.sinceLift / (st.period * CROSS_BEATS) * LONGEST * 1.2, rgb(hueB, 0.6, 1.0), width=25, tail=60)

        if st.sinceDrop is not None:
            beatsSince = st.sinceDrop / st.period
            out += math.exp(-st.sinceDrop / 0.3) * 1.2   # white hit
            if beatsSince < 4 * DROP_STROBE_BARS:
                every = 1 if 1.0 / st.period <= MAX_FLASHES else 2
                if int(math.floor(beatsSince)) % every == 0 and (beatsSince % 1.0) * st.period < FLASH_ON:
                    out = np.maximum(out, 0.9)
        return out

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

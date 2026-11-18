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
import zlib
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
# After a drop: one white flash. A drop set to strobe in the editor (style 'strobe') also strobes on the
# beat, for its 'strobeBars' bars (set in the editor) or else this many. Never over MAX_FLASHES a second.
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
# The chart-notes pattern shows beat pulses only after this many beats without a chart note (an intro, a
# breakdown); shorter rests, like those in a repeating riff, stay as they are
NOTES_GAP = 8
# 'notehype' marks: chart-note pulses (width, tail, saturation, brightness, held-note streak) instead of
# the usual (3, 10, 0.85, 1.0, 0.4)
HYPE_NOTES = (5.0, 18.0, 0.55, 1.35, 0.6)
# 'notepulse' marks: the strip's glow between notes (0-1), and how fast a short note's hit fades (s; a
# held note fades over its hold plus this)
NOTE_PULSE_GLOW = 0.18
NOTE_PULSE_FADE = 0.12
# 'notetoggle' marks: how lit the strip stays (0-1) between the note that turns it on and the one that turns it off
NOTE_TOGGLE_ON = 0.6
# ... and how much of the usual background glow it keeps (0-1), so 'off' reads as off
NOTE_TOGGLE_AMBIENT = 0.15
# 'notefret' marks: a lit area's shade (degrees round the colour wheel from the section's colours), how much
# brighter it hits, and how much of the usual background glow the effect keeps (0-1)
NOTE_FRET_SHIFT = 40
NOTE_FRET_BOOST = 1.4
NOTE_FRET_AMBIENT = 0.5
# ... and how long a short note's lit area takes to fade (s; a held note's is stretched over its hold too)
NOTE_FRET_FADE = 0.3
# A song with no analysis yet: one of these hues (blue, violet, rose, pink), and how bright (0-1)
WAITING_HUES = (225, 270, 328, 302)
WAITING_LEVEL = 0.85
# ... its comets: (LEDs a second, starting point 0-1, hue shift in degrees)
WAITING_COMETS = ((38, 0.0, -14), (55, 0.37, 0), (72, 0.71, 14))
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
    # rate holds from that point until the next stage; a rate of 0 is quiet (the music cuts out: no pulses,
    # and the strips go dark, see quietSpans); without stages it's 1 a beat, then 2 from halfway, then 4 for
    # the last fifth. Pulses fall on whole fractions of a beat counted back from the drop, so
    # they lock to the beat. With 'smooth', each stage speeds up gradually into the next instead of
    # jumping. The editor (editor.html, firings) works this out the same way to show the pulses.
    stages = d.get('stages') or [[total, 1], [0.5 * total, 2], [0.2 * total, 4]]
    st = sorted([(min(float(b), total), float(r)) for b, r in stages if min(float(b), total) > 0 and float(r) >= 0], reverse=True)
    out = []
    for i, (b, r) in enumerate(st):
        end = st[i + 1][0] if i + 1 < len(st) else 0.0
        if r <= 0:
            continue                                   # quiet
        if d.get('smooth') and i + 1 < len(st) and st[i + 1][1] > 0:
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


def quietSpans(d, total):
    # The quiet stretches of a drop's build-up (rate 0: the music cuts out), as (from, to) beats before the
    # drop, from > to
    st = sorted([(min(float(b), total), float(r)) for b, r in (d.get('stages') or [])
                 if min(float(b), total) > 0 and float(r) >= 0], reverse=True)
    return [(b, st[i + 1][0] if i + 1 < len(st) else 0.0) for i, (b, r) in enumerate(st) if r <= 0]


def noteFade(age, held, fade=None):
    # How bright a note's light is (1 at the hit) 'age' seconds in: a short note fades in about a tenth of a
    # second; a held note fades more slowly, stretched over its hold (to about 15% at its end), and keeps
    # fading after, so it never cuts off
    return math.exp(-age / ((fade or NOTE_PULSE_FADE) + 0.5 * held))


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
        self.burst = np.exp(-self.d / 25.0)[:, None]      # where a 'hype' note's burst of light lands
        self.raw = np.zeros((sum(n for s, n, lit in STRIPS), 3), np.uint8)   # the curved LEDs stay 0

    def run(self):
        frame = 1.0 / FPS
        next_ = time.monotonic()
        while True:
            try:
                st = self.clock.state(time.monotonic(), LEAD)
                if st is None:
                    song = self.clock.unanalysed()
                    if song is None:
                        # Nothing to follow (paused, nothing playing): stop sending and WLED takes its own
                        # effects back
                        time.sleep(0.1)
                        next_ = time.monotonic()
                        continue
                    # A song that hasn't been analysed yet: a calm look of its own
                    self.send(self.waiting(song, time.monotonic()))
                else:
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

    # ------------------------------------------------------------ a song with no analysis yet

    def waiting(self, song, now):
        # One colour for the song (blue, violet, rose or pink: picked from its id, so it's the same each time
        # it plays): a dim glow in it with a slow wave running through, three soft comets travelling out from
        # the matrix at different speeds (so they keep overtaking each other) in slightly different shades,
        # and pale twinkles fading in and out. On the clock, not the beat, so it looks right at any tempo.
        hue = WAITING_HUES[zlib.crc32(song.encode()) % len(WAITING_HUES)]
        d = self.d / LONGEST
        glow = 0.3 + 0.1 * np.sin(2 * np.pi * (d * 1.7 - now * 0.11))
        out = hsvArray(hue + 8 * np.sin(2 * np.pi * (d * 2.9 + now * 0.05)), 0.85, 1.0) * glow[:, None]
        span = LONGEST + 90
        for speed, phase, shade in WAITING_COMETS:
            pos = (now * speed + phase * span) % span - 45
            x = self.d - pos
            shape = np.where(x > 0, np.exp(-(x / 6.0) ** 2), np.exp(np.minimum(x, 0) / 35.0))
            out += shape[:, None] * rgb(hue + shade, 0.75, 0.9)
        slot = int(math.floor(now * 4))          # a new twinkle every quarter second, each lasting 1.2 s
        for k in range(slot - 5, slot + 1):
            age = now - k / 4.0
            if 0 <= age < 1.2:
                out[self.spots[k % len(self.spots), :2]] += rgb(hue, 0.35, 0.8) * math.sin(math.pi * age / 1.2)
        return out * WAITING_LEVEL

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
        # The section's pattern from the editor; otherwise the song's Clone Hero chart notes where the chart
        # has notes, a calm pattern for other quiet sections, else beat pulses
        pattern = st.section.get('pattern')
        if not pattern:
            hasChart = a is not None and a.hasNotes
            if hasChart and a.sectionNotes[st.sectionIndex]:
                pattern = 'notes'
            elif st.section.get('energy', 1.0) < CALM_BELOW and st.build is None:
                pattern = CALM_PATTERN
            else:
                pattern = 'notes' if hasChart else 'pulses'
        if st.balls is not None:
            # A 'balls' effect marked in the editor takes over from the pattern while it runs
            self.drawBalls(out, st, hues, level)
            pattern = 'balls'
        elif st.noteStyle is not None and a is not None and a.hasNotes:
            # So does another way of showing the chart's notes, marked in the editor
            self.drawNoteStyle(out, st, hues, level)
            pattern = st.noteStyle
        elif st.hype and a is not None and a.hasNotes:
            # And a 'hype' mark: the chart's notes, more intense (see draw_notes)
            self.draw_notes(out, st, hues, level)
            pattern = 'notes'
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
            drop = st.lastDrop or {}
            # Beats since the drop, counted on the beat grid (dividing the time by the current beat's length
            # jumped back a little where beat lengths differ by a millisecond, splitting a strobe flash in two)
            beatsSince = st.index - a.beatAt(drop['time']) if a is not None and drop else st.sinceDrop / st.period
            out += math.exp(-st.sinceDrop / 0.3) * 1.2   # white hit
            if drop.get('style') == 'strobe' and beatsSince < 4 * drop.get('strobeBars', DROP_STROBE_BARS):
                every = 1 if 1.0 / st.period <= MAX_FLASHES else 2
                if int(math.floor(beatsSince)) % every == 0 and (beatsSince % 1.0) * st.period < FLASH_ON:
                    out = np.maximum(out, 0.9)
        if st.build is not None and st.buildDrop is not None and st.buildDrop.get('stages'):
            # A quiet stretch in the build-up (the music cuts out): the strips go dark, in about 0.12 s
            for start, end in self.quiet(st.buildDrop, self.clock.analysis):
                if end < st.beatsToDrop <= start:
                    out = out * max(0.0, 1 - (start - st.beatsToDrop) * st.period / 0.12)
        if st.fade < 1.0:
            # A fade-out marked in the editor: everything fades to black (and stays dark)
            out = out * st.fade
        return out

    def noteHits(self, a):
        # The notes the 'notepulse' and 'notecolor' marks follow: the chart's melody, or for a drums-only
        # chart its (accented) kicks and snares
        if len(a.lead):
            return a.lead
        hits = getattr(self, '_hits', None)
        if hits is None or hits[0] is not a:
            keep = a.drumAccent & (a.drumLanes <= 1)
            arr = np.zeros((int(keep.sum()), 3))
            arr[:, 0], arr[:, 1] = a.drumTimes[keep], a.drumLanes[keep]
            hits = (a, arr)
            self._hits = hits
        return hits[1]

    def drawNoteStyle(self, out, st, hues, level):
        # The strip glows dimly in the section's colours (NOTE_PULSE_GLOW) and lights up on the chart's notes.
        # Each note hits at full brightness and fades away smoothly: a short note in about a tenth of a second,
        # a held note more slowly, stretched over its hold (noteFade), so it never cuts off.
        #  'notepulse': the whole strip lights up on each note.
        #  'notetoggle': the whole strip lights up on one note and stays lit, then fades out on the next, and
        #   so on (a chord counts as one note).
        #  'notefret': each note lights the part of the strip for its fret: green nearest the matrix, orange
        #   at the far end (an open note lights it all); in the section's colours, not the frets'.
        #  'notecolor': the whole strip is one colour and changes on each note: each fret its own colour,
        #   spread round the colour wheel from the section's first colour (open notes white), crossfading in
        #   60 ms.
        notes = self.noteHits(self.clock.analysis)
        t = st.time
        i1 = int(np.searchsorted(notes[:, 0], t, 'right'))
        mix = (self.d / LONGEST)[:, None]
        if st.noteStyle in ('notepulse', 'notetoggle', 'notefret'):
            lane = notes[i1 - 1, 1] if i1 else 0
            hue = hues[0] + (hues[1] - hues[0]) * max(0.0, lane) / 4.0
            if st.noteStyle == 'notefret':
                hue = hues[0]
            glow = (1 - mix) * rgb(hue, 0.85, 1.0) + mix * rgb(hues[1], 0.85, 1.0)
            if st.noteStyle == 'notepulse':
                swell = 0.0
                for t0, lane, held in notes[max(0, i1 - 24):i1]:
                    swell = max(swell, noteFade(t - t0, held))
                out += glow * (level * (NOTE_PULSE_GLOW + (1 - NOTE_PULSE_GLOW) * swell))
            elif st.noteStyle == 'notetoggle':
                onsets = self.onsets(notes)
                k = int(np.searchsorted(onsets, t, 'right')) - 1
                if k < 0:
                    swell = 0.0
                elif k % 2 == 0:
                    # On: a hit, settling to stay lit until the next note
                    swell = NOTE_TOGGLE_ON + (1 - NOTE_TOGGLE_ON) * math.exp(-(t - onsets[k]) / NOTE_PULSE_FADE)
                else:
                    # Off: fades out from where it was
                    swell = NOTE_TOGGLE_ON * math.exp(-(t - onsets[k]) / (2 * NOTE_PULSE_FADE))
                out += glow * (level * swell)
            else:
                # Per fret, the brightest of its notes now; then each fret's part of the strip
                lit = np.zeros(6)                     # frets 0-4, and open notes
                for t0, lane, held in notes[max(0, i1 - 40):i1]:
                    f = 5 if lane < 0 else int(lane)
                    lit[f] = max(lit[f], noteFade(t - t0, held, NOTE_FRET_FADE))
                shape = np.full(LONGEST, lit[5], np.float32)
                zone = LONGEST / 5.0
                for f in range(5):
                    if lit[f] > 0.01:
                        shape = np.maximum(shape, lit[f] * np.exp(-((self.d - (f + 0.5) * zone) / (0.5 * zone)) ** 2))
                # A lit area is brighter and a paler shade a little round the colour wheel, fading back into the
                # section's colour as it dims
                accent = (1 - mix) * rgb(hues[0] + NOTE_FRET_SHIFT, 0.45, 1.0) + mix * rgb(hues[1] + NOTE_FRET_SHIFT, 0.45, 1.0)
                k = shape[:, None]
                out += (glow * (1 - k) + accent * k) * (level * (NOTE_PULSE_GLOW + (1 - NOTE_PULSE_GLOW) * NOTE_FRET_BOOST * k))
            return

        def color(lane):
            return rgb(0, 0.0, 0.9) if lane < 0 else rgb(hues[0] + 72 * lane, 0.9, 1.0)
        if i1 == 0:
            c, accent = rgb(hues[0], 0.85, 1.0), 0.0
        else:
            age = t - notes[i1 - 1, 0]
            k = min(1.0, age / 0.06)
            prev = color(notes[i1 - 2, 1]) if i1 >= 2 else rgb(hues[0], 0.85, 1.0)
            c = prev * (1 - k) + color(notes[i1 - 1, 1]) * k
            accent = 0.15 * math.exp(-age / 0.15)
        out += c * (level * (0.6 + accent))

    def onsets(self, notes):
        # The distinct times notes start (a chord is one), for 'notetoggle'
        cache = getattr(self, '_onsets', None)
        if cache is None or cache[0] is not notes:
            cache = (notes, np.unique(np.round(notes[:, 0], 3)))
            self._onsets = cache
        return cache[1]

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
        if st.hype or st.noteStyle == 'notefret':
            p = 1.0     # a 'hype' mark, or the strip lighting up by fret: full contrast
        gain = OVERLAY + (1 - OVERLAY) * p
        ceiling = CEILING + (1.2 - CEILING) * p
        mix = (self.d / LONGEST)[:, None]
        glow = (1 - mix) * rgb(hues[0], 0.8, 1.0) + mix * rgb(hues[1], 0.8, 1.0)
        # 'notetoggle' marks keep only a little of the glow, so 'off' looks off
        ambient = (AMBIENT + AMBIENT_ENERGY * st.energy) * {'notetoggle': NOTE_TOGGLE_AMBIENT, 'notefret': NOTE_FRET_AMBIENT}.get(st.noteStyle, 1.0)
        out = glow * ambient + gain * out
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

    def quiet(self, d, a):
        key = ('quiet', d['time'], d['buildStart'], repr(d.get('stages')), len(a.beats), float(a.beats[0]))
        cache = getattr(self, '_firings', {})
        if key not in cache:
            if len(cache) > 32:
                cache.clear()
            cache[key] = quietSpans(d, round(a.beatAt(d['time'])) - a.beatAt(d['buildStart']))
            self._firings = cache
        return cache[key]

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
        # Under a 'hype' mark: bigger, whiter, brighter pulses with longer tails, a burst of light at the
        # matrix end on each note, bigger kick swells and more sparkles (and full contrast, see soften).
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
        # Beat pulses only where the chart has nothing for a while (NOTES_GAP beats), not in the rests of
        # a riff; and not just before a note
        gap, soon = NOTES_GAP * st.period, 2 * st.period
        upcoming = (i1 < len(lead) and lead[i1, 0] - t < soon) or (j1 < len(a.drumTimes) and a.drumTimes[j1] - t < soon)
        quiet = gap
        busy = upcoming or (len(notes) and (t - notes[-1, 0] < quiet or np.any(notes[:, 0] + notes[:, 2] > t))) or                (j1 > 0 and t - a.drumTimes[j1 - 1] < quiet)
        if not busy:
            return self.draw_pulses(out, st, hues, level)
        out += rgb(hues[0], 0.9, 0.04 + 0.08 * st.energy)
        width, tail, sat, bright, streak = HYPE_NOTES if st.hype else (3.0, 10.0, 0.85, 1.0, 0.4)
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
            colors = np.where((lanes >= 0)[:, None], hsvArray(hue, sat, level * bright), hsvArray(hue, 0.3, level * bright))
            x = self.d[None, :] - heads[:, None]
            shape = np.where(x > 0, np.exp(-(x / width) ** 2), np.exp(np.minimum(x, 0) / tail)) * (ages < window)[:, None]
            # A held note's streak runs from where it started to where it is now
            shape += streak * ((self.d[None, :] >= tails[:, None]) & (x <= 0) & ((held > 0) & (heads - tails > 1))[:, None])
            out += (shape.T @ colors).astype(np.float32)
            if st.hype:
                # A burst of light at the matrix end as each note fires
                fresh = ages < 0.25
                if fresh.any():
                    out += self.burst * (np.exp(-ages[fresh] / 0.08)[:, None] * colors[fresh]).sum(0).astype(np.float32)
        for k in range(j0, j1):
            age = t - a.drumTimes[k]
            lane = a.drumLanes[k]
            if lane == 0:
                if a.drumAccent[k]:
                    out += rgb(hues[0], 0.85, (0.5 if st.hype else 0.3) * level * math.exp(-age / 0.18))
                continue
            if lane == 1 and not a.drumAccent[k]:
                continue
            count, dsat, strength, fade = {1: (40, 0.2, 0.9, 0.12), 2: (6, 0.3, 0.35, 0.12)}.get(lane, (14, 0.3, 0.8, 0.3))
            if st.hype:
                count, strength = min(40, int(count * 1.5)), strength * 1.3
            out[self.spots[k % len(self.spots), :count]] += rgb(hues[1], dsat, 1.0) * (level * strength * math.exp(-age / fade))

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

# Beat clock for the lights: each song's beats, bars, sections and drops (worked out on the PC by
# led-lights/analyze.py), lined up with what's actually heard. Spotify's position alone is off by
# up to a few tenths of a second (polling, plus the Bluetooth speaker's delay), so WLED's
# microphone is used to measure that offset: the bass hits it hears are matched against the
# song's own bass pattern every couple of seconds.
import base64
import collections
import json
import os
import socket
import struct
import threading
import time
import numpy as np

BEATS_DIR = '/home/pi/led-scripts/lyrics/beats'
PENDING_DIR = BEATS_DIR + '/pending'
PI_UID = 1000
# WLED's audio sync (AudioReactive usermod, "send" mode)
MULTICAST, PORT = '239.0.0.1', 11988
# Heard song time = Spotify position + offset. Before the microphone has measured it:
DEFAULT_OFFSET = -0.15
# WLED hears, analyses and sends the sound this long after it happens
MIC_LATENCY = 0.04
# Microphone history compared against the song, and how far from the current offset to look
WINDOW = 20.0
SEARCH = 0.6
TRACK_SEARCH = 0.12
# A seek (or a new play of the song) rather than a timing correction
SEEK = 1.5


def log(message):
    try:
        print(time.strftime('%H:%M:%S ') + message, flush=True)
    except Exception:
        pass


class Analysis:
    def __init__(self, data):
        self.tempo = data['tempo']
        self.beats = np.array(data['beats'])
        # Beat numbers count from a bar line, so beat % 4 == 0 on each bar's first beat
        self.downbeat = data['downbeat']
        self.energy = np.array(data['beatEnergy'], np.float32)
        self.bass = np.array(data['beatBass'], np.float32)
        self.notes = np.array(data['notes'])
        self.sections = data['sections']
        self.sectionStarts = np.array([s['start'] for s in self.sections])
        self.drops = data['drops']
        self.lifts = data['lifts']
        self.env = np.frombuffer(base64.b64decode(data['env']), np.uint8).astype(np.float32) / 255
        self.envRate = data['envRate']

    def beatAt(self, t):
        # Fractional beat index at song time t (extrapolated before the first and after the last)
        b = self.beats
        i = int(np.searchsorted(b, t, 'right')) - 1
        i = min(max(i, 0), len(b) - 2)
        return i + (t - b[i]) / (b[i + 1] - b[i])

    def envAt(self, times):
        return np.interp(times * self.envRate, np.arange(len(self.env)), self.env, left=0, right=0)


class BeatState:
    # Everything the lights need at one moment of the song
    def __init__(self, a, t):
        self.time = t
        index = a.beatAt(t)
        i = int(np.floor(index))
        n = len(a.beats)
        self.index = index
        self.beat = index - a.downbeat
        self.period = float(a.beats[min(max(i, 0) + 1, n - 1)] - a.beats[min(max(i, 0), n - 2)])
        self.tempo = 60.0 / self.period
        k = min(max(i, 0), n - 1)
        self.energy = float(a.energy[k])
        self.bass = float(a.bass[k])
        half = int(np.floor(index * 2))
        self.note = int(a.notes[half]) if 0 <= half < len(a.notes) else -1
        s = max(0, int(np.searchsorted(a.sectionStarts, t, 'right')) - 1)
        self.section = a.sections[s]
        self.sectionIndex = s
        self.sinceDrop = self.dropStrength = self.build = None
        for d in a.drops:
            if d['buildStart'] <= t < d['time']:
                self.build = (t - d['buildStart']) / max(0.1, d['time'] - d['buildStart'])
            elif t >= d['time']:
                self.sinceDrop, self.dropStrength = t - d['time'], d['strength']
        self.sinceLift = None
        for d in a.lifts:
            if t >= d['time']:
                self.sinceLift = t - d['time']


class Mic(threading.Thread):
    # Bass onsets from WLED's audio sync packets, timestamped on arrival
    def __init__(self):
        threading.Thread.__init__(self, daemon=True)
        self.lock = threading.Lock()
        self.samples = collections.deque(maxlen=int(WINDOW * 60))
        self.last = 0.0
        self.source = None    # WLED's address, from its packets

    def run(self):
        while True:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('', PORT))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                struct.pack('4s4s', socket.inet_aton(MULTICAST), socket.inet_aton('0.0.0.0')))
                previous = None
                while True:
                    data, address = sock.recvfrom(128)
                    if len(data) < 34 or data[:5] != b'00002':
                        continue
                    now = time.monotonic()
                    self.source = address[0]
                    level = data[18] + data[19] + data[20]     # the three lowest FFT bands (~40-200 Hz)
                    flux = max(0, level - previous) if previous is not None else 0
                    previous = level
                    with self.lock:
                        self.samples.append((now - MIC_LATENCY, flux))
                        self.last = now
            except Exception as e:
                log('Microphone sync: %r' % e)
                time.sleep(5)

    def recent(self, since):
        with self.lock:
            if time.monotonic() - self.last > 1.0:
                return None
            return np.array([s for s in self.samples if s[0] >= since], np.float64)


class BeatClock(threading.Thread):
    # Follows the current track (via getPlayback, a function returning lyrics.py's Playback),
    # loads its analysis or asks the PC for one, and keeps the offset measured
    def __init__(self, getPlayback):
        threading.Thread.__init__(self, daemon=True)
        self.getPlayback = getPlayback
        self.mic = Mic()
        self.lock = threading.Lock()
        self.trackId = None
        self.analysis = None
        self.playback = None
        self.offset = DEFAULT_OFFSET
        self.locked = False
        self.validFrom = 0.0
        self.candidate = None
        self.checked = 0.0
        for d in (BEATS_DIR, PENDING_DIR):
            if not os.path.isdir(d):
                os.makedirs(d)
                os.chown(d, PI_UID, PI_UID)

    def state(self, now, lead=0.0):
        # BeatState for local time 'now' (+ lead, to make up for output delay), or None when there's
        # nothing to follow (no analysis, nothing playing, paused)
        with self.lock:
            a, p, offset = self.analysis, self.playback, self.offset
        if a is None or p is None or not p.playing:
            return None
        return BeatState(a, p.position(now + lead) / 1000.0 + offset)

    def run(self):
        self.mic.start()
        while True:
            try:
                self._follow()
                self._measure()
            except Exception as e:
                log('Beat clock: %r' % e)
            time.sleep(1.0)

    def _follow(self):
        p = self.getPlayback()
        now = time.monotonic()
        with self.lock:
            old = self.playback
            if p is None or p.id != self.trackId:
                self.trackId = p.id if p else None
                self.analysis, self.offset, self.locked, self.candidate = None, DEFAULT_OFFSET, False, None
                self.validFrom, self.checked = now, 0.0
            elif old is not None and p is not old:
                # Spotify's position was re-anchored: keep the heard time continuous, unless it was a seek
                jump = (p.position(now) - old.position(now)) / 1000.0
                if abs(jump) > SEEK or p.playing != old.playing:
                    self.validFrom = now
                    if abs(jump) > SEEK:
                        self.locked, self.candidate = False, None
                else:
                    self.offset -= jump
                    self.validFrom = now
            self.playback = p
        if p is None or self.analysis is not None or now - self.checked < 5.0:
            return
        self.checked = now
        path = os.path.join(BEATS_DIR, p.id + '.json')
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if data.get('error'):
                return
            a = Analysis(data)
            with self.lock:
                if self.trackId == p.id:
                    self.analysis = a
            log('Beats for %s: %.1f BPM, %d drops' % (p.title, a.tempo, len(a.drops)))
        else:
            pending = os.path.join(PENDING_DIR, p.id + '.json')
            if not os.path.exists(pending):
                with open(pending, 'w') as f:
                    f.write(json.dumps({'id': p.id, 'title': p.title, 'artists': p.artists, 'album': p.album,
                                        'durationMs': p.durationMs, 'isrc': p.isrc}) + '\n')
                os.chown(pending, PI_UID, PI_UID)

    def _measure(self):
        # Match the last WINDOW seconds of microphone bass onsets against the song's bass onset
        # envelope over a range of offsets; the best match is the offset
        with self.lock:
            a, p, offset, locked = self.analysis, self.playback, self.offset, self.locked
        if a is None or p is None or not p.playing:
            return
        now = time.monotonic()
        mic = self.mic.recent(max(self.validFrom + 1.0, now - WINDOW))
        if mic is None or len(mic) < 8 * 40:
            return
        grid = np.arange(mic[0, 0], mic[-1, 0], 0.02)
        heard = np.interp(grid, mic[:, 0], mic[:, 1])
        if heard.std() < 1e-6:
            return
        heard = (heard - heard.mean()) / heard.std()
        song = p.progressMs / 1000.0 + (grid - p.at)
        span = TRACK_SEARCH if locked else SEARCH
        center = offset if locked else DEFAULT_OFFSET
        lags = np.arange(center - span, center + span + 1e-9, 0.01)
        ref = a.envAt(song[None, :] + lags[:, None])
        ref = (ref - ref.mean(1, keepdims=True)) / np.maximum(ref.std(1, keepdims=True), 1e-6)
        corr = (ref * heard[None, :]).mean(1)
        best = int(np.argmax(corr))
        # The runner-up at least a third of a beat away: when it's about as good, the match is ambiguous
        period = 60.0 / a.tempo
        far = np.abs(lags - lags[best]) > period / 3
        second = corr[far].max() if far.any() else -1.0
        good = corr[best] > 0.12 and corr[best] - second > 0.02
        found = float(lags[best])
        with self.lock:
            if self.playback is not p:
                return
            if not good:
                return
            if locked:
                # Small steady corrections; a sudden jump needs to show up twice in a row
                if abs(found - self.offset) < 0.05:
                    self.offset += 0.5 * (found - self.offset)
                elif self.candidate is not None and abs(found - self.candidate) < 0.03:
                    self.offset, self.candidate = found, None
                else:
                    self.candidate = found
            else:
                # First lock: two measurements in a row that agree
                if self.candidate is not None and abs(found - self.candidate) < 0.03:
                    self.offset, self.locked, self.candidate = found, True, None
                    log('Beat clock locked: offset %+.0f ms (match %.2f)' % (found * 1000, corr[best]))
                else:
                    self.candidate = found

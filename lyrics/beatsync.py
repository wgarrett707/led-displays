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
# Heard song time = Spotify position + offset. The offset is mostly the speaker's delay, the same for
# every song, so the room's usual offset is learned (ROOM_FILE) and each song's measurement is only
# accepted within ROOM_RANGE beats of it: bass hits repeat every beat, so a match a whole beat away
# can look almost as good as the right one. DEFAULT_OFFSET until anything has been learned.
DEFAULT_OFFSET = -0.20
ROOM_FILE = BEATS_DIR + '/room.json'
ROOM_RANGE = 0.4
# Matches at least this good teach the room offset
ROOM_TEACH = 0.2
# WLED hears, analyses and sends the sound this long after it happens
MIC_LATENCY = 0.04
# Microphone history compared against the song, and how far from the current offset to look once locked
WINDOW = 20.0
TRACK_SEARCH = 0.12
# A seek (or a new play of the song) rather than a timing correction
SEEK = 1.5
# Kick and snare accents from a chart: at most one per this many seconds each (about 3 a second)
ACCENT_GAP = 0.3
# Spotify positions: each poll's (position - local time); the median of the last ANCHORS is the
# song's start on the local clock, much steadier than any single poll
ANCHORS = 15


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
        # Strip effects marked in the editor, each {'type', 'time', 'end'}: 'fadeout' (the strips fade to
        # black from time to end, and stay dark) and 'balls' (balls filling up the strips)
        self.effects = [e for e in data.get('effects') or [] if e.get('type') in ('fadeout', 'balls') and e['end'] > e['time']]
        self.env = np.frombuffer(base64.b64decode(data['env']), np.uint8).astype(np.float32) / 255
        self.envRate = data['envRate']
        # Notes from a Clone Hero chart of the song (analyze.py / charts.py), already in song time:
        # the melody part as rows of (time, lane 0-4 or -1 for an open note, seconds held), and drum
        # hits as times and lanes (0 kick, 1 snare, 2-4 hi-hat / toms / cymbals)
        chart = data.get('chart') or {}
        self.chartName = '%s (charted by %s)' % (chart.get('name'), chart.get('charter')) if chart else None
        self.leadPart = next((k for k in ('guitar', 'guitarghl', 'keys', 'bass', 'bassghl') if chart.get(k)), None)
        self.lead = np.array(chart[self.leadPart], float).reshape(-1, 3) if self.leadPart else np.zeros((0, 3))
        drums = np.array(chart.get('drums') or [], float).reshape(-1, 2)
        self.drumTimes, self.drumLanes = drums[:, 0].copy(), drums[:, 1].astype(int)
        self.hasNotes = len(self.lead) > 0 or len(self.drumTimes) > 0
        # Per section: whether the chart has notes in it (those always play the notes, even quiet ones)
        self.sectionNotes = [bool(np.any((self.lead[:, 0] >= s['start']) & (self.lead[:, 0] < s.get('end', 1e9))) or
                                  np.any((self.drumTimes >= s['start']) & (self.drumTimes < s.get('end', 1e9))))
                             for s in self.sections]
        # Kicks and snares the strips light up: no closer together than ACCENT_GAP, so a busy drum
        # part never turns into a strobe
        self.drumAccent = np.zeros(len(self.drumTimes), bool)
        last = {}
        for k, (t, lane) in enumerate(zip(self.drumTimes, self.drumLanes)):
            if lane <= 1 and t - last.get(lane, -9.0) >= ACCENT_GAP:
                self.drumAccent[k] = True
                last[lane] = t

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
        self.lastDrop = None      # the drop sinceDrop counts from (its 'style' from the editor)
        # During a build-up: its drop (with any speeds set in the editor) and how many beats are left
        self.buildDrop = self.beatsToDrop = None
        for d in a.drops:
            if d['buildStart'] <= t < d['time']:
                self.build = (t - d['buildStart']) / max(0.1, d['time'] - d['buildStart'])
                # counted from the beat nearest the drop, so the pulses stay on the beat even if the
                # drop mark is a little off the grid
                self.buildDrop, self.beatsToDrop = d, round(a.beatAt(d['time'])) - index
            elif t >= d['time']:
                self.sinceDrop, self.dropStrength, self.lastDrop = t - d['time'], d['strength'], d
        # Marked effects: how far a fade-out has got (1 = none, 0 = dark) and the 'balls' effect running now
        self.fade, self.balls = 1.0, None
        for e in a.effects:
            if e['type'] == 'fadeout' and t >= e['time']:
                self.fade = min(self.fade, max(0.0, 1 - (t - e['time']) / (e['end'] - e['time'])))
            elif e['type'] == 'balls' and e['time'] <= t < e['end']:
                self.balls = e
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
        self.locked = False
        self.validFrom = 0.0
        self.candidate = None
        self.checked = 0.0
        self.loadedAt = 0.0
        self.anchors = collections.deque(maxlen=ANCHORS)
        self.anchorTrack = None
        self.roomSaved = 0.0
        for d in (BEATS_DIR, PENDING_DIR):
            if not os.path.isdir(d):
                os.makedirs(d)
                os.chown(d, PI_UID, PI_UID)
        try:
            with open(ROOM_FILE) as f:
                self.room = float(json.load(f)['offset'])
        except (OSError, ValueError, KeyError):
            self.room = DEFAULT_OFFSET
        self.offset = self.room

    def observe(self, p):
        # Every fresh Spotify poll (call from the polling thread, before any smoothing)
        with self.lock:
            if p is None or not p.playing:
                self.anchors.clear()
                return
            anchor = p.progressMs / 1000.0 - p.at
            if p.id != self.anchorTrack or (self.anchors and abs(anchor - float(np.median(self.anchors))) > SEEK):
                # New song or a seek: start over
                self.anchors.clear()
                self.anchorTrack = p.id
                self.locked, self.candidate = False, None
                self.validFrom = time.monotonic()
            self.anchors.append(anchor)

    def songTime(self, now):
        # Spotify's position at local time 'now' (s), from the median anchor (call with the lock held)
        if self.anchors:
            return float(np.median(self.anchors)) + now
        return self.playback.position(now) / 1000.0

    def state(self, now, lead=0.0):
        # BeatState for local time 'now' (+ lead, to make up for output delay), or None when there's
        # nothing to follow (no analysis, nothing playing, paused)
        with self.lock:
            a, p, offset = self.analysis, self.playback, self.offset
            if a is None or p is None or not p.playing:
                return None
            t = self.songTime(now + lead)
        return BeatState(a, t + offset)

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
                self.analysis, self.offset, self.locked, self.candidate = None, self.room, False, None
                self.validFrom, self.checked, self.loadedAt = now, 0.0, 0.0
            elif old is not None and p.playing != old.playing:
                # Paused or resumed: microphone history from before doesn't line up
                self.validFrom = now
            self.playback = p
        if p is None or now - self.checked < 5.0:
            return
        self.checked = now
        path = os.path.join(BEATS_DIR, p.id + '.json')
        if os.path.exists(path):
            # (Re)load when new or changed: an edit saved from the PC applies straight away
            changed = os.path.getmtime(path)
            if changed == self.loadedAt:
                return
            with open(path) as f:
                data = json.load(f)
            self.loadedAt = changed
            if data.get('error'):
                return
            a = Analysis(data)
            with self.lock:
                if self.trackId == p.id:
                    self.analysis = a
            log('Beats for %s: %.1f BPM, %d drops%s%s' % (p.title, a.tempo, len(a.drops),
                                                         ' (edited)' if data.get('edited') else '',
                                                         ', notes from %s' % a.chartName if a.hasNotes else ''))
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
        with self.lock:
            if len(self.anchors) < 3:
                return    # wait for a steady position
            song = float(np.median(self.anchors)) + grid
        period = 60.0 / a.tempo
        room = self.room
        if locked:
            lags = np.arange(offset - TRACK_SEARCH, offset + TRACK_SEARCH + 1e-9, 0.01)
            lags = lags[np.abs(lags - room) <= ROOM_RANGE * period]
        else:
            lags = np.arange(room - ROOM_RANGE * period, room + ROOM_RANGE * period + 1e-9, 0.01)
        if len(lags) < 3:
            return
        ref = a.envAt(song[None, :] + lags[:, None])
        ref = (ref - ref.mean(1, keepdims=True)) / np.maximum(ref.std(1, keepdims=True), 1e-6)
        corr = (ref * heard[None, :]).mean(1)
        best = int(np.argmax(corr))
        # The runner-up at least a third of a beat away: when it's about as good, the match is ambiguous
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
                    log('Beat clock locked: offset %+.0f ms (match %.2f, room %+.0f ms)' % (
                        found * 1000, corr[best], self.room * 1000))
                else:
                    self.candidate = found
            if self.locked and corr[best] >= ROOM_TEACH:
                # A clear match: the room's usual offset moves a little towards it
                self.room += 0.1 * (self.offset - self.room)
                if now - self.roomSaved > 60:
                    self.roomSaved = now
                    try:
                        with open(ROOM_FILE, 'w') as f:
                            json.dump({'offset': round(self.room, 4)}, f)
                        os.chown(ROOM_FILE, PI_UID, PI_UID)
                    except OSError:
                        pass

# Note charts for the LED strips: the guitar, drums, keys and bass notes from a Clone Hero / Rock Band
# chart of the song, lined up with our audio and stored in the song's analysis, so the strips can play
# the actual notes instead of guessing them.
#
# Charts are found through Chorus Encore (the search behind the Bridge chart downloader). A chart's
# notes are timed against the chart's own audio, which may start earlier or later than ours (or run a
# hair faster), so that audio is fetched just long enough to line the two up, then thrown away. Only
# the notes are kept.
import io
import json
import os
import re
import struct
import subprocess
import tempfile

import librosa
import mido
import numpy as np
import requests

SEARCH = 'https://api.enchor.us/search'
FILES = 'https://files.enchor.us/%s.sng'
HEADERS = {'User-Agent': 'led-lights-chart-lookup/0.1'}
# Bump to look again for charts for songs checked before (2: charts of a different edit, in pieces)
VERSION = 2
SR = 22050
# Onset envelopes for lining up: 150 frames a second
RATE = 150
HOP = SR // RATE
# Charts of a different edit than ours (extended, radio, live) fail to line up and are skipped;
# ones within this many seconds of our length are tried first
LENGTH_SLACK = 20


def log(message):
    import time
    print(time.strftime('%H:%M:%S ') + message, flush=True)


def _words(text):
    return re.sub(r'[^a-z0-9 ]', ' ', (text or '').lower()).split()


OTHER_VERSION = re.compile(r'\b(live|remix|cover|acoustic|extended|mashup|rework|bootleg|vip|edit)\b', re.I)


# ---------------------------------------------------------------- finding a chart

def candidates(title, artist, durationMs, ourTitle=''):
    # Charts of this song with notes the strips can use, best first: full-band charts (drums plus a
    # melody part), official ones (Harmonix and co. are carefully timed), close in length
    r = requests.post(SEARCH, json={'search': '%s %s' % (title, artist), 'page': 1}, headers=HEADERS, timeout=20)
    r.raise_for_status()
    want, by = set(_words(title)), set(_words(artist))
    out = []
    for c in r.json().get('data', []):
        name = c.get('name') or ''
        if not want <= set(_words(name)) or not by & set(_words(c.get('artist'))):
            continue
        if OTHER_VERSION.search(name) and not OTHER_VERSION.search(ourTitle):
            continue
        parts = set((c.get('notesData') or {}).get('instruments') or [])
        if not parts & {'guitar', 'guitarghl', 'drums', 'keys', 'bass', 'bassghl'}:
            continue
        off = abs((c.get('song_length') or 0) / 1000.0 - durationMs / 1000.0)
        score = (3 if 'drums' in parts else 0) + (2 if parts & {'guitar', 'keys', 'guitarghl'} else 0)
        score += 2 if (c.get('charter') or '') in ('Harmonix', 'Neversoft', 'FreeStyleGames') else 0
        score -= min(off, 60) / 10.0
        out.append((score, off, c))
    out.sort(key=lambda x: (x[1] > LENGTH_SLACK, -x[0]))
    return [c for score, off, c in out]


def _range(url, start, end):
    r = requests.get(url, headers=dict(HEADERS, Range='bytes=%d-%d' % (start, end - 1)), timeout=60)
    if r.status_code != 206:
        raise RuntimeError('chart download: HTTP %d' % r.status_code)
    return r.content


def readSng(md5):
    # The .sng package's metadata and file list (format: github.com/mdsitton/SngFileFormat), read from
    # its first 64 KB so only the files needed are downloaded
    url = FILES % md5
    head = _range(url, 0, 65536)
    if head[:6] != b'SNGPKG':
        raise RuntimeError('not a .sng chart')
    mask = np.frombuffer(head[10:26], np.uint8)
    pos = 26
    metaLength, count = struct.unpack_from('<QQ', head, pos)
    p = pos + 16
    meta = {}
    for _ in range(count):
        n, = struct.unpack_from('<i', head, p)
        key = head[p + 4:p + 4 + n].decode('utf-8', 'replace')
        p += 4 + n
        n, = struct.unpack_from('<i', head, p)
        meta[key] = head[p + 4:p + 4 + n].decode('utf-8', 'replace')
        p += 4 + n
    pos += 8 + metaLength
    _, count = struct.unpack_from('<QQ', head, pos)
    p = pos + 16
    files = {}
    for _ in range(count):
        n = head[p]
        name = head[p + 1:p + 1 + n].decode('utf-8', 'replace')
        size, index = struct.unpack_from('<QQ', head, p + 1 + n)
        p += 1 + n + 16
        files[name] = (size, index)
    return url, mask, meta, files


def getFile(url, mask, size, index):
    data = np.frombuffer(_range(url, index, index + size), np.uint8)
    i = np.arange(len(data))
    return (data ^ mask[i % 16] ^ (i & 0xFF).astype(np.uint8)).tobytes()


# ---------------------------------------------------------------- reading the notes

class TempoMap:
    def __init__(self, resolution, tempos):
        # tempos: [(tick, microseconds per beat)]
        tempos = sorted(dict(tempos).items()) or [(0, 500000)]
        if tempos[0][0] != 0:
            tempos.insert(0, (0, tempos[0][1]))
        self.res = float(resolution)
        self.ticks = np.array([t for t, _ in tempos], float)
        self.us = np.array([u for _, u in tempos], float)
        self.secs = np.concatenate([[0.0], np.cumsum(np.diff(self.ticks) / self.res * self.us[:-1] / 1e6)])

    def time(self, tick):
        tick = np.asarray(tick, float)
        i = np.clip(np.searchsorted(self.ticks, tick, 'right') - 1, 0, len(self.ticks) - 1)
        return self.secs[i] + (tick - self.ticks[i]) / self.res * self.us[i] / 1e6


def _notes(tm, raw, sustain=True):
    # [(tick, lane, length ticks)] -> [[seconds, lane, sustain seconds]]; short notes have no sustain
    out = []
    for tick, lane, length in sorted(raw):
        t0 = float(tm.time(tick))
        held = float(tm.time(tick + length)) - t0 if sustain and length >= tm.res / 2 else 0.0
        out.append([t0, lane, held])
    return out


def readMid(data):
    m = mido.MidiFile(file=io.BytesIO(data), clip=True)   # some charts have out-of-range bytes
    tempos, tracks = [], []
    for tr in m.tracks:
        tick, evs = 0, []
        for msg in tr:
            tick += msg.time
            evs.append((tick, msg))
            if msg.type == 'set_tempo':
                tempos.append((tick, msg.tempo))
        tracks.append(((tr.name or '').upper(), evs))
    tm = TempoMap(m.ticks_per_beat, tempos)
    parts = {'guitar': [], 'bass': [], 'keys': [], 'drums': []}
    sections, beatTrack = [], []
    for name, evs in tracks:
        on = {}
        for tick, msg in evs:
            if name == 'EVENTS' and msg.type in ('text', 'lyrics', 'marker'):
                s = re.match(r'\[(?:section|prc)[ _](.+)\]', msg.text)
                if s:
                    sections.append([round(float(tm.time(tick)), 3), s.group(1).replace('_', ' ')])
            if msg.type == 'note_on' and msg.velocity:
                on[msg.note] = tick
            elif msg.type in ('note_off', 'note_on') and msg.note in on:
                start, n = on.pop(msg.note), msg.note
                length = tick - start
                if name == 'BEAT' and n in (12, 13):
                    beatTrack.append(start)
                elif name == 'PART DRUMS' and 95 <= n <= 100:
                    parts['drums'].append((start, max(0, n - 96), 0))      # 95 is the second kick pedal
                elif name in ('PART GUITAR', 'PART BASS', 'PART KEYS') and 96 <= n <= 100:
                    parts[name.split()[1].lower()].append((start, n - 96, length))
                elif name in ('PART GUITAR GHL', 'PART BASS GHL') and 94 <= n <= 100:
                    # Six frets in two rows: fold onto five lanes; the open note (94) is lane -1
                    key = ('guitar' if 'GUITAR' in name else 'bass') + 'ghl'
                    parts.setdefault(key, []).append((start, -1 if n == 94 else min(4, n - 95), length))
    out = {'sections': sections}
    for key, raw in parts.items():
        if raw:
            out[key] = _notes(tm, raw, sustain=key != 'drums')
    return out


def readChart(data):
    text = data.decode('utf-8-sig', 'replace')
    blocks = dict(re.findall(r'\[(\w+)\]\s*\{(.*?)\}', text, re.S))
    song = blocks.get('Song', '')
    res = int(re.search(r'Resolution\s*=\s*(\d+)', song).group(1))
    tm = TempoMap(res, [(int(t), 6e10 / int(b)) for t, b in re.findall(r'(\d+)\s*=\s*B\s+(\d+)', blocks.get('SyncTrack', ''))
                        if int(b) > 0])
    offset = re.search(r'Offset\s*=\s*([-\d.]+)', song)
    out = {'sections': [[round(float(tm.time(int(t))), 3), s.strip()]
                        for t, s in re.findall(r'(\d+)\s*=\s*E\s+"?section ([^"\n]+)', blocks.get('Events', ''))],
           'chartOffset': float(offset.group(1)) if offset else 0.0}
    for key, dest in (('ExpertSingle', 'guitar'), ('ExpertDoubleBass', 'bass'), ('ExpertKeyboard', 'keys'),
                      ('ExpertDrums', 'drums'), ('ExpertGHLGuitar', 'guitarghl'), ('ExpertGHLBass', 'bassghl')):
        raw = []
        for t, fret, length in re.findall(r'(\d+)\s*=\s*N\s+(\d+)\s+(\d+)', blocks.get(key, '')):
            t, fret, length = int(t), int(fret), int(length)
            if dest == 'drums':
                if fret <= 5 or fret == 32:
                    raw.append((t, 0 if fret == 32 else min(fret, 4), 0))
            elif dest.endswith('ghl'):
                # .chart GHL frets: 0-2 white, 3-4 black 1-2, 7 open, 8 black 3
                lane = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 8: 4, 7: -1}.get(fret)
                if lane is not None:
                    raw.append((t, lane, length))
            elif fret <= 4 or fret == 7:
                raw.append((t, fret if fret <= 4 else -1, length))
        if raw:
            out[dest] = _notes(tm, raw, sustain=dest != 'drums')
    return out


# ---------------------------------------------------------------- lining up with our audio

def decode(data, ext):
    path = os.path.join(tempfile.gettempdir(), 'led-lights-chart-stem.' + ext)
    with open(path, 'wb') as f:
        f.write(data)
    try:
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                             capture_output=True, check=True).stdout
    finally:
        os.remove(path)
    return np.frombuffer(raw, np.float32).copy()


def chartAudio(url, mask, files):
    # The chart's audio: all its stems mixed (not the crowd, not the preview clip)
    mix = None
    for name, (size, index) in files.items():
        ext = name.rsplit('.', 1)[-1].lower()
        if ext not in ('opus', 'ogg', 'mp3', 'wav') or name.startswith(('preview', 'crowd')):
            continue
        y = decode(getFile(url, mask, size, index), ext)
        if mix is None:
            mix = y
        else:
            n = max(len(mix), len(y))
            mix = np.pad(mix, (0, n - len(mix))) + np.pad(y, (0, n - len(y)))
    return mix


def envelope(y):
    o = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, aggregate=np.median)
    return (o - o.mean()) / max(o.std(), 1e-9)


def mapping(ours, theirs):
    # Chart audio time -> our audio time, as ours = scale * chart + offset. First the overall offset
    # (the whole of both, slid past each other); then 15 s stretches of the chart's audio are each found
    # in ours near that offset, and one straight line is fitted through the ones that agree. Searching
    # only near the overall offset stops a chorus matching the chorus before it.
    # Returns (scale, offset, stretches that agree, stretches tried, first and last agreeing chart time).
    n = 1 << int(np.ceil(np.log2(len(ours) + len(theirs))))
    corr = np.fft.irfft(np.fft.rfft(ours, n) * np.conj(np.fft.rfft(theirs, n)), n)
    lag = int(np.argmax(corr))
    lag = lag - n if lag > n // 2 else lag          # samples: ours = theirs shifted by lag
    reach = 5 * RATE + int(0.02 * len(theirs))       # plus up to 2% speed difference
    pts = []
    for start in range(0, int(len(theirs) / RATE) - 15, 5):
        seg = theirs[start * RATE:(start + 15) * RATE]
        if seg.std() < 0.3:
            continue    # silence
        lo, hi = max(0, start * RATE + lag - reach), min(len(ours), start * RATE + lag + len(seg) + reach)
        if hi - lo <= len(seg):
            continue
        score = np.correlate(ours[lo:hi], seg, 'valid')
        pts.append((start + 7.5, (lo + int(np.argmax(score))) / RATE + 7.5))
    if len(pts) < 4:
        return None
    pts = np.array(pts)
    best = None
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            s = (pts[j, 1] - pts[i, 1]) / (pts[j, 0] - pts[i, 0])
            if abs(s - 1) > 0.02:
                continue
            inliers = np.abs(pts[:, 0] * s + pts[i, 1] - s * pts[i, 0] - pts[:, 1]) < 0.03
            if best is None or inliers.sum() > best.sum():
                best = inliers
    if best is None or best.sum() < 3:
        return None
    s, o = np.polyfit(pts[best, 0], pts[best, 1], 1)
    return float(s), float(o), int(best.sum()), len(pts), float(pts[best, 0].min() - 7.5), float(pts[best, 0].max() + 7.5)


# Harmony features for lining up the song's overall structure: 10 a second
FEAT_HOP = SR // 10


def harmony(y):
    c = librosa.feature.chroma_stft(y=y, sr=SR, hop_length=FEAT_HOP, n_fft=4096)
    return c / np.maximum(np.linalg.norm(c, axis=0, keepdims=True), 1e-9)


def piecewise(ours, theirs, oursHarmony, theirsHarmony):
    # For a different edit of the song than the chart's (a radio edit with parts cut out, say), where no
    # single offset fits. Rhythm alone can't do it: a dance track repeats the same bar so much that a
    # stretch of it matches many places equally well. So the two are first lined up as a whole by
    # their harmony (dynamic time warping, which allows for parts cut out of either), then each 15 s
    # stretch of ours is placed exactly by rhythm within half a second of where that puts it. Runs of
    # neighbouring stretches that agree become pieces, each lined up on its own.
    # Returns ([(scale, offset, our from, our to)], stretches in pieces, stretches tried) or None.
    D, path = librosa.sequence.dtw(X=oursHarmony, Y=theirsHarmony, metric='euclidean')
    path = path[::-1] / 10.0                 # (our time, chart time) pairs, in order
    width = 15 * RATE
    reach = RATE // 2
    pts = []
    for start in range(0, int(len(ours) / RATE) - 15, 5):
        seg = ours[start * RATE:start * RATE + width]
        if seg.std() < 0.3:
            continue    # silence
        near = np.abs(path[:, 0] - (start + 7.5)) < 0.5
        if not near.any():
            continue
        guess = int(round((np.median(path[near, 1]) - 7.5) * RATE))      # chart frame for this stretch
        lo, hi = max(0, guess - reach), min(len(theirs), guess + width + reach)
        if hi - lo <= width:
            continue
        score = np.correlate(theirs[lo:hi], seg, 'valid')
        pts.append((start + 7.5, (lo + int(np.argmax(score))) / RATE + 7.5))    # (our time, chart time)
    if len(pts) < 4:
        return None
    runs, run = [], [pts[0]]
    for prev, cur in zip(pts, pts[1:]):
        if cur[0] - prev[0] <= 10 and abs((cur[0] - cur[1]) - (prev[0] - prev[1])) < 0.04:
            run.append(cur)
        else:
            runs.append(run)
            run = [cur]
    runs.append(run)
    pieces = []
    for run in runs:
        if len(run) < 2:
            continue
        r = np.array(run)
        s, o = np.polyfit(r[:, 1], r[:, 0], 1) if len(run) >= 3 else (1.0, float(np.mean(r[:, 0] - r[:, 1])))
        if abs(s - 1) > 0.02:
            s, o = 1.0, float(np.mean(r[:, 0] - r[:, 1]))
        pieces.append([float(s), float(o), r[0, 0] - 7.5, r[-1, 0] + 7.5, len(run)])
    if not pieces:
        return None
    # Neighbouring pieces overlap by up to a stretch: split the overlap down the middle
    for a, b in zip(pieces, pieces[1:]):
        if a[3] > b[2]:
            a[3] = b[2] = (a[3] + b[2]) / 2
    return [tuple(p[:4]) for p in pieces], sum(p[4] for p in pieces), len(pts)


# ---------------------------------------------------------------- per song

def findChart(result, y, ourTitle, tries=4):
    # The analysis' 'chart': the best chart's notes in our audio's time, or None when there isn't one
    # that lines up. y: our audio (mono, SR).
    title, artist = result['title'], result['artist'].split(',')[0]
    title = re.sub(r'\s*[\(\[][^\)\]]*\b(feat|ft|with)\.?\s[^\)\]]*[\)\]]', '', title, flags=re.I)
    title = re.sub(r'\s+-\s+.*(remaster|version|edit|live|mix|mono|stereo).*$', '', title, flags=re.I).strip()
    ours = oursHarmony = None
    for c in candidates(title, artist, result['durationMs'], ourTitle)[:tries]:
        label = '%s - %s (charted by %s)' % (c.get('artist'), c.get('name'), c.get('charter'))
        try:
            url, mask, meta, files = readSng(c['md5'])
            notesFile = next((n for n in ('notes.mid', 'notes.chart') if n in files), None)
            if not notesFile:
                continue
            notes = (readMid if notesFile.endswith('.mid') else readChart)(getFile(url, mask, *files[notesFile]))
            if not any(k in notes for k in ('guitar', 'drums', 'keys', 'bass', 'guitarghl', 'bassghl')):
                continue
            if ours is None:
                ours = envelope(y)
            audio = chartAudio(url, mask, files)
            if audio is None:
                continue
            theirs = envelope(audio)
            delay = float(meta.get('delay') or 0) / 1000.0 + notes.pop('chartOffset', 0.0)
            # Pieces of the song, each (scale, offset, our from, our to): chart audio time c is our time
            # scale * c + offset between 'our from' and 'our to'. One piece when it's the same edit as ours.
            fit = mapping(ours, theirs)
            if fit and fit[2] >= max(8, 0.6 * fit[3]):
                scale, offset, agree, tried, first, last = fit
                pieces = [(scale, offset, scale * (first - 10) + offset, scale * (last + 10) + offset)]
                how = '%d/%d stretches agree, offset %+.2f s' % (agree, tried, offset + scale * delay)
            else:
                if oursHarmony is None:
                    oursHarmony = harmony(y)
                cut = piecewise(ours, theirs, oursHarmony, harmony(audio))
                if not cut or cut[1] < max(8, 0.6 * cut[2]):
                    log('  chart %s: does not line up with our audio (%s as one piece, %s in pieces)' % (
                        label, '%d/%d' % fit[2:4] if fit else '-', '%d/%d' % cut[1:] if cut else '-'))
                    continue
                pieces, agree, tried = cut
                how = 'a different edit: %d pieces, %d/%d stretches agree' % (len(pieces), agree, tried)
            out = {'md5': c['md5'], 'name': c.get('name'), 'artist': c.get('artist'), 'charter': c.get('charter'),
                   'pieces': [[round(s, 6), round(o + s * delay, 4), round(a, 3), round(b, 3)] for s, o, a, b in pieces],
                   'agree': '%d/%d' % (agree, tried)}
            # Notes only where the two audios were seen to line up (a chorus the chart has twice and our
            # edit has once comes through once)
            for key, events in notes.items():
                kept = []
                for s, o, a, b in pieces:
                    for e in events:
                        t = s * (e[0] + delay) + o
                        if a <= t < b:
                            kept.append([round(t, 3), e[1]] if key in ('sections', 'drums') else
                                        [round(t, 3), e[1], round(e[2] * s, 3)])
                if kept:
                    out[key] = sorted(kept, key=lambda n: n[0])
            log('  chart %s lines up (%s): %s' % (label, how, ', '.join(
                '%d %s' % (len(out[k]), k) for k in ('guitar', 'guitarghl', 'keys', 'bass', 'bassghl', 'drums') if k in out)))
            return out
        except Exception as e:
            log('  chart %s: failed (%r)' % (label, e))
    return None


def addChart(result, y, ourTitle=''):
    result['chart'] = findChart(result, y, ourTitle or result['title'])
    result['chartChecked'] = VERSION
    return result['chart']

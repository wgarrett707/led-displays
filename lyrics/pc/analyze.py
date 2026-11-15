# Song analysis for the LED lights: beats, bars, sections, drops and melody notes, worked out
# ahead of time on the PC and sent to the Pi, which lines them up with what Spotify is playing.
#
#   python analyze.py watch                 analyse songs the Pi has asked for, as they come in
#   python analyze.py track <Spotify link>  analyse particular songs now
#   python analyze.py playlist <link>       analyse a whole playlist ahead of a party
#   python analyze.py charts                look for note charts for songs analysed before charts.py
#
# Audio comes from YouTube (yt-dlp), matched to the Spotify track by title, artist and length.
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time

import librosa
import numpy as np
import requests
import yt_dlp

import charts

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(HERE, 'audio')
OUT_DIR = os.path.join(HERE, 'analysis')
PI = os.environ.get('LED_PI', 'pi@willpi')
PI_BEATS = '/home/pi/led-scripts/lyrics/beats'
VERSION = 3

SR = 22050
HOP = 256                 # ~11.6 ms analysis frames
ENV_RATE = 50             # Hz; the bass onset envelope the Pi matches against the microphone
DURATION_TOLERANCE = 2.0  # s; how far YouTube's length may be from Spotify's

# Uploads that are usually a different recording or edit than the album track
OTHER_VERSION = re.compile(r'\b(live|remix|sped|slowed|reverb|cover|karaoke|instrumental|8d|nightcore|'
                           r'acoustic|extended|mashup|loop|hours?|reaction|tutorial|lesson|mix)\b', re.I)


def log(message):
    print(time.strftime('%H:%M:%S ') + message, flush=True)


# ---------------------------------------------------------------- finding the audio

def _words(text):
    return re.sub(r'[^a-z0-9 ]', ' ', text.lower()).split()


def cleanTitle(title):
    # "Song (feat. X) - Remastered 2011" -> "Song"
    title = re.sub(r'\s*[\(\[][^\)\]]*\b(feat|ft|with|vs)\.?\s[^\)\]]*[\)\]]', '', title, flags=re.I)
    title = re.sub(r'\s+-\s+.*(remaster|version|edit|live|mix|mono|stereo).*$', '', title, flags=re.I)
    return title.strip()


def findAudio(track):
    # Best YouTube match for the track: same length, title words present; YouTube's
    # auto-generated "Artist - Topic" uploads are the album audio, so they're preferred
    title, artist = cleanTitle(track['title']), track['artists'][0]
    target = track['durationMs'] / 1000
    want = set(_words(title))
    best = None
    options = {'quiet': True, 'no_warnings': True, 'extract_flat': 'in_playlist', 'skip_download': True}
    with yt_dlp.YoutubeDL(options) as ydl:
        for query in ('%s %s topic' % (artist, title), '%s - %s audio' % (artist, title), '%s %s' % (artist, title)):
            for e in ydl.extract_info('ytsearch10:' + query, download=False).get('entries') or []:
                if not e or not e.get('duration') or not e.get('id'):
                    continue
                off = abs(e['duration'] - target)
                if off > DURATION_TOLERANCE:
                    continue
                name = e.get('title') or ''
                if not want <= set(_words(name)):
                    continue
                if OTHER_VERSION.search(name) and not OTHER_VERSION.search(track['title']):
                    continue
                channel = e.get('channel') or e.get('uploader') or ''
                score = -off + (3 if channel.endswith(' - Topic') else 0) + (1 if artist.lower() in channel.lower() else 0)
                if best is None or score > best[0]:
                    best = (score, {'youtubeId': e['id'], 'title': name, 'channel': channel, 'duration': e['duration']})
            if best and best[0] >= 2:
                break
    return best[1] if best else None


def download(source, trackId):
    os.makedirs(AUDIO_DIR, exist_ok=True)
    for f in os.listdir(AUDIO_DIR):
        if f.startswith(trackId + '.'):
            return os.path.join(AUDIO_DIR, f)
    options = {'quiet': True, 'no_warnings': True, 'noprogress': True, 'format': 'bestaudio/best',
               'outtmpl': os.path.join(AUDIO_DIR, trackId + '.%(ext)s')}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info('https://www.youtube.com/watch?v=' + source['youtubeId'], download=True)
    return ydl.prepare_filename(info)


def decode(path):
    # Mono float samples at SR, via ffmpeg (handles whatever format YouTube served)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def deezerBpm(track):
    # Deezer knows the tempo of many tracks (0 when it doesn't); used to settle double/half-time
    if not track.get('isrc'):
        return None
    try:
        bpm = requests.get('https://api.deezer.com/track/isrc:' + track['isrc'], timeout=10).json().get('bpm')
        return float(bpm) if bpm else None
    except Exception:
        return None


# ---------------------------------------------------------------- analysis

def _db(x):
    return 10 * np.log10(np.maximum(x, 1e-10))


def _norm(x, lo=5, hi=95):
    a, b = np.percentile(x, lo), np.percentile(x, hi)
    return np.clip((x - a) / max(b - a, 1e-9), 0, 1)


def _sync(data, starts):
    # Mean of per-frame data (last axis) from each start frame up to the next (the last runs to the end)
    data = np.asarray(data, float)
    n = data.shape[-1]
    starts = np.clip(np.asarray(starts, int), 0, n - 1)
    out = np.empty(data.shape[:-1] + (len(starts),))
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else n
        out[..., i] = data[..., a:max(b, a + 1)].mean(-1)
    return out


# Without a tempo from Deezer, a tempo below this is taken to be half the felt beat (a 132 BPM song
# counted at 66) and tracked again at double
SLOW = 78


def beatGrid(y, bpmHint):
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, aggregate=np.median)

    def track(start, tightness):
        tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=SR, hop_length=HOP, start_bpm=start,
                                               tightness=tightness, trim=False, units='time')
        return float(np.atleast_1d(tempo)[0]), np.asarray(beats, float)

    tempo, beats = track(bpmHint or 120.0, 300 if bpmHint else 100)
    if not bpmHint and tempo < SLOW:
        fast, fastBeats = track(tempo * 2, 100)
        if fast > 1.6 * tempo:
            tempo, beats = fast, fastBeats
    if len(beats) < 8:
        raise ValueError('no steady beat found')
    # Most songs are recorded to a click: one exact tempo all the way through. The tracker above finds
    # the beat well but now and then slips onto the off-beat for a stretch (in a breakdown, say), so
    # when the song is steady its beats come from one steady grid instead.
    period = float(np.polyfit(np.arange(len(beats)), beats, 1)[0])
    fit = steadyGrid(y, period, onset=onset)
    if fit['steady'] >= STEADY:
        return fit['beats'], 60.0 / fit['period'], 0, fit
    grid, tempo, first = extendGrid(beats, len(y) / SR)
    return grid, tempo, first, fit


# Share of the song that must sit on one steady grid for it to be used
STEADY = 0.8
# Below this (onsets on the beat / on the off-beat), the grid may be on the off-beat: worth a listen
SURE = 1.25


def steadyGrid(y, period, spread=0.02, near=None, onset=None):
    # One exact tempo and beat position for the whole song.
    #  Tempo: of every period within 'spread' of 'period', the one whose beat lines (and half-beat
    #  lines, so stretches with the sound on the off-beat still count) catch the most onset energy.
    #  Position: all the onsets folded onto a single beat; the beat is where they pile up most (hits
    #  across the whole spectrum, kick and snare, rather than a bassline or hi-hats on the off-beat).
    #  'near' (seconds) keeps it within a quarter beat of a position the user tapped.
    # Returns beats, period, 'steady' (the share of 16-beat stretches that sit on the grid) and 'sure'
    # (how much more piles up on the beat than on the off-beat; near 1 means it could be either).
    if onset is None:
        onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP, aggregate=np.median)
    n = len(onset)
    t = np.arange(n) * HOP / SR
    duration = len(y) / SR
    o = onset - onset.mean()

    def score(p):
        return abs(np.sum(o * np.exp(2j * np.pi * t / p))) + abs(np.sum(o * np.exp(4j * np.pi * t / p)))

    step = period * period / max(t[-1], 1.0) / 30
    cands = np.arange(period * (1 - spread), period * (1 + spread) + step, step)
    p = cands[int(np.argmax([score(c) for c in cands]))]
    for fine in (step / 5, step / 25):
        cands = p + fine * np.arange(-6, 7)
        p = cands[int(np.argmax([score(c) for c in cands]))]

    # Where in the beat the hits land (5 ms bins, lightly smoothed)
    weight = np.maximum(onset - np.median(onset), 0)
    bins = max(8, int(round(p / 0.005)))
    hist = np.bincount((((t / p) % 1.0) * bins).astype(int) % bins, weights=weight, minlength=bins)
    hist = np.convolve(np.concatenate([hist[-2:], hist, hist[:2]]), [1, 2, 3, 2, 1], 'valid')
    plain = hist.copy()
    if near is not None:
        dist = np.abs(((np.arange(bins) + 0.5) / bins - (near / p) % 1.0 + 0.5) % 1.0 - 0.5)
        hist = np.where(dist <= 0.25, hist, -1)
    k = int(np.argmax(hist))
    left, mid, right = hist[k - 1], hist[k], hist[(k + 1) % bins]
    shift = 0.5 * (left - right) / (left - 2 * mid + right) if (left - 2 * mid + right) < 0 else 0.0
    a = ((k + 0.5 + shift) / bins * p) % p
    opposite = plain[(k + bins // 2 - 2):(k + bins // 2 + 3)].max() if k + bins // 2 + 3 <= bins else         np.concatenate([plain, plain])[(k + bins // 2 - 2):(k + bins // 2 + 3)].max()
    sure = float(plain[k] / max(opposite, 1e-9))

    # How much of the song sits on this grid (beat or off-beat), 16 beats at a time
    win = max(8, int(16 * p * SR / HOP))
    whole = np.sum(o * np.exp(4j * np.pi * (t - a) / p))
    on = []
    for start in range(0, n - win + 1, win // 2):
        part = np.sum(o[start:start + win] * np.exp(4j * np.pi * (t[start:start + win] - a) / p))
        if abs(part) > 0.2 * abs(whole) * win / n:
            on.append(abs(np.angle(part / whole)) / (4 * np.pi) * p < 0.035)
    beats = a + p * np.arange(int(np.ceil(-a / p)), int(np.floor((duration - a) / p)) + 1)
    return {'beats': beats, 'period': float(p), 'steady': float(np.mean(on)) if on else 0.0, 'sure': sure}


def extendGrid(beats, duration):
    # Extend a beat grid to the whole song at its median spacing, so the clock always has a beat.
    # Returns (beats, tempo, index of the first original beat)
    beats = np.asarray(beats, float)
    period = float(np.median(np.diff(beats)))
    before = np.arange(beats[0] - period, -period / 2, -period)[::-1]
    after = np.arange(beats[-1] + period, duration + period / 2, period)
    before = before[before >= 0]
    return np.concatenate([before, beats, after[after <= duration]]), 60.0 / period, len(before)


def beatFeatures(y, beats, harmonic=None):
    # Per-beat loudness and bass (0..1), and the melody note on each half beat (-1 when unclear).
    # Separate from analyze() so the editor can redo them for a corrected beat grid.
    beats = np.asarray(beats, float)
    beatFrames = librosa.time_to_frames(beats, sr=SR, hop_length=HOP)
    mel = librosa.feature.melspectrogram(y=y, sr=SR, hop_length=HOP, n_mels=64, fmax=8000)
    melFreqs = librosa.mel_frequencies(n_mels=64, fmax=8000)
    if harmonic is None:
        # Separating out the drums takes most of a minute; the editor goes without (notes a bit noisier)
        harmonic = y
    lead = librosa.feature.chroma_cqt(y=harmonic, sr=SR, hop_length=HOP, fmin=librosa.note_to_hz('C4'), n_octaves=3)
    halves = np.sort(np.concatenate([beats, (beats[:-1] + beats[1:]) / 2]))
    leadSync = _sync(lead, librosa.time_to_frames(halves, sr=SR, hop_length=HOP))
    clarity = leadSync.max(0) / np.maximum(leadSync.sum(0), 1e-9)
    notes = np.where(clarity > 0.16, leadSync.argmax(0), -1)
    return {'beatEnergy': [round(float(v), 2) for v in _norm(_sync(_db(mel.sum(0)), beatFrames))],
            'beatBass': [round(float(v), 2) for v in _norm(_sync(_db(mel[melFreqs < 160].sum(0)), beatFrames))],
            'notes': [int(n) for n in notes]}


def analyze(y, bpmHint=None):
    duration = len(y) / SR
    beats, tempo, firstReal, fit = beatGrid(y, bpmHint)
    beatFrames = librosa.time_to_frames(beats, sr=SR, hop_length=HOP)
    harmonic, percussive = librosa.effects.hpss(y)

    # Loudness and bass per frame
    mel = librosa.feature.melspectrogram(y=y, sr=SR, hop_length=HOP, n_mels=64, fmax=8000)
    melFreqs = librosa.mel_frequencies(n_mels=64, fmax=8000)
    loud = _db(mel.sum(0))
    bass = _db(mel[melFreqs < 160].sum(0))
    bassOnset = librosa.onset.onset_strength(S=librosa.power_to_db(mel[melFreqs < 160]), sr=SR, hop_length=HOP)

    beatKick = np.array([bassOnset[max(0, f - 2):f + 3].max() if f < len(bassOnset) else 0 for f in beatFrames])

    # Chords (for bar lines and sections) and the upper register (melody notes)
    chroma = librosa.feature.chroma_cqt(y=harmonic, sr=SR, hop_length=HOP)
    beatChroma = _sync(chroma, beatFrames)
    change = np.zeros(len(beats))
    unit = beatChroma / np.maximum(np.linalg.norm(beatChroma, axis=0), 1e-9)
    change[1:] = 1 - (unit[:, 1:] * unit[:, :-1]).sum(0)

    # Bar 1 of each bar: the phase (of 4) where kicks and chord changes land most
    def z(v):
        return (v - v.mean()) / max(v.std(), 1e-9)
    kz, cz = z(beatKick), z(change)
    phase = int(np.argmax([kz[p::4].mean() + cz[p::4].mean() for p in range(4)]))
    bars = np.arange(phase, len(beats), 4)
    barTimes = beats[bars]

    # Per bar: loudness, bass, and features for finding sections
    barFrames = beatFrames[bars]
    barLoud = _sync(loud, barFrames)
    barBass = _sync(bass, barFrames)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(mel), n_mfcc=13)
    feats = np.vstack([_sync(chroma, barFrames), _sync(mfcc, barFrames)[1:] / 40.0])

    sections = findSections(feats, barLoud, barTimes, duration)
    drops, lifts = findDrops(barTimes, barLoud, barBass, sections, beats, loud)

    # Bass onset envelope at ENV_RATE for lining up with the live microphone
    envHop = SR // ENV_RATE
    envMel = librosa.feature.melspectrogram(y=y, sr=SR, hop_length=envHop, n_mels=24, fmin=30, fmax=250)
    env = librosa.onset.onset_strength(S=librosa.power_to_db(envMel), sr=SR, hop_length=envHop)
    env = np.round(_norm(env, 1, 99.5) * 255).astype(np.uint8)

    result = {
        'tempo': round(tempo, 2),
        'beats': [round(float(t), 3) for t in beats],
        'firstBeat': int(firstReal),
        'steady': round(fit['steady'], 2),
        'offbeatRisk': fit['steady'] >= STEADY and fit['sure'] < SURE,
        'downbeat': phase,
        'sections': sections,
        'drops': drops,
        'lifts': lifts,
        'envRate': ENV_RATE,
        'env': base64.b64encode(env.tobytes()).decode(),
    }
    result.update(beatFeatures(y, beats, harmonic))
    return result


def findSections(feats, barLoud, barTimes, duration):
    # Boundaries where the music changes character (checkerboard novelty on the bar-by-bar
    # self-similarity), snapped to 4-bar phrases; then sections that sound alike share a label
    n = feats.shape[1]
    unit = feats / np.maximum(np.linalg.norm(feats, axis=0), 1e-9)
    ssm = unit.T @ unit
    half = 4
    kernel = np.kron(np.array([[1, -1], [-1, 1]]), np.ones((half, half)))
    novelty = np.zeros(n)
    for i in range(half, n - half):
        novelty[i] = (ssm[i - half:i + half, i - half:i + half] * kernel).sum()
    novelty = np.maximum(novelty, 0)
    cuts = [0]
    threshold = np.percentile(novelty, 75) if n > 8 else np.inf
    for i in np.argsort(-novelty):
        if novelty[i] < threshold:
            break
        snapped = int(round(i / 4) * 4) if abs(i - round(i / 4) * 4) <= 1 else int(i)
        if all(abs(snapped - c) >= 4 for c in cuts) and 0 < snapped < n:
            cuts.append(snapped)
    cuts = sorted(cuts) + [n]

    # Label by similarity of average features (cosine), greedily in order of appearance
    segs, labels, centroids = [], [], []
    for a, b in zip(cuts[:-1], cuts[1:]):
        v = feats[:, a:b].mean(1)
        v = v / max(np.linalg.norm(v), 1e-9)
        match = None
        for k, c in enumerate(centroids):
            if float(v @ c) > 0.985:
                match = k
                break
        if match is None:
            centroids.append(v)
            match = len(centroids) - 1
        labels.append(match)
        segs.append((a, b))
    loudNorm = _norm(barLoud)
    out = []
    for (a, b), k in zip(segs, labels):
        out.append({'start': round(float(barTimes[a]), 3),
                    'end': round(float(barTimes[b]) if b < len(barTimes) else duration, 3),
                    'label': chr(65 + k % 26), 'energy': round(float(loudNorm[a:b].mean()), 2)})
    # The chorus: the loudest label that comes back
    counts = {}
    for s in out:
        counts.setdefault(s['label'], []).append(s['energy'])
    repeated = {k: np.mean(v) for k, v in counts.items() if len(v) >= 2}
    chorus = max(repeated, key=repeated.get) if repeated else None
    for s in out:
        s['chorus'] = s['label'] == chorus
    return out


def findDrops(barTimes, barLoud, barBass, sections, beats, loud):
    # A drop: the bass comes in hard on a bar line after a quieter stretch (often a build or a gap),
    # landing in one of the song's loud parts. Smaller jumps into a loud part are 'lifts'.
    n = len(barTimes)
    loudHigh = np.percentile(barLoud, 60)
    bassHigh = np.percentile(barBass, 60)
    scored = []
    for b in range(4, n - 2):
        pre = barBass[max(0, b - 8):b - 1].mean()          # the stretch before, minus the last bar
        gapBar = barBass[b - 1]
        post = barBass[b:b + 4].mean()
        if post < bassHigh or barLoud[b:b + 4].mean() < loudHigh:
            continue
        jump = post - max(pre, gapBar)
        gap = post - gapBar
        score = max(jump, 0.7 * gap)
        if score >= 4:
            scored.append((score, b))
    drops, lifts, taken = [], [], []
    for score, b in sorted(scored, reverse=True):
        if any(abs(b - t) < 8 for t in taken):
            continue
        taken.append(b)
        start = barTimes[max(0, b - 8)]
        for s in sections:
            if s['start'] < barTimes[b] and s['start'] >= start:
                start = s['start']    # the build runs from where the section before the drop began
        entry = {'time': round(float(barTimes[b]), 3), 'strength': round(float(score), 1),
                 'buildStart': round(float(start), 3)}
        (drops if score >= 8 else lifts).append(entry)
    return sorted(drops, key=lambda d: d['time']), sorted(lifts, key=lambda d: d['time'])


# ---------------------------------------------------------------- per track

def analyzeTrack(track, force=False):
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, track['id'] + '.json')
    if os.path.exists(out) and not force:
        with open(out) as f:
            result = json.load(f)
        # Hand-edited songs (editor.py) are never replaced by a fresh analysis
        if result.get('version') == VERSION or result.get('edited'):
            return result
    name = '%s - %s' % (track['artists'][0], track['title'])
    started = time.time()
    result = {'version': VERSION, 'id': track['id'], 'title': track['title'], 'artist': ', '.join(track['artists']),
              'durationMs': track['durationMs'], 'isrc': track.get('isrc')}
    source = findAudio(track)
    if not source:
        log('%s: no YouTube upload of the same length' % name)
        result['error'] = 'no matching audio'
    else:
        y = decode(download(source, track['id']))
        bpm = deezerBpm(track)
        result.update(source=source, bpmHint=bpm, offset=0.0)
        result.update(analyze(y, bpm))
        findChart(result, y)
        log('%s: %.1f BPM%s, %s, %d sections (%s), drops at %s, lifts at %s (%.0f s)' % (
            name, result['tempo'], ' (Deezer %.1f)' % bpm if bpm else '',
            ('steady tempo' + (' (beat vs off-beat unclear: check it in the editor)' if result['offbeatRisk'] else ''))
            if result['steady'] >= STEADY else 'tempo varies (%.0f%% steady), following the beat' % (100 * result['steady']),
            len(result['sections']),
            ''.join(s['label'] for s in result['sections']),
            [_mmss(d['time']) for d in result['drops']] or 'none', [_mmss(d['time']) for d in result['lifts']] or 'none',
            time.time() - started))
    with open(out + '.tmp', 'w') as f:
        json.dump(result, f, separators=(',', ':'))
    os.replace(out + '.tmp', out)
    return result


def findChart(result, y):
    # The guitar / drums / keys notes from a Clone Hero chart of the song, if there's one that lines up
    try:
        charts.addChart(result, y)
    except Exception as e:
        log('  chart lookup failed: %r' % e)


def addCharts(force=False):
    # Charts for songs analysed before (edited ones too: a chart doesn't change any edits)
    for name in sorted(os.listdir(OUT_DIR)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(OUT_DIR, name)
        with open(path) as f:
            result = json.load(f)
        if result.get('error') or (result.get('chartChecked') == charts.VERSION and not force):
            continue
        audio = [f for f in os.listdir(AUDIO_DIR) if f.startswith(result['id'] + '.')]
        if not audio:
            continue
        log('%s - %s' % (result['artist'], result['title']))
        findChart(result, decode(os.path.join(AUDIO_DIR, audio[0])))
        if result.get('chartChecked') != charts.VERSION:
            continue
        with open(path + '.tmp', 'w') as f:
            json.dump(result, f, separators=(',', ':'))
        os.replace(path + '.tmp', path)
        try:
            sendToPi(result)
        except Exception as e:
            log('  could not send to the Pi: %r' % e)


def _mmss(t):
    return '%d:%04.1f' % (t // 60, t % 60)


# ---------------------------------------------------------------- talking to the Pi and Spotify

def ssh(command, data=None):
    return subprocess.run(['ssh', '-o', 'ConnectTimeout=10', PI, command], input=data,
                          capture_output=True, check=True).stdout


def sendToPi(result):
    ssh('mkdir -p %s && cat > %s/%s.json.tmp && mv %s/%s.json.tmp %s/%s.json && rm -f %s/pending/%s.json' % (
        PI_BEATS, PI_BEATS, result['id'], PI_BEATS, result['id'], PI_BEATS, result['id'], PI_BEATS, result['id']),
        json.dumps(result, separators=(',', ':')).encode())


def spotifySession():
    # App-only Spotify access (client credentials), using the keys stored on the Pi
    keys = json.loads(ssh('cat /home/pi/led-scripts/apikeys.json'))
    r = requests.post('https://accounts.spotify.com/api/token', data={'grant_type': 'client_credentials'},
                      auth=(keys['spotify_client_id'], keys['spotify_client_secret']), timeout=10)
    r.raise_for_status()
    s = requests.Session()
    s.headers['Authorization'] = 'Bearer ' + r.json()['access_token']
    return s


def userSession():
    # Spotify access as the Pi's logged-in user. Spotify only lists a playlist's songs to a signed-in
    # user, not to the app on its own. The token comes from the Pi's own Spotify code, so if Spotify
    # hands out a new login token it's saved where the lyrics display looks for it.
    token = ssh('cd /home/pi/led-scripts/lyrics && /usr/local/bin/python3 -c "import json, spotify; '
                's = spotify.Spotify(json.load(open(\'/home/pi/led-scripts/apikeys.json\'))); s._refresh(); '
                'print(s.accessToken)"').decode().strip()
    s = requests.Session()
    s.headers['Authorization'] = 'Bearer ' + token
    return s


def linkTracks(text):
    # Every song in the Spotify track / album / playlist links in 'text'
    app, user = spotifySession(), None
    tracks = []
    for kind, sid in re.findall(r'(track|album|playlist)[/:]([A-Za-z0-9]{22})', text):
        if kind == 'track':
            tracks.append(trackInfo(app.get('https://api.spotify.com/v1/tracks/' + sid, timeout=10).json()))
            continue
        if kind == 'playlist':
            user = user or userSession()
            s, url = user, 'https://api.spotify.com/v1/playlists/%s/items?limit=50' % sid
        else:
            s, url = app, 'https://api.spotify.com/v1/albums/%s/tracks?limit=50' % sid
        while url:
            page = s.get(url, timeout=10).json()
            if 'error' in page:
                message = page['error'].get('message', page['error']) if isinstance(page['error'], dict) else page['error']
                raise RuntimeError('Spotify %s %s: %s' % (kind, sid, message))
            for entry in page['items']:
                item = entry.get('item') or entry.get('track') or entry
                if kind == 'album':
                    item = app.get('https://api.spotify.com/v1/tracks/' + item['id'], timeout=10).json()
                if item and item.get('id') and item.get('type') == 'track':
                    tracks.append(trackInfo(item))
            url = page.get('next')
    return tracks


def trackInfo(item):
    return {'id': item['id'], 'title': item['name'], 'artists': [a['name'] for a in item['artists']],
            'album': item['album']['name'], 'durationMs': item['duration_ms'],
            'isrc': item.get('external_ids', {}).get('isrc')}


def spotifyId(link):
    m = re.search(r'(?:track|playlist|album)[/:]([A-Za-z0-9]{22})', link)
    return m.group(1) if m else link


def run(tracks, push=True):
    for track in tracks:
        try:
            result = analyzeTrack(track)
            if push:
                sendToPi(result)
        except Exception as e:
            log('%s - %s: failed: %r' % (track['artists'][0], track['title'], e))


def watch():
    # Songs the Pi played without an analysis wait in beats/pending/ until this picks them up
    log('Watching %s for songs to analyse (Ctrl+C to stop)' % PI)
    while True:
        try:
            listing = ssh('mkdir -p %s/pending && cat %s/pending/*.json 2>/dev/null | head -c 1000000; true' % (PI_BEATS, PI_BEATS))
            tracks = [json.loads(line) for line in listing.decode().splitlines() if line.strip()]
            run(tracks)
        except Exception as e:
            log('Pi not reachable: %r' % e)
        time.sleep(15)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['watch', 'track', 'playlist', 'album', 'charts'])
    p.add_argument('links', nargs='*')
    p.add_argument('--no-push', action='store_true', help="analyse only; don't send to the Pi")
    p.add_argument('--force', action='store_true', help='charts: look again for songs already checked')
    a = p.parse_args()
    if a.mode == 'watch':
        return watch()
    if a.mode == 'charts':
        return addCharts(a.force)
    tracks = linkTracks(' '.join(a.links))
    log('%d track(s)' % len(tracks))
    run(tracks, push=not a.no_push)


if __name__ == '__main__':
    main()

# LED lights editor: check and fix a song's beat grid, bar lines, drops and sections by ear, and pick
# how each section looks on the strips. Runs on the PC (the audio and analyses live here) and opens
# in the browser; Save sends the song to the Pi, which picks it up within seconds, even mid-song.
#   editor.bat   (or: .venv\Scripts\python editor.py)
import glob
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser

import numpy as np

import analyze

PORT = 8777
PAGE = os.path.join(analyze.HERE, 'editor.html')
PEAKS_DIR = os.path.join(analyze.HERE, 'peaks')
PEAKS_RATE = 100          # waveform points per second
LOG = []                  # recent messages, shown in the page
ONSETS = {}               # song id -> (audio, onset strength), for steady-grid fits


def note(message):
    analyze.log(message)
    LOG.append(time.strftime('%H:%M:%S ') + message)
    del LOG[:-50]


def analysisPath(trackId):
    if not re.fullmatch(r'[A-Za-z0-9]{10,40}', trackId):
        raise ValueError('bad id')
    return os.path.join(analyze.OUT_DIR, trackId + '.json')


def audioPath(trackId):
    analysisPath(trackId)
    found = glob.glob(os.path.join(analyze.AUDIO_DIR, trackId + '.*'))
    return found[0] if found else None


def songs():
    out = []
    for path in glob.glob(os.path.join(analyze.OUT_DIR, '*.json')):
        with open(path) as f:
            r = json.load(f)
        out.append({'id': r['id'], 'title': r['title'], 'artist': r['artist'], 'tempo': r.get('tempo'),
                    'edited': bool(r.get('edited')), 'error': r.get('error'), 'drops': len(r.get('drops', []))})
    return sorted(out, key=lambda s: (s['artist'].lower(), s['title'].lower()))


def peaks(trackId):
    # Waveform outline: the loudest sample in each 1/PEAKS_RATE s (cached)
    os.makedirs(PEAKS_DIR, exist_ok=True)
    cache = os.path.join(PEAKS_DIR, trackId + '.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    y = analyze.decode(audioPath(trackId))
    step = analyze.SR // PEAKS_RATE
    n = len(y) // step
    values = np.abs(y[:n * step]).reshape(n, step).max(1)
    values = values / max(float(values.max()), 1e-9)
    out = [round(float(v), 3) for v in values]
    with open(cache, 'w') as f:
        json.dump(out, f)
    return out


def save(trackId, edit):
    # Apply the page's changes to the stored analysis, redoing per-beat data if the grid changed
    path = analysisPath(trackId)
    with open(path) as f:
        r = json.load(f)
    beats = [float(b) for b in edit['beats']]
    if len(beats) < 8 or any(b2 <= b1 for b1, b2 in zip(beats, beats[1:])):
        raise ValueError('the beat grid must have at least 8 beats in order')
    if [round(b, 3) for b in beats] != r['beats']:
        note('%s: beat grid changed, measuring the new beats...' % r['title'])
        y = analyze.decode(audioPath(trackId))
        r.update(analyze.beatFeatures(y, beats))
        r['beats'] = [round(b, 3) for b in beats]
        r['tempo'] = round(60.0 / float(np.median(np.diff(beats))), 2)
    r['downbeat'] = int(edit['downbeat']) % 4
    duration = r['durationMs'] / 1000.0
    sections = sorted(edit['sections'], key=lambda s: s['start'])
    energy = np.array(r['beatEnergy'])
    times = np.array(r['beats'])
    for i, s in enumerate(sections):
        s['start'] = round(float(s['start']), 3)
        s['end'] = round(float(sections[i + 1]['start']) if i + 1 < len(sections) else duration, 3)
        inside = (times >= s['start']) & (times < s['end'])
        s['energy'] = round(float(energy[inside].mean()), 2) if inside.any() else 0.0
        s['chorus'] = bool(s.get('chorus'))
        for key in ('pattern', 'hues'):
            if not s.get(key):
                s.pop(key, None)
    r['sections'] = sections
    def drop(d):
        out = {'time': round(float(d['time']), 3), 'strength': float(d.get('strength', 10)),
               'buildStart': round(float(d['buildStart']), 3)}
        # Build-up speeds from the editor: [beats before the drop, pulses per beat], and whether it speeds up smoothly
        if d.get('stages'):
            out['stages'] = sorted([[round(float(b), 3), float(rate)] for b, rate in d['stages']], reverse=True)
        if d.get('smooth'):
            out['smooth'] = True
        # How the drop hits: 'flash' = one white flash; otherwise a white hit, then a short strobe
        if d.get('style') == 'flash':
            out['style'] = 'flash'
        return out
    r['drops'] = sorted([drop(d) for d in edit['drops']], key=lambda d: d['time'])
    r['lifts'] = sorted([{'time': round(float(d['time']), 3), 'strength': float(d.get('strength', 5)),
                          'buildStart': round(float(d.get('buildStart', d['time'])), 3)} for d in edit['lifts']],
                        key=lambda d: d['time'])
    chart = edit.get('chart')
    if chart and r.get('chart') and chart.get('part'):
        # Chart notes with some removed in the editor
        lead = [[round(float(t), 3), int(lane), round(float(held), 3)] for t, lane, held in chart['lead']]
        drums = [[round(float(t), 3), int(lane)] for t, lane in chart['drums']]
        if lead != r['chart'].get(chart['part']) or drums != (r['chart'].get('drums') or []):
            removed = len(r['chart'].get(chart['part']) or []) - len(lead) + len(r['chart'].get('drums') or []) - len(drums)
            note('%s: %d chart note(s) removed' % (r['title'], removed))
            r['chart'][chart['part']] = sorted(lead)
            r['chart']['drums'] = sorted(drums)
            r['chartEdited'] = True
    # Strip effects marked in the editor: fade-outs and 'balls', each from 'time' to 'end'
    r['effects'] = sorted([{'type': e['type'], 'time': round(float(e['time']), 3), 'end': round(float(e['end']), 3)}
                           for e in edit.get('effects') or []
                           if e.get('type') in ('fadeout', 'balls') and float(e['end']) > float(e['time'])],
                          key=lambda e: e['time'])
    r['edited'] = True
    r['editedAt'] = time.strftime('%Y-%m-%d %H:%M')
    with open(path + '.tmp', 'w') as f:
        json.dump(r, f, separators=(',', ':'))
    os.replace(path + '.tmp', path)
    try:
        analyze.sendToPi(r)
        note('%s: saved and sent to the Pi' % r['title'])
        sent = True
    except Exception as e:
        note('%s: saved, but the Pi could not be reached (%r); it will be sent next time' % (r['title'], e))
        sent = False
    return {'ok': True, 'sent': sent, 'song': r}


def steady(trackId, req):
    # A steady grid fitted to the song's audio near a tempo (and beat position) from the page
    if trackId not in ONSETS:
        y = analyze.decode(audioPath(trackId))
        ONSETS.clear()
        ONSETS[trackId] = (y, analyze.librosa.onset.onset_strength(y=y, sr=analyze.SR, hop_length=analyze.HOP,
                                                                   aggregate=np.median))
    y, onset = ONSETS[trackId]
    period = 60.0 / float(req['bpm'])
    spread = min(0.03, max(0.003, float(req.get('spread', 0.02))))
    fit = analyze.steadyGrid(y, period, spread=spread, near=req.get('near'), onset=onset)
    return {'beats': [round(float(b), 4) for b in fit['beats']], 'bpm': 60.0 / fit['period'],
            'steady': fit['steady'], 'sure': fit['sure']}


def analyzeLinks(text):
    # Spotify track / album / playlist links, analysed in the background
    def work():
        try:
            tracks = analyze.linkTracks(text)
            note('Analysing %d song(s)...' % len(tracks))
            for i, track in enumerate(tracks):
                try:
                    r = analyze.analyzeTrack(track)
                    analyze.sendToPi(r)
                    note('(%d/%d) %s - %s: %s' % (i + 1, len(tracks), track['artists'][0], track['title'],
                                                  r.get('error') or '%.1f BPM' % r['tempo']))
                except Exception as e:
                    note('(%d/%d) %s: failed (%r)' % (i + 1, len(tracks), track['title'], e))
            note('Done.')
        except Exception as e:
            note('Analysis failed: %r' % e)
    threading.Thread(target=work, daemon=True).start()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, body, kind='application/json', status=200):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        try:
            if url.path == '/':
                with open(PAGE, 'rb') as f:
                    return self.reply(f.read(), 'text/html; charset=utf-8')
            if url.path == '/api/songs':
                return self.reply(songs())
            if url.path == '/api/song':
                with open(analysisPath(q['id'])) as f:
                    r = json.load(f)
                r.pop('env', None)
                r['peaks'], r['peaksRate'] = (peaks(q['id']), PEAKS_RATE) if audioPath(q['id']) else ([], PEAKS_RATE)
                return self.reply(r)
            if url.path == '/api/log':
                return self.reply(LOG[-12:])
            if url.path == '/audio':
                path = audioPath(q['id'])
                if not path:
                    return self.reply({'error': 'no audio'}, status=404)
                with open(path, 'rb') as f:
                    return self.reply(f.read(), 'audio/webm' if path.endswith('.webm') else 'audio/mp4')
            self.reply({'error': 'not found'}, status=404)
        except Exception as e:
            self.reply({'error': repr(e)}, status=500)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            if url.path == '/api/save':
                return self.reply(save(q['id'], body))
            if url.path == '/api/steady':
                return self.reply(steady(q['id'], body))
            if url.path == '/api/analyze':
                analyzeLinks(body.get('links', ''))
                return self.reply({'ok': True})
            self.reply({'error': 'not found'}, status=404)
        except Exception as e:
            note('Error: %r' % e)
            self.reply({'error': str(e)}, status=400)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    server = Server(('127.0.0.1', PORT), Handler)
    url = 'http://127.0.0.1:%d/' % PORT
    note('Editor running at %s (close this window to stop it)' % url)
    if '--no-browser' not in sys.argv:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == '__main__':
    main()

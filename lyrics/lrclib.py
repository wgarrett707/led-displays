# Synced lyrics from LRCLib (https://lrclib.net), cached per Spotify track.
import json
import os
import re
import time
import requests

API = 'https://lrclib.net/api'
HEADERS = {'User-Agent': 'led-lyrics/1.0 (https://github.com/wgarrett707/led-displays)'}
CACHE_DIR = '/home/pi/led-scripts/lyrics/cache'
# Songs with no synced lyrics are looked up again after this long, in case someone adds them
NOT_FOUND_RETRY = 24 * 3600
# How far LRCLib's track length may be from Spotify's and still count as the same recording
DURATION_TOLERANCE = 3

TIMESTAMP = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\]')


def parseLrc(text):
    # "[mm:ss.xx] words" lines -> sorted [(ms, words)]. A line can carry several timestamps.
    lines = []
    for raw in text.splitlines():
        stamps = []
        pos = 0
        while True:
            m = TIMESTAMP.match(raw, pos)
            if not m:
                break
            stamps.append(int((int(m.group(1)) * 60 + float(m.group(2))) * 1000))
            pos = m.end()
        words = raw[pos:].strip()
        for ms in stamps:
            lines.append((ms, words))
    lines.sort(key=lambda l: l[0])
    return lines


def cleanTitle(title):
    # "Song (feat. X) - Remastered 2011" -> "Song", for fuzzier searches
    title = re.sub(r'\s*[\(\[](feat|ft|with)\.?\s[^\)\]]*[\)\]]', '', title, flags=re.I)
    title = re.sub(r'\s+-\s+.*(remaster|version|edit|live|mix|mono|stereo).*$', '', title, flags=re.I)
    return title.strip()


# Songs whose lookup hit a temporary LRCLib error are tried again after this long
TRANSIENT_RETRY = 600


def _get(path, params):
    r = requests.get(API + path, params=params, headers=HEADERS, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _isTransient(error):
    # Timeouts, connection drops and 5xx ("ServerOverloaded") are worth retrying later
    if isinstance(error, requests.HTTPError):
        return error.response is not None and error.response.status_code >= 500
    return isinstance(error, requests.RequestException)


def _pickFromSearch(results, durationS):
    # Closest-length result that has synced lyrics, within tolerance
    best = None
    for r in results or []:
        if not r.get('syncedLyrics') or r.get('duration') is None:
            continue
        diff = abs(r['duration'] - durationS)
        if diff <= DURATION_TOLERANCE and (best is None or diff < best[0]):
            best = (diff, r)
    return best[1] if best else None


def _lookup(track):
    durationS = round(track.durationMs / 1000)
    artist = track.artists[0]
    title = cleanTitle(track.title)
    # Cheapest and most exact first. /get (last) also searches external sources, which is
    # slow and often answers 503 "ServerOverloaded".
    attempts = [
        lambda: _get('/get-cached', {'artist_name': artist, 'track_name': track.title,
                                     'album_name': track.album, 'duration': durationS}),
        lambda: _pickFromSearch(_get('/search', {'artist_name': artist, 'track_name': title}), durationS),
        lambda: _pickFromSearch(_get('/search', {'q': title + ' ' + artist}), durationS),
        lambda: _get('/get', {'artist_name': artist, 'track_name': track.title,
                              'album_name': track.album, 'duration': durationS}),
    ]
    found = None
    transient = None
    for attempt in attempts:
        try:
            found = attempt()
        except Exception as e:
            if not _isTransient(e):
                raise
            transient = e
            found = None
            continue
        if found and (found.get('syncedLyrics') or found.get('instrumental')):
            break
        found = None
    if not found:
        return {'synced': None, 'instrumental': False, 'transient': repr(transient) if transient else None}
    return {'synced': parseLrc(found['syncedLyrics']) if found.get('syncedLyrics') else None,
            'instrumental': bool(found.get('instrumental')),
            'lrclibId': found.get('id')}


def fetch(track):
    # Returns {'synced': [(ms, words)] or None, 'instrumental': bool}; raises on network errors
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, re.sub(r'[^A-Za-z0-9]', '_', track.id) + '.json')
    try:
        with open(path) as f:
            cached = json.load(f)
        retry = TRANSIENT_RETRY if cached.get('transient') else NOT_FOUND_RETRY
        if cached['synced'] or cached['instrumental'] or time.time() - cached['fetched'] < retry:
            return cached
    except (OSError, ValueError, KeyError):
        pass
    result = _lookup(track)
    result['fetched'] = time.time()
    result['title'] = track.title
    result['artist'] = ', '.join(track.artists)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(result, f)
    os.replace(tmp, path)
    return result

#!/usr/bin/env python3.7
# Shows synced lyrics (from LRCLib) for whatever is playing on Spotify.
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
import bisect
import os
import sys
import threading
import time
import traceback
from rgbmatrix import RGBMatrix, RGBMatrixOptions
import ledpackage as lp
import layout
import lrclib
from spotify import Spotify, RateLimited

# Lines appear this much before their timestamp; Spotify's reported position trails the audio
# slightly, and a line showing a hair early reads better than one showing late.
LEAD_MS = 250
# Position corrections smaller than this are polling noise and are ignored (avoids flicker)
RESYNC_MS = 300
POLL_PLAYING = 2.0
POLL_PAUSED = 3.0
POLL_IDLE = 5.0
# A line normally stays up until the next one. Across a long break (an instrumental section,
# the outro) it gives way to the song info after LINE_HOLD_MS.
BREAK_MS = 12000
LINE_HOLD_MS = 8000
# Long lines that don't fit scroll; they pause this long at each end
SCROLL_HOLD_MS = 800
# LYRICS_DEBUG=1 logs every screen change with the song position, for checking timing
DEBUG = os.environ.get('LYRICS_DEBUG') == '1'

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 8
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350
# Stay root: the program writes its lyrics cache and Spotify token while running
options.drop_privileges = False

def log(message):
    # Console output must never take a thread down (e.g. if stdout is closed)
    try:
        # One write per line, so messages from different threads can't run together
        sys.stdout.write(time.strftime('%H:%M:%S ') + message + '\n')
        sys.stdout.flush()
    except Exception:
        pass


lp.recordPID('lyrics', str(os.getpid()))
matrix = RGBMatrix(options=options)
matrixCanvas = matrix.CreateFrameCanvas()


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.playback = None      # spotify.Playback, or None when nothing is playing
        self.error = None         # last Spotify error, shown when nothing else can be
        self.lyrics = {}          # track id -> Lyrics, or 'loading'


PENDING = 'pending'


class Lyrics:
    def __init__(self, result, error=None):
        # A temporary LRCLib failure counts as an error so the lookup is retried
        self.error = error or (result and result.get('transient'))
        self.fetched = time.monotonic()
        self.instrumental = bool(result and result.get('instrumental'))
        synced = result.get('synced') if result else None
        self.times = [ms for ms, words in synced] if synced else None
        self.words = [words for ms, words in synced] if synced else []
        # Each entry becomes layout.lyric()'s (image, wideImage), or None for a blank line
        self.images = [PENDING] * len(self.words)

    def image(self, index):
        # Wrapping a long line can take ~50 ms on the Pi, so lines are rendered in the
        # background; one the display needs before then is rendered on the spot.
        if self.images[index] is PENDING:
            words = self.words[index]
            self.images[index] = layout.lyric(words) if layout.toAscii(words) else None
        return self.images[index]


def loadLyrics(state, track):
    try:
        lyrics = Lyrics(lrclib.fetch(track))
        log('Lyrics for %s - %s: %s' % (track.artists[0], track.title,
              '%d lines' % len(lyrics.times) if lyrics.times else 'instrumental' if lyrics.instrumental
              else 'lookup failed, will retry' if lyrics.error else 'none'))
    except Exception as e:
        log('Lyrics lookup failed for %s: %r' % (track.title, e))
        lyrics = Lyrics(None, error=e)
    with state.lock:
        state.lyrics[track.id] = lyrics
    for index in range(len(lyrics.words)):
        lyrics.image(index)


def pollSpotify(spotify, state):
    delay = POLL_PLAYING
    while True:
        try:
            playback = spotify.currentlyPlaying()
            with state.lock:
                old = state.playback
                if (playback and old and playback.id == old.id and playback.playing and old.playing
                        and abs(playback.position(playback.at) - old.position(playback.at)) < RESYNC_MS):
                    playback = old
                if playback and (old is None or playback.id != old.id):
                    log('Now playing: %s - %s' % (', '.join(playback.artists), playback.title))
                state.playback = playback
                state.error = None
                entry = state.lyrics.get(playback.id) if playback else None
                # Look up lyrics for a new song, or retry a failed lookup after 30 s
                if playback and (entry is None or (entry != 'loading' and entry.error
                                                   and time.monotonic() - entry.fetched > 30)):
                    state.lyrics[playback.id] = 'loading'
                    threading.Thread(target=loadLyrics, args=(state, playback), daemon=True).start()
            if playback and playback.playing:
                # Poll sooner near the end of a song so the next one is picked up quickly
                remaining = (playback.durationMs - playback.position(time.monotonic())) / 1000
                delay = max(0.3, min(POLL_PLAYING, remaining + 0.2))
            else:
                delay = POLL_PAUSED if playback else POLL_IDLE
        except RateLimited as e:
            log('Spotify rate limit, waiting %d s' % e.seconds)
            delay = e.seconds
        except Exception as e:
            log('Spotify request failed: %r' % e)
            with state.lock:
                state.error = 'Spotify connection problem'
            delay = min(30, max(delay * 2, POLL_IDLE))
        time.sleep(delay)


def screenFor(state, now):
    # Decides what to show: returns (key, draw), where draw() gives (image, scrollOffset)
    with state.lock:
        playback, error = state.playback, state.error
        entry = state.lyrics.get(playback.id) if playback else None
    if playback is None:
        if error:
            return ('error', error), lambda: (layout.message(error), 0)
        return ('idle',), lambda: (layout.message('Nothing playing on Spotify', layout.DIM), 0)

    def info(note=None, dim=False):
        return (('info', playback.id, note, dim),
                lambda: (layout.songInfo(playback.title, ', '.join(playback.artists), note, dim), 0))

    if entry is None or entry == 'loading':
        return info('loading lyrics')
    if entry.error:
        return info('lyrics unavailable')
    if not entry.times:
        return info('instrumental' if entry.instrumental else 'no synced lyrics')

    position = playback.position(now) + LEAD_MS
    index = bisect.bisect_right(entry.times, position) - 1
    paused = not playback.playing
    if index < 0:
        return info('paused' if paused else None)
    start = entry.times[index]
    end = entry.times[index + 1] if index + 1 < len(entry.times) else playback.durationMs
    if end - start > BREAK_MS:
        end = start + LINE_HOLD_MS
    rendered = entry.image(index)
    if rendered is None or position >= end:
        return info('paused' if paused else None, dim=True)

    image, wide = rendered
    if image is not None:
        return ('line', playback.id, index, paused), lambda: (dimIfPaused(image, paused), 0)
    # Scroll a too-long line across the time it's sung, holding briefly at each end
    span = max(1, (end - start) - 2 * SCROLL_HOLD_MS)
    fraction = min(1, max(0, (position - start - SCROLL_HOLD_MS) / span))
    offset = -int(round(fraction * (wide.size[0] - layout.WIDTH)))
    return ('scroll', playback.id, index, paused, offset), lambda: (dimIfPaused(wide, paused), offset)


_dimmed = {}


def dimIfPaused(image, paused):
    # While paused, the current line stays up at about a third of its brightness
    if not paused:
        return image
    if id(image) not in _dimmed:
        _dimmed.clear()
        _dimmed[id(image)] = (image, image.point(lambda v: v * 35 // 100))
    return _dimmed[id(image)][1]


def show(image, offset=0):
    global matrixCanvas
    matrixCanvas.SetImage(image, offset)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)


state = State()
if not all(k in KEYS for k in ('spotify_client_id', 'spotify_client_secret', 'spotify_refresh_token')):
    log('Spotify is not connected yet: run spotify_auth.py on your PC.')
    show(layout.message('Run spotify_auth.py to connect Spotify'))
    while True:
        time.sleep(60)

show(layout.message('Connecting to Spotify...', layout.DIM))
threading.Thread(target=pollSpotify, args=(Spotify(KEYS), state), daemon=True).start()

lastKey = None
while True:
    try:
        # The key identifies what's on screen; the image is only drawn when it changes
        key, draw = screenFor(state, time.monotonic())
        if key != lastKey:
            show(*draw())
            if DEBUG:
                with state.lock:
                    playback = state.playback
                log('screen %r at song position %s' % (key[:1] + key[2:], '%.2f s' % (
                    playback.position(time.monotonic()) / 1000) if playback else '-'))
            lastKey = key
    except Exception:
        log(traceback.format_exc().rstrip())
        time.sleep(1)
    time.sleep(0.02)

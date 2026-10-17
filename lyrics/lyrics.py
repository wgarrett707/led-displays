#!/usr/bin/env python3.7
# Shows synced lyrics (from LRCLib) for whatever is playing on Spotify, with animated effects.
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
import bisect
import os
import sys
import threading
import time
import traceback
from PIL import Image
from rgbmatrix import RGBMatrix, RGBMatrixOptions
import ledpackage as lp
import layout
import lrclib
import effects
import moreeffects
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
# Target time per animation frame (~40 fps); rounded to a whole number of panel refreshes
FRAME_TIME = 0.025
# While paused, the last frame stays up at this brightness
PAUSED_BRIGHTNESS = 0.35
# LYRICS_DEBUG=1 logs every screen change with the song position, for checking timing
DEBUG = os.environ.get('LYRICS_DEBUG') == '1'
# LYRICS_EFFECT=<name> uses one effect for every song instead of cycling through them
FIXED_EFFECT = os.environ.get('LYRICS_EFFECT')

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
# The refresh thread is pinned to CPU 3 at top real-time priority; keep this process (and the
# threads it starts) on the other cores so animation frames aren't held up behind it.
if os.cpu_count() >= 4:
    os.sched_setaffinity(0, {0, 1, 2})


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.playback = None      # spotify.Playback, or None when nothing is playing
        self.error = None         # last Spotify error, shown when nothing else can be
        self.lyrics = {}          # track id -> Lyrics, or 'loading'
        self.effectName = ''      # current effect, shown on the song info screen


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
        # Each entry becomes (effects.Text, None) for a line that fits, (None, (wideMask, boxes))
        # for one that scrolls, or None for a blank line
        self.texts = [PENDING] * len(self.words)

    def text(self, index):
        # Lines are laid out in the background (a few ms each); one the display needs before
        # then is laid out on the spot.
        if self.texts[index] is PENDING:
            words = self.words[index]
            if not layout.toAscii(words):
                self.texts[index] = None
            else:
                mask, boxes, wide = layout.lyric(words)
                self.texts[index] = (None, (mask, boxes)) if wide else (effects.Text(mask, boxes), None)
        return self.texts[index]


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
        lyrics.text(index)


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


class Screen:
    # What to show right now. 'key' identifies it: a new key starts a new entrance animation.
    # Either 'static' (a plain RGB image, no effect) or 'make' (builds the effects.Text).
    def __init__(self, key, static=None, make=None, track=None, paused=False, progress=None, line=0,
                 scroll=None):
        self.key, self.static, self.make, self.track = key, static, make, track
        self.paused, self.progress, self.line = paused, progress, line
        self.scroll = scroll      # (wideMask, boxes, offset) for a line too long to fit


def screenFor(state, now):
    with state.lock:
        playback, error, effectName = state.playback, state.error, state.effectName
        entry = state.lyrics.get(playback.id) if playback else None
    if playback is None:
        if error:
            return Screen(('error', error), static=lambda: layout.message(error))
        return Screen(('idle',), static=lambda: layout.message('Nothing playing on Spotify', layout.DIM))

    paused = not playback.playing

    def info(note=None, dim=False):
        note = note or effectName
        artists = ', '.join(playback.artists)
        return Screen(('info', playback.id, note, dim), track=playback.id, paused=paused,
                      make=lambda: effects.Text(*layout.songInfo(playback.title, artists, note, dim)))

    if entry is None or entry == 'loading':
        return info('loading lyrics')
    if entry.error:
        return info('lyrics unavailable')
    if not entry.times:
        return info('instrumental' if entry.instrumental else 'no synced lyrics')

    position = playback.position(now) + LEAD_MS
    index = bisect.bisect_right(entry.times, position) - 1
    if index < 0:
        return info()
    start = entry.times[index]
    end = entry.times[index + 1] if index + 1 < len(entry.times) else playback.durationMs
    if end - start > BREAK_MS:
        end = start + LINE_HOLD_MS
    laidOut = entry.text(index)
    if laidOut is None or position >= end:
        return info(dim=True)

    progress = min(1.0, max(0.0, (position - start) / max(1.0, 0.92 * (end - start))))
    text, wide = laidOut
    screen = Screen(('line', playback.id, index), track=playback.id, paused=paused, progress=progress,
                    line=index, make=lambda: text)
    if wide is not None:
        # Scroll a too-long line across the time it's sung, holding briefly at each end
        mask, boxes = wide
        span = max(1, (end - start) - 2 * SCROLL_HOLD_MS)
        fraction = min(1, max(0, (position - start - SCROLL_HOLD_MS) / span))
        screen.scroll = (mask, boxes, -int(round(fraction * (mask.size[0] - layout.WIDTH))))
    return screen


def scrolledText(mask, boxes, offset):
    # The visible 256 px of a wide line, as a Text
    crop = mask.crop((-offset, 0, -offset + layout.WIDTH, layout.HEIGHT))
    return effects.Text(crop, [(x0 + offset, y0, x1 + offset, y1, s, t) for x0, y0, x1, y1, s, t in boxes])


def measureRefresh(frames=120):
    # Times bare SwapOnVSync calls (one panel refresh each); drawing is kept out of the loop
    # because it can take longer than a refresh
    global matrixCanvas
    blank = Image.new('RGB', (layout.WIDTH, layout.HEIGHT))
    for _ in range(2):
        matrixCanvas.SetImage(blank)
        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    start = time.monotonic()
    for _ in range(frames):
        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    return (time.monotonic() - start) / frames


def show(image):
    global matrixCanvas
    matrixCanvas.SetImage(image)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)


# Cycled through one per song
ALL_EFFECTS = moreeffects.EFFECTS + effects.EFFECTS


def pickEffect(count):
    if FIXED_EFFECT:
        for cls in ALL_EFFECTS:
            if cls.name.lower() == FIXED_EFFECT.lower():
                return cls()
    return ALL_EFFECTS[count % len(ALL_EFFECTS)]()


state = State()
if not all(k in KEYS for k in ('spotify_client_id', 'spotify_client_secret', 'spotify_refresh_token')):
    log('Spotify is not connected yet: run spotify_auth.py on your PC.')
    show(layout.message('Run spotify_auth.py to connect Spotify'))
    while True:
        time.sleep(60)

refreshPeriod = measureRefresh()
refreshesPerFrame = max(1, round(FRAME_TIME / refreshPeriod))
# Each frame is handed over in the middle of its last refresh, so frames land evenly
swapDelay = (refreshesPerFrame - 0.5) * refreshPeriod
log('Panel refresh %.2f ms; animating at %.0f fps' % (refreshPeriod * 1000, 1 / (refreshesPerFrame * refreshPeriod)))
show(layout.message('Connecting to Spotify...', layout.DIM))
threading.Thread(target=pollSpotify, args=(Spotify(KEYS), state), daemon=True).start()

effect, effectCount, track = None, -1, None
key, current, previous, isStatic = None, None, None, True
clock, keyStart, lastFrame, lastSwap = 0.0, 0.0, time.monotonic(), time.monotonic()
lastOutput, pausedShown = None, False
while True:
    try:
        now = time.monotonic()
        dt, lastFrame = min(0.1, now - lastFrame), now
        screen = screenFor(state, now)

        if screen.track and screen.track != track:
            # New song: next effect
            effectCount += 1
            effect = pickEffect(effectCount)
            with state.lock:
                state.effectName = effect.name
            log('Effect: %s' % effect.name)
            screen = screenFor(state, now)
            previous, current = None, None
        track = screen.track or track

        if screen.key != key:
            if DEBUG:
                with state.lock:
                    playback = state.playback
                log('screen %r at song position %s' % (screen.key[:1] + screen.key[2:], '%.2f s' % (
                    playback.position(now) / 1000) if playback else '-'))
            key, pausedShown = screen.key, False
            isStatic = screen.static is not None
            if isStatic:
                show(screen.static())
                current = previous = None
            else:
                previous, current = current, screen.make()
                keyStart = clock

        if isStatic:
            time.sleep(0.05)
            continue

        text = scrolledText(*screen.scroll) if screen.scroll else current
        if screen.paused:
            # Freeze the animation and keep the current text up, dimmed
            if not pausedShown:
                frame = effect.render(effects.Frame(text, None, clock, 99.0, screen.progress, screen.line, 0.0))
                show(Image.fromarray(effects.toBytes(frame * PAUSED_BRIGHTNESS), 'RGB'))
                pausedShown = True
            time.sleep(0.05)
            continue
        pausedShown = False

        clock += dt
        frame = effect.render(effects.Frame(text, previous, clock, clock - keyStart, screen.progress,
                                            screen.line, dt))
        matrixCanvas.SetImage(Image.fromarray(effects.toBytes(frame), 'RGB'))
        delay = lastSwap + swapDelay - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
        lastSwap = time.monotonic()
    except Exception:
        log(traceback.format_exc().rstrip())
        time.sleep(1)

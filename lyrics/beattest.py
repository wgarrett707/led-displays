#!/usr/bin/env python3.7
# Beat test: a plain metronome on the matrix and the strips, following whatever Spotify is playing,
# for checking the beat clock by eye and ear. Four blocks on the matrix are beats 1-4 of the bar
# (beat 1 red); the strips flash on every beat (beat 1 red). Right side: tempo, and sync status
# (grey WAIT = no analysis yet, yellow = measuring the speaker delay, green = locked).
# Run with the hub stopped:
#   sudo systemctl stop ledhub; sudo python3 beattest.py; sudo systemctl start ledhub
# /tmp/beatnudge can hold a number of ms to show the beats earlier (+) or later (-); read every second.
import json
import math
import os
import sys
import threading
import time
import numpy as np
from PIL import Image, ImageDraw
from rgbmatrix import RGBMatrix, RGBMatrixOptions
import layout
import beatsync
import strips
from spotify import Spotify

KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
NUDGE_FILE = '/tmp/beatnudge'
MATRIX_LEAD = 0.02
STRIP_LEAD = strips.LEAD
DECAY = 0.12          # seconds for a flash to fade
RED, WHITE = np.array((255, 30, 30), np.float32), np.array((255, 255, 255), np.float32)


class Playing:
    def __init__(self):
        self.lock = threading.Lock()
        self.playback = None
        self.clock = None

    def get(self):
        with self.lock:
            return self.playback

    def poll(self, spotify):
        while True:
            try:
                p = spotify.currentlyPlaying()
                if self.clock is not None:
                    self.clock.observe(p)
                with self.lock:
                    old = self.playback
                    # Same rule as lyrics.py: small position differences are polling noise
                    if (p and old and p.id == old.id and p.playing and old.playing
                            and abs(p.position(p.at) - old.position(p.at)) < 300):
                        p = old
                    self.playback = p
            except Exception as e:
                print('Spotify: %r' % e, flush=True)
            time.sleep(2)


def flash(st):
    # Brightness of the current beat's flash, and whether it's beat 1 of the bar
    since = (st.beat % 1.0) * st.period
    return math.exp(-since / DECAY), int(math.floor(st.beat)) % 4 == 0


class Metronome(strips.Strips):
    def render(self, st):
        level, one = flash(st)
        return np.ones((strips.LONGEST, 3), np.float32) * ((RED if one else WHITE) / 255.0) * (0.85 * level)


def main():
    options = RGBMatrixOptions()
    options.rows = 32
    options.chain_length = 8
    options.parallel = 1
    options.hardware_mapping = 'regular'
    options.brightness = 18
    options.multiplexing = 6
    options.led_rgb_sequence = "BGR"
    options.pwm_lsb_nanoseconds = 350
    options.drop_privileges = False
    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()
    if os.cpu_count() >= 4:
        os.sched_setaffinity(0, {0, 1, 2})

    playing = Playing()
    threading.Thread(target=playing.poll, args=(Spotify(KEYS),), daemon=True).start()
    clock = beatsync.BeatClock(playing.get)
    playing.clock = clock
    clock.start()
    Metronome(clock).start()

    nudge, lastCheck, lastLog = 0.0, 0.0, 0.0
    while True:
        now = time.monotonic()
        if now - lastCheck > 1.0:
            lastCheck = now
            try:
                nudge = float(open(NUDGE_FILE).read().strip() or 0) / 1000.0
            except (OSError, ValueError):
                nudge = 0.0
            strips.LEAD = STRIP_LEAD + nudge
        st = clock.state(now, MATRIX_LEAD + nudge)
        p = playing.get()
        img = Image.new('RGB', (256, 32))
        draw = ImageDraw.Draw(img)
        draw.fontmode = '1'
        for i in range(4):
            x0 = 4 + i * 48
            draw.rectangle((x0, 3, x0 + 42, 28), outline=(40, 10, 10) if i == 0 else (35, 35, 35))
        if st is not None:
            level, one = flash(st)
            current = int(math.floor(st.beat)) % 4
            color = (RED if one else WHITE) * max(level, 0.10)
            x0 = 4 + current * 48
            draw.rectangle((x0, 3, x0 + 42, 28), fill=tuple(int(c) for c in color))
            status = (0, 200, 0) if clock.locked else (220, 180, 0)
            draw.text((204, 0), '%3.0f' % st.tempo, font=layout.FONT, fill=status)
            draw.text((204, 16), 'BPM', font=layout.FONT, fill=status)
        else:
            path = os.path.join(beatsync.BEATS_DIR, p.id + '.json') if p else None
            text = 'IDLE' if p is None else 'PAUSE' if not p.playing else 'NONE' if path and os.path.exists(path) else 'WAIT'
            draw.text((204, 8), text, font=layout.FONT, fill=(110, 110, 110))
        canvas.SetImage(img)
        canvas = matrix.SwapOnVSync(canvas)
        if now - lastLog > 5.0:
            lastLog = now
            spread = (np.ptp(clock.anchors) * 1000) if len(clock.anchors) > 1 else 0
            print('%s %s | %s offset %+.0f ms locked=%s room %+.0f ms polls %d (spread %.0f ms) nudge %+.0f ms' % (
                time.strftime('%H:%M:%S'), (p.title[:30] if p else '-'),
                ('beat %.2f %.1f BPM' % (st.beat, st.tempo)) if st else 'no beat clock',
                clock.offset * 1000, clock.locked, clock.room * 1000, len(clock.anchors), spread, nudge * 1000), flush=True)
        time.sleep(max(0.0, 1 / 60.0 - (time.monotonic() - now)))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass

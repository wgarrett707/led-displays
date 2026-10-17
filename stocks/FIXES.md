# Stocks display: bugs and fixes (2026-10-17)

## How it runs

Selecting **stocks** in the hub runs two scripts (from `hub/serverTest3.py`):

```
nice -n 10 sudo python3 stocks/FinnhubGeneratorFix2.py & nice -n -20 sudo python3 stocks/logoviewer12.py
```

- **`FinnhubGeneratorFix2.py`** (generator) fetches a Finnhub quote for each of 108 symbols and renders
  `displays/<SYM>.png` (logo, ticker, price, arrow, % change). It waits `width * 0.005` s between symbols
  to stay under Finnhub's 60 requests/min, and checks market hours to decide how often to refresh.
- **`logoviewer12.py`** (scroller) drives the matrix, scrolling each `displays/<SYM>.png` 1 px per frame.
- They hand off through `Ready.txt`: the scroller writes `1` at startup and at the 5th-from-last logo;
  the generator waits for `1`, resets it to `0`, and regenerates every image.

Every other script in `stocks/` is an older version or a test and isn't run.

## Bugs fixed

### 1. Any network or API error froze prices for the rest of the session (generator)
`finnhub_client.quote()` had no error handling or timeout. A dropped connection, a Finnhub outage or a
429 rate-limit response crashed the generator. The scroller kept running, showing stale prices
indefinitely with no sign anything was wrong. A hung connection could also block it forever.

**Fix:** `fetchQuote()` adds a 10 s request timeout and catches errors. On failure the symbol keeps its
previous image and the generator moves on. It waits 60 s after a 429, or 5 s after other errors.

### 2. `checkReady()` could crash with a RecursionError (generator)
`checkReady()` polled by calling itself every 0.5 s. It can wait several minutes for the scroller,
adding about 2 stack frames per second against Python's limit of 1000. A slow scroll cycle (CPU
throttling, wider images) would crash the generator, with the same frozen-prices result as bug 1.

**Fix:** it now polls in a `while` loop.

### 3. The scroller could read a half-written image and crash (both)
The generator overwrote `displays/<SYM>.png` while the scroller might be opening it. The scroller
retried once; a second failure crashed it.

**Fix:** the generator writes to `<SYM>.png.tmp` and renames it into place, which is atomic. The
scroller retries up to 3 times and skips the symbol if it still can't load it.

### 4. Possible lost first refresh at startup (generator)
The generator reset `Ready.txt` at the top of its loop. If the scroller had already marked itself
ready, the reset wiped that out, and the first price refresh waited a full scroll cycle (~5 min).

**Fix:** `Ready.txt` is reset once, before the generator records its PID (which the scroller waits
on), and the first pass starts immediately. Later passes use the same handshake as before.

## Speed and smoothness

### 5. 20 s of fixed sleeps at startup (scroller)
The scroller slept 10 s, recorded its PID, then slept another 10 s. **Removed.** The loading screen
now stays up only until the generator has recorded its PID, then scrolling starts with the
previous session's images while the generator refreshes them.

### 6. 13 s import of pandas for a single check (generator)
`pandas` and `pandas_market_calendars` were imported only to ask "is today an NYSE trading day?".
**Replaced** with `isTradingDay()`: a weekday check plus the regular NYSE holidays (New Year's Day,
MLK Day, Presidents' Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day,
Thanksgiving, Christmas), with weekend observance rules. Checked against the official NYSE schedules
for 2022 and 2025-2027. One-off closures (e.g. national days of mourning) aren't included; on those
days it just keeps refreshing as if open.

### 7. Jittery scrolling (scroller)

#### How the panel is driven
The library (`rpi-rgb-led-matrix`, commit `56b87b9` from Jan 2020, installed into
`/usr/local/lib/python3.7/site-packages/rgbmatrix`) runs a **refresh thread** at real-time priority 99,
pinned to CPU 3. It redraws the whole panel continuously, about **126 times a second (7.9 ms each,
measured; very stable)**. There are two frame buffers: one is shown while the script draws into the other.
`SwapOnVSync(buffer)` hands over the drawn buffer, **blocks until the end of the refresh in progress**,
and returns the other buffer. `SetImage(image, offset)` writes only the image columns that land on the
panel; it never clears anything.

#### What caused the jitter (all measured on the panel)
- **The original loop** did `SetImage`, `SwapOnVSync`, then `sleep(0.01)`. Because the sleep isn't a
  whole number of refreshes, steps randomly took 2 or 3 refreshes: **60 uneven steps/minute** at idle.
- **`SetImage` is slow and variable**: 2.2 ms median, 5.7 ms p99, 13 ms worst (8,192 pixels, each through
  the "coreman" multiplex mapper). Drawing every refresh left ~5 ms of slack, so slow draws made a
  position stay up one refresh too long.
- **Logo transitions** took ~21 ms (up to 81 ms): a full garbage collection (16 ms) and reading the
  next PNG from the SD card (usually 1 ms, up to 66 ms).
- **The scroller's thread could land on CPU 3**, where the refresh thread always takes priority.

#### Fix
- **One draw per step, swap timed to the panel:** each position is drawn once, straight after the
  previous swap, and handed over in the middle of the step's last refresh, so it appears exactly 2
  refreshes later (15.8 ms per step, ~63 px/s). This leaves ~12 ms of slack instead of ~5. The refresh
  period is measured at startup while the loading screen shows.
- **The next logo's file is read on a background thread** while the current one scrolls.
- **`gc.freeze()` at startup:** collecting between logos now takes ~0 ms instead of 16 ms.
- **The scroller is pinned to CPUs 0-2.**

#### Result (60 s runs on the real panel with the real images)
| Version | Idle | Under load (2 busy processes) |
|---|---|---|
| Original | 60 glitches/min | — |
| Drawing every refresh (interim fix) | 26 glitches/min | 62 glitches/min |
| **Final** | **1.1 glitches/min** | **3.2 glitches/min** |

No steps came early, and the worst glitch is one extra refresh (8 ms).

**Tuning:** `FRAME_TIME` at the top of `logoviewer12.py` picks the step length, rounded to a whole
number of refreshes: 0.016 gives 2 refreshes (~63 px/s), 0.024 gives 3 (~42 px/s), 0.008 gives 1 (~126 px/s).

### 8. Pixels shifted a pixel or two at the left edge (scroller)
The scroller drew the canvas at offset `xpos - 250 + 256`, which is positive (5 down to 1) for the
first 5 steps of every logo. `SetImage` skips columns left of the offset, so panel columns 0-4 kept
whatever that buffer held from two swaps earlier: pixels 1-2 px behind the rest of the image.
**Fix:** new logos are pasted at column 255, so the offset is never positive and every frame covers
all 256 columns.

If shifted pixels still appear **elsewhere** on the panel, or on the hub menu or other programs, the
likely cause is the GPIO signal timing instead: `gpio_slowdown` is at its default of 1 (fastest), which
is marginal on a Pi 3 driving 5 V panels from 3.3 V pins. `options.gpio_slowdown = 2` costs only ~5%
refresh rate (126 Hz to 120 Hz, measured). Under-voltage makes it worse.

## Not changed (recommendations)

- **Power and heat.** `vcgencmd get_throttled` reported `0xd0008`: under-voltage has occurred, and
  the CPU is currently at its soft temperature limit (61 °C). Throttling slows the LED refresh and
  causes flicker. Use a 5.1 V / 2.5 A+ supply and add a heatsink or fan.
- **`isolcpus=3`** in `/boot/cmdline.txt` gives the matrix refresh thread its own core, which is the
  library author's main recommendation against flicker. It's a boot setting and affects every
  program, so back up `cmdline.txt` first.
- **`options.pwm_bits`**: lowering it from 11 to 8 only raised the refresh rate from 126 Hz to 138 Hz
  (measured), so it isn't worth the colour loss.
- **Library upgrade**: newer versions can swap every Nth refresh natively, but the multiplexing
  numbering changed (coreman is no longer 6), and every program uses this install, so it wasn't upgraded.
- The hub's Esc handler kills the PIDs in `hub/stocks.txt`. If Esc is pressed before the new scripts
  have recorded their PIDs, it kills stale PIDs instead. Removing the startup sleeps makes that window
  much smaller, but the hub logic itself is unchanged.

## Rolling back

```
cd ~/led-scripts && git log --oneline -- stocks/
git checkout <commit-before-fixes> -- stocks/FinnhubGeneratorFix2.py stocks/logoviewer12.py
```

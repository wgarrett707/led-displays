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

### 7. Uneven scroll speed (scroller)
Each frame took `SwapOnVSync` time + a fixed `sleep(0.01)` + Python's own work, which varies, so the
scroll speed wobbled. **Fix:** frames are now scheduled against a fixed clock (`FRAME_TIME = 0.016`,
about 62 px/s). If the Pi falls well behind, it resyncs instead of speeding up to catch up. Python's
garbage collector, which can pause unpredictably, now only runs between logos.

**Tuning:** adjust `FRAME_TIME` at the top of `logoviewer12.py` if the speed differs from before.

## Not changed (recommendations)

- **Power and heat.** `vcgencmd get_throttled` reported `0xd0008`: under-voltage has occurred, and
  the CPU is currently at its soft temperature limit (61 °C). Throttling slows the LED refresh and
  causes flicker. Use a 5.1 V / 2.5 A+ supply and add a heatsink or fan.
- **`isolcpus=3`** in `/boot/cmdline.txt` gives the matrix refresh thread its own core, which is the
  library author's main recommendation against flicker. It's a boot setting and affects every
  program, so back up `cmdline.txt` first.
- **`options.pwm_bits`** (default 11): lowering to ~8 raises the refresh rate; at brightness 30 the
  colour loss is hard to see. Compare on the panel.
- The hub's Esc handler kills the PIDs in `hub/stocks.txt`. If Esc is pressed before the new scripts
  have recorded their PIDs, it kills stale PIDs instead. Removing the startup sleeps makes that window
  much smaller, but the hub logic itself is unchanged.

## Rolling back

```
cd ~/led-scripts && git log --oneline -- stocks/
git checkout <commit-before-fixes> -- stocks/FinnhubGeneratorFix2.py stocks/logoviewer12.py
```

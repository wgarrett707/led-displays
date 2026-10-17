# led-displays

A Python project using hzeller's LED display library to scroll current stock prices, show current news headlines, subscriber counts, and the weather/time.

The display is eight chained 32-row panels (256x32) driven from a Raspberry Pi.

## Layout

- `hub/` - menu: `keyPressTest4.py` draws the menu, `serverTest3.py` reads the keyboard on tty1 and starts/kills programs
- `stocks/`, `news/`, `weather/`, `discord/`, `subs/`, `banana/` - display programs
- `onBoot.py` - boot splash

## Boot

`/etc/systemd/system/ledhub.service` (root, on tty1) runs `/home/pi/led-scripts/hub/start3.py`, which launches `keyPressTest4.py` and `serverTest3.py`.

## Restoring from this repo

1. Clone to `/home/pi/led-scripts` (paths are hardcoded).
2. Create `apikeys.json` (not committed) with keys:
   `alphavantage`, `discord`, `finnhub`, `finnhub_old`, `fmp`, `newsapi`, `openweathermap`, `youtube`.
3. Install hzeller's rpi-rgb-led-matrix Python bindings.
4. Create the hub state files, which are not committed:
   `cd hub && touch hub.txt input.txt running.txt stocks.txt stockslocal.txt news.txt weather.txt discord.txt discordlocal.txt subs.txt banana.txt pidKill.txt && chmod 777 *.txt`
5. Create `stocks/displays/`.

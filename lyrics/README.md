# Lyrics

Shows synced lyrics for whatever is playing on Spotify, line by line, in time with the song.

- `lyrics.py` - the display program (polls Spotify, picks the current line, drives the matrix)
- `spotify.py` - Spotify Web API: token refresh and current playback
- `lrclib.py` - looks up synced lyrics on [LRCLib](https://lrclib.net) and caches them in `cache/`
- `layout.py` - renders lines in one font size (6x11 at 16): one line, or two balanced lines;
  the rare line too long for two scrolls sideways
- `spotify_auth.py` - one-time Spotify login, run on a PC (not the Pi)

## Setup

1. Create an app at <https://developer.spotify.com/dashboard> (the account needs Spotify Premium).
   Add the Redirect URI `http://127.0.0.1:8765/callback` and select "Web API".
2. On a PC with SSH access to the Pi, run `python spotify_auth.py` and enter the app's Client ID and
   Client Secret. It opens the Spotify login, then saves `spotify_client_id`,
   `spotify_client_secret` and `spotify_refresh_token` into `apikeys.json` on the Pi.

## Running it by hand

The matrix can only be driven by one program, so stop the hub first:

```
sudo systemctl stop ledhub
sudo python3 /home/pi/led-scripts/lyrics/lyrics.py      # LYRICS_DEBUG=1 logs every screen change
sudo systemctl start ledhub
```

## Behaviour

- Lines appear `LEAD_MS` (250 ms) before their timestamp; Spotify's reported position trails the
  audio slightly. Measured: lines switch 0.21-0.25 s before their LRC timestamps.
- Spotify is polled every 2 s while playing (sooner near the end of a song), 3 s paused, 5 s idle.
  Between polls the position is extrapolated; corrections under 300 ms are ignored.
- Paused: the current line stays up, dimmed. Long instrumental breaks (>12 s between lines) show the
  song info after 8 s.
- Lookup order: LRCLib `/get-cached` (exact), `/search` matched by track length (+-3 s), then
  `/get` (which also queries external sources and is often overloaded). Results are cached per
  Spotify track; "not found" is retried after a day, temporary errors after 10 minutes.
- The fonts are ASCII: accents are stripped and characters they can't draw (e.g. CJK) are dropped.

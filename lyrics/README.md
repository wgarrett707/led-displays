# Lyrics

Shows synced lyrics for whatever is playing on Spotify, line by line, in time with the song.

- `lyrics.py` - the display program (polls Spotify, picks the current line, drives the matrix)
- `spotify.py` - Spotify Web API: token refresh and current playback
- `lrclib.py` - looks up synced lyrics on [LRCLib](https://lrclib.net) and caches them in `cache/`
- `layout.py` - lays out lines in one font size (6x11 at 16): one line, or two balanced lines;
  the rare line too long for two scrolls sideways. Produces text masks for the effects.
- `effects.py`, `moreeffects.py`, `partyeffects.py`, `clubeffects.py` - the animated effects
- `spotify_auth.py` - one-time Spotify login, run on a PC (not the Pi)

## Setup

1. Create an app at <https://developer.spotify.com/dashboard> (the account needs Spotify Premium).
   Add the Redirect URI `http://127.0.0.1:8765/callback` and select "Web API".
2. On a PC with SSH access to the Pi, run `python spotify_auth.py` and enter the app's Client ID and
   Client Secret. It opens the Spotify login, then saves `spotify_client_id`,
   `spotify_client_secret` and `spotify_refresh_token` into `apikeys.json` on the Pi.

## In the hub

Lyrics is the 6th item in the hub menu (after Subs), and the hub starts it at boot
(`BOOT_PROGRAM` in `hub/start3.py`; set it to `''` to boot to the menu instead). Esc goes back to the menu, as with
the other programs.

## Running it by hand

The matrix can only be driven by one program, so stop the hub first:

```
sudo systemctl stop ledhub
sudo python3 /home/pi/led-scripts/lyrics/lyrics.py
sudo systemctl start ledhub
```

Options (environment variables; note `sudo VAR=value python3 ...`):
- `LYRICS_EFFECT=Fire` - use one effect for every song instead of cycling
- `LYRICS_DEBUG=1` - log every screen change with the song position

## Effects

One effect per song, cycling in this order (the effect's name shows after the artist on the
song info screen). All run at ~43 fps; each frame costs 3-13 ms of CPU on the Pi 3B+.

- Club: Strobe, Bass Drop, Shockwave, Rave, Laser Fan, LED Wall, Crowd, Sirens, Glow Sticks, Pulse
- Party: Confetti, Club Lights, Meteors, Embers, Inferno, Warp Tunnel, City Storm, Electric,
  Particles, Mirror EQ, Bubbles
- Earth (orbit view; its 0.25-degree surface is built once and cached in `cache/earth-v1.npz`)
- Wave, Lasers, Matrix, Fireworks, Synthwave, Disco, Storm, Bounce, Aurora, Pac-Man
- Rainbow, Neon, Fire, Karaoke, Plasma, Glitch, Hyperspace, Equalizer

Beat-synced effects assume 120 BPM (Spotify no longer gives new apps tempo data).

**Flashing:** Strobe, Bass Drop's snare roll and Sirens flash at 4 Hz or more, which can trigger
seizures in people with photosensitive epilepsy. `STROBE_FLASHES_PER_BEAT` in `clubeffects.py` sets
the strobe rate (2 = 4 flashes a second at 120 BPM).

Effects get the text as an `effects.Text` (mask, black outline ring, per-pixel shade, line boxes)
and return one 32x256 RGB frame per call; see `effects.Effect` and `effects.paint`. On the Pi 3,
whole-frame numpy operations cost ~0.3-1.5 ms each, so effects avoid masked gathers/scatters, use
cached per-line weights, and batch particle drawing (`moreeffects.additive`).

## Behaviour

- Lines appear `LEAD_MS` (250 ms) before their timestamp; Spotify's reported position trails the
  audio slightly. Measured: lines switch 0.21-0.25 s before their LRC timestamps.
- Spotify is polled every 2 s while playing (sooner near the end of a song), 3 s paused, 5 s idle.
  Between polls the position is extrapolated; corrections under 300 ms are ignored.
- Paused: the current line stays up, dimmed. Long instrumental breaks (>12 s between lines) show the
  song info after 8 s.
- Lookup order: LRCLib `/get-cached` (exact), `/search` matched by track length (+-3 s), then
  `/get` (which also queries external sources and is often overloaded). When search results
  exist but none is the song's length, the closest length is used (its timing may drift).
  Results are cached per Spotify track; "not found" and different-length fallbacks are looked
  up again after a day, temporary errors after 10 minutes.
- The fonts are ASCII: accents are stripped and characters they can't draw (e.g. CJK) are dropped.

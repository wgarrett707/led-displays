# Lyrics

Shows synced lyrics for whatever is playing on Spotify, line by line, in time with the song.

- `lyrics.py` - the display program (polls Spotify, picks the current line, drives the matrix)
- `spotify.py` - Spotify Web API: token refresh and current playback
- `lrclib.py` - looks up synced lyrics on [LRCLib](https://lrclib.net) and caches them in `cache/`
- `layout.py` - lays out lines in one font size (6x11 at 16): one line, or two balanced lines;
  the rare line too long for two scrolls sideways. Produces text masks for the effects.
- `effects.py`, `moreeffects.py`, `partyeffects.py`, `clubeffects.py` - the animated effects
- `brat.py` - the brat album theme
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

**Now: one look for every song** (`ONE_LOOK = True` in `lyrics.py`): plain white text on black, each
new line wiping in from the bottom and pushing the old one up (`effects.Wipe`, 0.25 s); no brat theme
and no white flash on drops (the strips still have theirs). `ONE_LOOK = False` brings back everything
below.

One effect per song, cycling in this order (the effect's name shows after the artist on the
song info screen). All run at ~43 fps; each frame costs 3-13 ms of CPU on the Pi 3B+.

- Club: Strobe, Bass Drop, Shockwave, Rave, Laser Fan, LED Wall, Crowd, Sirens, Glow Sticks, Pulse
- Party: Confetti, Club Lights, Meteors, Embers, Inferno, Warp Tunnel, City Storm, Electric,
  Particles, Mirror EQ, Bubbles
- Earth (orbit view; its 0.25-degree surface is built once and cached in `cache/earth-v1.npz`)
- Wave, Lasers, Matrix, Fireworks, Synthwave, Disco, Storm, Bounce, Aurora, Pac-Man
- Rainbow, Neon, Fire, Karaoke, Plasma, Glitch, Hyperspace, Equalizer

**brat theme:** songs from Charli xcx's brat albums (brat, the deluxe, and the remix album) skip the
cycle and get the cover's look instead: lowercase Arial Narrow, slightly blurred, black on brat
green (#8ACE00); see `brat.py`. `LYRICS_EFFECT=brat` shows every song that way. Arial Narrow is a
Microsoft font, so it's kept out of the repo: copy `C:\Windows\Fonts\ARIALN.TTF` to `fonts/` (without
it the theme falls back to the pixel font).

Beat-synced effects assume 120 BPM (Spotify no longer gives new apps tempo data).

**Flashing:** Strobe, Bass Drop, Club Lights and Sirens are left out of the cycle while
`SKIP_FLASHING` in `lyrics.py` is True. Strobe, Bass Drop's snare roll and Sirens flash at 4 Hz or more, which can trigger
seizures in people with photosensitive epilepsy. `STROBE_FLASHES_PER_BEAT` in `clubeffects.py` sets
the strobe rate (2 = 4 flashes a second at 120 BPM).

Effects get the text as an `effects.Text` (mask, black outline ring, per-pixel shade, line boxes)
and return one 32x256 RGB frame per call; see `effects.Effect` and `effects.paint`. On the Pi 3,
whole-frame numpy operations cost ~0.3-1.5 ms each, so effects avoid masked gathers/scatters, use
cached per-line weights, and batch particle drawing (`moreeffects.additive`).

## Beat sync and the LED strips

The lights follow each song's real beat instead of assuming 120 BPM.

- **On the PC** (`pc/analyze.py`, run from `Documents\led-lights` with its own venv): finds the song's
  audio on YouTube (same length as on Spotify, preferring the "Artist - Topic" album uploads), and
  works out the beats (Deezer's BPM as a hint; most songs are recorded to a click, so when at least 80% of
  the song sits on one steady tempo the whole grid is that exact tempo, which stops the tracker slipping onto
  the off-beat in breakdowns; close calls between beat and off-beat are flagged in the editor), bar lines, sections (repeats share a label; the
  loudest repeated one is the chorus), drops and their build-ups, a melody note per half beat, and
  a bass onset envelope. Results go to `beats/<Spotify id>.json` on the Pi.
  `watch.bat` (or `analyze.py watch`) picks up songs the Pi has played without an analysis
  (`beats/pending/`); `analyze.py playlist <link>` (yours or public; read through the Pi's Spotify login, since Spotify only lists a playlist's songs to a signed-in user) / `album <link>` / `track <link>` do them ahead of time.
- **Chart notes** (`pc/charts.py`): when someone has made a Clone Hero / Rock Band chart of the song, the
  analysis also stores its expert guitar, bass, keys and drum notes. Charts are found through Chorus
  Encore (the search behind the Bridge downloader), official ones (Harmonix etc.) and full-band charts
  first. A chart is timed against its own audio, which can start a few seconds earlier or later than
  ours, so that audio is downloaded just long enough to line the two up (overall offset, then 15 s
  stretches matched one by one and a straight line fitted through the ones that agree; at least 60% must
  agree, which rejects charts of a different edit or recording) and then thrown away; only the notes are
  kept, in our audio's time. `analyze.py charts` looks for charts for songs analysed before this
  existed (`--force` looks again). Charted beats sit ~40 ms before our beat grids, as `strips.LEAD`
  assumes.
- **Editor** (`pc/editor.py`, `editor.bat`): a page on the PC for fixing a song by ear. Plays the song with
  a click track on the beat grid (high click on bar 1); tap along with T for ~20 s, then "New grid from my
  taps" fits a steady tempo to the taps and lines it up exactly with the audio for the whole song (taps
  alone drift 50-300 ms by the end); H moves the grid half a beat (clicks between the beats), G refits a
  steady grid from the audio; nudge it 10 ms at a time; tempo x2 / /2; set bar 1 (B), drops (D), build-up starts (U), lifts (L) and
  sections (S); per drop, its build-up (Build-up panel): where it starts (bars before the drop), the speed the
  pulses fire at (speed changes "from N bars before the drop: R per beat", once a bar up to 8 per beat), in
  steps or speeding up smoothly; cyan ticks under the waveform show exactly where each pulse fires
  (`strips.buildFirings`, matched by `firings` in the page) and they can be clicked along with the song.
  Without settings: 1 a beat, 2 from halfway, 4 for the last fifth. Pulses count back from the beat
  nearest the drop, so they stay on the beat. Strip effects at a mark (Strip effects panel, keys F and
  O; `effects` in the analysis, each {type, time, end}): a fade-out (the strips fade to black over its
  length, to the end of the song unless shortened, then stay dark, drops included) and 'balls' (balls
  bounce and collide, flashing white when they hit, a new one dropping into the biggest gap on the beat
  until they fill the strips by its end; `strips.Balls`, simulated in fixed steps from the effect's start
  so it always plays the same; by default it runs to the next drop if one is within 32 bars). Per
  section: label, chorus, strip pattern (chart notes, pulses, breathe, chase, sparkle,
  rainbow, solid, strobe, off) and colours. The strip preview follows the chart's notes when there is one. Save sends it to the Pi, which reloads it within seconds;
  hand-edited songs are never overwritten by the automatic analysis.
- **`beatsync.py`**: the beat clock. Song time = Spotify's position + an offset, measured by matching the
  bass hits WLED's microphone hears (its UDP audio sync, multicast 239.0.0.1:11988, "send" mode) against
  the song's bass envelope every second; that covers the Bluetooth speaker's delay and Spotify's
  polling error. Spotify's position is the median over its last 15 polls. The offset is mostly the
  speaker's delay, the same for every song, so the room's usual offset is learned (`beats/room.json`)
  and a song's match is only accepted within 0.4 beat of it (a match a whole beat off can look almost as
  good). `MIC_LATENCY` is WLED's own delay. `beattest.py` shows a plain metronome for checking it.
- **Matrix**: every beat-synced effect uses the real beat (`effects.BEAT`, bar lines on multiples of 4);
  a drop gives one white hit. Without an analysis they count 120 BPM as before.
- **`strips.py`**: draws both strips (by distance from the matrix) and streams them to WLED over DDP.
  Pulses leave the matrix on each beat, coloured by the melody note (repeated melodies repeat colours),
  with a palette per section label (the chorus is always pink/orange); build-ups rush in from the
  far ends, faster and whiter. Songs with a chart play its notes instead (pattern `notes`, the default
  for them): each guitar note (else keys / bass) leaves the matrix as a pulse coloured by its lane, held
  notes trail a streak while held, kicks swell the strip near the matrix, snares lift the whole strip
  (each at most ~3 a second, `beatsync.ACCENT_GAP`), hi-hats and cymbals sparkle; stretches the chart
  leaves empty fall back to beat pulses. Both strips have 224 LEDs (WLED outputs 0-223 and 224-447),
  fed from the far end; the last LEDs at the matrix end curve onto the other wall and stay dark, so the
  lights start from the corner (strip 1 lit up to LED 207, strip 2 up to 205: `STRIPS`). WLED's segments
  and presets cover the same LEDs. Everything sits on a steady glow in the section's colours (`AMBIENT`)
  with the effects scaled down (`OVERLAY`) and through a soft limiter (`CEILING`), so pulses peak at about
  3x the glow instead of full white on black; build-ups climb back to full contrast by the drop. Quiet
  sections (energy under `CALM_BELOW`) get a calm pattern (`drift`) unless one is set in the editor;
  calm patterns: `drift` (long colour bands drifting outward), `waves` (a soft wide wave each bar),
  `aurora` (slow shimmering curtains). A drop is a white hit then a strobe on the beat for
  `DROP_STROBE_BARS` bars, never above `MAX_FLASHES` a second. With no analysis, or paused, it stops
  sending and WLED's own audio-reactive playlist (preset 20) takes over again.

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

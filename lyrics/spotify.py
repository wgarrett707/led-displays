# Spotify Web API access for the lyrics display: token refresh and current playback.
import json
import os
import time
import requests

TOKEN_URL = 'https://accounts.spotify.com/api/token'
PLAYING_URL = 'https://api.spotify.com/v1/me/player/currently-playing'
# Spotify can hand out a new refresh token when refreshing; the latest one is kept here
TOKEN_CACHE = '/home/pi/led-scripts/lyrics/spotify_token.json'
PI_UID = 1000


class RateLimited(Exception):
    def __init__(self, seconds):
        Exception.__init__(self, 'rate limited for %d s' % seconds)
        self.seconds = seconds


class Playback:
    # One snapshot of what Spotify is playing, anchored to the local monotonic clock
    def __init__(self, item, progressMs, playing, at):
        self.id = item['id'] or item['uri']
        self.title = item['name']
        self.artists = [a['name'] for a in item['artists']]
        self.album = item['album']['name']
        self.durationMs = item['duration_ms']
        self.progressMs = progressMs
        self.playing = playing
        self.at = at

    def position(self, now):
        # Estimated playback position (ms) at local time 'now'
        if not self.playing:
            return self.progressMs
        return min(self.durationMs, self.progressMs + (now - self.at) * 1000)


class Spotify:
    def __init__(self, keys):
        self.clientId = keys['spotify_client_id']
        self.clientSecret = keys['spotify_client_secret']
        self.refreshToken = keys['spotify_refresh_token']
        try:
            with open(TOKEN_CACHE) as f:
                self.refreshToken = json.load(f)['refresh_token']
        except (OSError, ValueError, KeyError):
            pass
        self.accessToken = None
        self.expires = 0
        self.session = requests.Session()

    def _refresh(self):
        r = self.session.post(TOKEN_URL, timeout=10, auth=(self.clientId, self.clientSecret),
                              data={'grant_type': 'refresh_token', 'refresh_token': self.refreshToken})
        r.raise_for_status()
        j = r.json()
        self.accessToken = j['access_token']
        self.expires = time.monotonic() + j.get('expires_in', 3600)
        if j.get('refresh_token') and j['refresh_token'] != self.refreshToken:
            self.refreshToken = j['refresh_token']
            self._saveRefreshToken()

    def _saveRefreshToken(self):
        tmp = TOKEN_CACHE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'refresh_token': self.refreshToken}, f)
        os.chmod(tmp, 0o600)
        if os.geteuid() == 0:
            os.chown(tmp, PI_UID, PI_UID)
        os.replace(tmp, TOKEN_CACHE)

    def currentlyPlaying(self):
        # Returns a Playback, or None when nothing (or a podcast/ad) is playing
        if time.monotonic() > self.expires - 60:
            self._refresh()
        for attempt in range(2):
            sent = time.monotonic()
            r = self.session.get(PLAYING_URL, timeout=5,
                                 headers={'Authorization': 'Bearer ' + self.accessToken})
            received = time.monotonic()
            if r.status_code == 401 and attempt == 0:
                self._refresh()
                continue
            break
        if r.status_code == 429:
            raise RateLimited(int(r.headers.get('Retry-After', '30')))
        if r.status_code == 204 or not r.content:
            return None
        r.raise_for_status()
        j = r.json()
        item = j.get('item')
        if not item or j.get('currently_playing_type') != 'track':
            return None
        # The position was measured somewhere during the request; assume the middle
        return Playback(item, j.get('progress_ms') or 0, j.get('is_playing', False), (sent + received) / 2)

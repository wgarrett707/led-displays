"""One-time Spotify login for the LED lyrics display.

Run this on your PC (not the Pi), in your own terminal:

    python spotify_auth.py

It asks for your Spotify app's Client ID and Client Secret, opens Spotify's login page in your
browser, and saves the resulting tokens into apikeys.json on the Pi over SSH. Nothing secret is
printed. Needs Python 3.6+ and the same SSH key access to the Pi that you already have.
"""
import base64
import getpass
import http.server
import json
import secrets
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

PI = 'pi@10.0.0.146'
# Not 8888: Jupyter and VS Code commonly hold that port
PORT = 8765
REDIRECT_URI = 'http://127.0.0.1:%d/callback' % PORT
SCOPES = 'user-read-currently-playing user-read-playback-state'

# Runs on the Pi: merges the JSON from stdin into apikeys.json (kept private to the pi user)
# and drops any refresh token cached from a previous login.
MERGE_ON_PI = r'''
import json, os, sys
path = "/home/pi/led-scripts/apikeys.json"
keys = json.load(open(path))
keys.update(json.load(sys.stdin))
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(keys, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
try:
    os.remove("/home/pi/led-scripts/lyrics/spotify_token.json")
except OSError:
    pass
print("Saved Spotify login to apikeys.json on the Pi.")
'''


def main():
    state = secrets.token_urlsafe(16)
    result = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != '/callback':
                self.send_response(404)
                self.end_headers()
                return
            if query.get('state', [''])[0] != state:
                result['error'] = 'state mismatch'
            elif 'error' in query:
                result['error'] = query['error'][0]
            else:
                result['code'] = query.get('code', [''])[0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            message = 'Done - you can close this tab.' if 'code' in result else 'Login failed: ' + result['error']
            self.wfile.write(('<h2>' + message + '</h2>').encode())

        def log_message(self, *args):
            pass

    # Claim the port before printing any address: VS Code's terminal auto-forwards ports it sees
    # in output, and would grab this one first.
    try:
        server = http.server.HTTPServer(('127.0.0.1', PORT), Callback)
    except OSError as e:
        sys.exit('Could not open port %d (%s).\nSomething else holds it - often VS Code port forwarding: '
                 'stop it in VS Code\'s Ports panel, or run this from a normal PowerShell window.' % (PORT, e))

    print('Spotify app settings: https://developer.spotify.com/dashboard')
    print('The app needs this Redirect URI: ' + REDIRECT_URI + '\n')
    clientId = input('Client ID: ').strip()
    clientSecret = getpass.getpass('Client Secret (hidden): ').strip()
    if not clientId or not clientSecret:
        sys.exit('Both are required.')

    url ='https://accounts.spotify.com/authorize?' + urllib.parse.urlencode({
        'client_id': clientId, 'response_type': 'code', 'redirect_uri': REDIRECT_URI,
        'scope': SCOPES, 'state': state})
    print('\nOpening Spotify login in your browser. If it does not open, visit:\n' + url + '\n')
    webbrowser.open(url)
    while not result:
        server.handle_request()
    server.server_close()
    if 'error' in result:
        sys.exit('Login failed: ' + result['error'])

    request = urllib.request.Request(
        'https://accounts.spotify.com/api/token',
        data=urllib.parse.urlencode({'grant_type': 'authorization_code', 'code': result['code'],
                                     'redirect_uri': REDIRECT_URI}).encode(),
        headers={'Authorization': 'Basic ' + base64.b64encode((clientId + ':' + clientSecret).encode()).decode(),
                 'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request, timeout=15) as response:
        tokens = json.load(response)

    payload = json.dumps({'spotify_client_id': clientId, 'spotify_client_secret': clientSecret,
                          'spotify_refresh_token': tokens['refresh_token']})
    saved = subprocess.run(['ssh', PI, 'python3 -c ' + shlex.quote(MERGE_ON_PI)],
                           input=payload, universal_newlines=True)
    if saved.returncode != 0:
        sys.exit('Could not save to the Pi over SSH (exit code %d).' % saved.returncode)

    # Quick check that the token can read playback
    check = urllib.request.Request('https://api.spotify.com/v1/me/player/currently-playing',
                                   headers={'Authorization': 'Bearer ' + tokens['access_token']})
    try:
        with urllib.request.urlopen(check, timeout=15) as response:
            body = response.read()
    except Exception as e:
        print('Saved, but reading playback failed: %s' % e)
        return
    if body:
        item = json.loads(body).get('item') or {}
        print('Spotify login works. Currently playing: %s - %s' % (
            ', '.join(a['name'] for a in item.get('artists', [])), item.get('name', '(nothing)')))
    else:
        print('Spotify login works (nothing playing right now).')


if __name__ == '__main__':
    main()

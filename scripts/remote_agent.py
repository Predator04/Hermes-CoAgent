"""Remote CoAgent - lightweight remote desktop agent (auth required)"""
import http.server
import json
import io
import subprocess
import os
import sys
import secrets
import shlex
from PIL import ImageGrab
PORT = 19124
BIND_HOST = "127.0.0.1"  # never expose to network without auth
MAX_BODY = 1 * 1024 * 1024  # 1 MB max request body

# Auth: read token from env or file, generate if neither exists
_TOKEN = None

def _get_token():
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    tok = (os.environ.get("REMOTE_AGENT_TOKEN") or "").strip()
    if tok:
        _TOKEN = tok
        return _TOKEN
    token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".remote_token")
    # Prefer an existing token (another process may have created it).
    try:
        with open(token_file) as f:
            tok = f.read().strip()
    except OSError:
        tok = ""
    if not tok:
        # Generate a fresh token atomically with restrictive permissions.
        tok = secrets.token_hex(32)
        try:
            fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Lost a race with a concurrent start — adopt the on-disk token.
            try:
                with open(token_file) as f:
                    tok = f.read().strip()
            except OSError:
                tok = ""
        else:
            with os.fdopen(fd, "w") as f:
                f.write(tok)
    _TOKEN = tok
    return _TOKEN

class Handler(http.server.BaseHTTPRequestHandler):
    def _check_auth(self):
        token = self.headers.get("Authorization", "")
        if token.startswith("Bearer "):
            token = token[7:]
        if not token or not secrets.compare_digest(token, _get_token()):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Unauthorized"}')
            return False
        return True

    def do_GET(self):
        try:
            if self.path == "/screen":
                if not self._check_auth(): return
                img = ImageGrab.grab(all_screens=True)
                b = io.BytesIO(); img.save(b, "PNG"); b.seek(0)
                self.send_response(200); self.send_header("Content-Type","image/png"); self.end_headers()
                self.wfile.write(b.getvalue())
            elif self.path == "/info":
                if not self._check_auth(): return
                self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
                self.wfile.write(json.dumps({"pid":os.getpid(),"host":os.environ.get("COMPUTERNAME",""),"python":sys.version}).encode())
            elif self.path == "/health":
                self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            else:
                self.send_response(404); self.send_header("Content-Type","application/json"); self.end_headers()
        except Exception as e:
            self.send_response(500); self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps({"error":"Internal error"}).encode())

    def do_POST(self):
        try:
            if not self._check_auth(): return

            # Cap body size
            length_str = self.headers.get("Content-Length", "0")
            try:
                length = int(length_str)
            except ValueError:
                self.send_response(400); self.send_header("Content-Type","application/json"); self.end_headers()
                self.wfile.write(b'{"error":"Bad Content-Length"}')
                return
            if length < 0 or length > MAX_BODY:
                self.send_response(413); self.send_header("Content-Type","application/json"); self.end_headers()
                self.wfile.write(b'{"error":"Body too large"}')
                return

            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body) if body else {}

            if self.path == "/exec":
                cmd_str = data.get("cmd", "")
                if not cmd_str:
                    self.send_response(400); self.send_header("Content-Type","application/json"); self.end_headers()
                    self.wfile.write(b'{"error":"cmd required"}')
                    return
                # Parse safely — no shell=True
                try:
                    args = shlex.split(cmd_str, posix=False)
                except ValueError:
                    self.send_response(400); self.send_header("Content-Type","application/json"); self.end_headers()
                    self.wfile.write(b'{"error":"Invalid command"}')
                    return
                r = subprocess.run(args, capture_output=True, text=True, timeout=30)
                self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
                self.wfile.write(json.dumps({"stdout":r.stdout,"stderr":r.stderr,"code":r.returncode}).encode())

            elif self.path == "/launch":
                cmd_str = data.get("cmd", "")
                if not cmd_str:
                    self.send_response(400); self.send_header("Content-Type","application/json"); self.end_headers()
                    self.wfile.write(b'{"error":"cmd required"}')
                    return
                try:
                    args = shlex.split(cmd_str, posix=False)
                except ValueError:
                    self.send_response(400); self.send_header("Content-Type","application/json"); self.end_headers()
                    self.wfile.write(b'{"error":"Invalid command"}')
                    return
                subprocess.Popen(args)
                self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
                self.wfile.write(b'{"ok":true}')

            else:
                self.send_response(404); self.send_header("Content-Type","application/json"); self.end_headers()
        except Exception as e:
            self.send_response(500); self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps({"error":"Internal error"}).encode())

http.server.HTTPServer((BIND_HOST, PORT), Handler).serve_forever()

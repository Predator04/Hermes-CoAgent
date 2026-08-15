"""Remote CoAgent - lightweight remote desktop agent (auth required)"""
import http.server
import json
import io
import subprocess
import os
import sys
import secrets
import shlex
import threading
from PIL import ImageGrab
PORT = 19124
BIND_HOST = "127.0.0.1"  # never expose to network without auth
MAX_BODY = 1 * 1024 * 1024  # 1 MB max request body

# Auth: read token from env or file, generate if neither exists
_TOKEN = None
_TOKEN_LOCK = threading.Lock()

def _get_token():
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    with _TOKEN_LOCK:
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
    def _begin(self):
        self._response_started = False

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self._response_started = True
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code, content_type, body):
        self._response_started = True
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self):
        token = self.headers.get("Authorization", "")
        if token.startswith("Bearer "):
            token = token[7:]
        if not token or not secrets.compare_digest(token, _get_token()):
            self._send_json(401, {"error": "Unauthorized"})
            return False
        return True

    def _fail(self, path, method, exc):
        self.log_error("%s %s failed: %r", method, path, exc)
        if not self._response_started:
            try:
                self._send_json(500, {"error": "Internal error"})
            except Exception:
                pass

    def do_GET(self):
        self._begin()
        try:
            if self.path == "/screen":
                if not self._check_auth(): return
                img = ImageGrab.grab(all_screens=True)
                b = io.BytesIO()
                img.save(b, "PNG")
                self._send_bytes(200, "image/png", b.getvalue())
            elif self.path == "/info":
                if not self._check_auth(): return
                self._send_json(200, {
                    "pid": os.getpid(),
                    "host": os.environ.get("COMPUTERNAME", ""),
                    "python": "%d.%d" % (sys.version_info.major, sys.version_info.minor),
                })
            elif self.path == "/health":
                self._send_json(200, {"status": "ok"})
            else:
                self._send_json(404, {"error": "Not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._fail(self.path, "GET", e)

    def do_POST(self):
        self._begin()
        try:
            if not self._check_auth(): return

            # Cap body size
            length_str = self.headers.get("Content-Length", "0")
            try:
                length = int(length_str)
            except ValueError:
                self._send_json(400, {"error": "Bad Content-Length"})
                return
            if length < 0 or length > MAX_BODY:
                self._send_json(413, {"error": "Body too large"})
                return

            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            if self.path == "/exec":
                cmd_str = data.get("cmd", "")
                if not cmd_str:
                    self._send_json(400, {"error": "cmd required"})
                    return
                # Parse safely — no shell=True
                try:
                    args = shlex.split(cmd_str, posix=False)
                except ValueError:
                    self._send_json(400, {"error": "Invalid command"})
                    return
                try:
                    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
                except subprocess.TimeoutExpired:
                    self._send_json(504, {"error": "Command timed out"})
                    return
                except FileNotFoundError:
                    self._send_json(404, {"error": "Executable not found"})
                    return
                self._send_json(200, {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode})

            elif self.path == "/launch":
                cmd_str = data.get("cmd", "")
                if not cmd_str:
                    self._send_json(400, {"error": "cmd required"})
                    return
                try:
                    args = shlex.split(cmd_str, posix=False)
                except ValueError:
                    self._send_json(400, {"error": "Invalid command"})
                    return
                kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
                if os.name == "posix":
                    kwargs["start_new_session"] = True
                else:
                    kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                try:
                    subprocess.Popen(args, **kwargs)
                except FileNotFoundError:
                    self._send_json(404, {"error": "Executable not found"})
                    return
                self._send_json(200, {"ok": True})

            else:
                self._send_json(404, {"error": "Not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._fail(self.path, "POST", e)

class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

ThreadingHTTPServer((BIND_HOST, PORT), Handler).serve_forever()

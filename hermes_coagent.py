# ════════════════════════════════════════════════════════════════
# HERMES COAGENT v7.3 — PERFORMANCE OPTIMIZATIONS
# ════════════════════════════════════════════════════════════════
"""
Hermes CoAgent — Windows Desktop Co-Pilot (Flask REST + MCP server)
====================================================================
Primary server for the CoAgent desktop automation system.

v7.3: Performance and reliability optimizations on the modular route layout.
v7.3: Codebase split into modular route files:
  shared.py          — Shared utilities (logging, auth, path safety, SSE)
  routes_mouse.py    — Mouse, keyboard, chain, emergency
  routes_ocr.py      — Screenshots, OCR, crop, describe
  routes_uia.py      — UIA tree, SOM overlays, element find
  routes_file.py     — File ops, app launch, power management
  routes_media.py    — Wallpaper, windows, clipboard, macros, scheduler, voice, tunnel

LAUNCH:
  python hermes_coagent.py                    # REST server on :9123
  python hermes_coagent.py --secure           # Auth enabled (random token)
  python hermes_coagent.py --token=KEY        # Auth with fixed token
  python hermes_coagent.py --allow-external   # Bind 0.0.0.0 (requires --secure)
"""
import sys, os, json, subprocess, threading, time, ctypes, traceback
from collections import deque
from datetime import datetime
from html import escape
from pathlib import Path
from dataclasses import dataclass, field
from typing import List
from shutil import which

# Auth module (required: fail closed if unavailable)
try:
    import auth as _auth
    from auth import require_auth as _require_auth, init_auth as _init_auth, register_auth_routes
    import functools
    from flask import g
    def require_auth(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            ap = getattr(g, '_auth_passed', False)
            if ap: return f(*args, **kwargs)
            return _require_auth(f)(*args, **kwargs)
        return wrapper
except Exception as e:
    print(f"[FATAL] auth.py failed to import; refusing to start unprotected: {e}", file=sys.stderr)
    raise

# Platform check
import platform as _platform
if _platform.system() != "Windows":
    print(f"[WARN] Hermes CoAgent is designed for Windows (detected: {_platform.system()})")
    HAS_SENDINPUT = False
else:
    HAS_SENDINPUT = True

os.environ["PYAUTOGUI_FAILSAFE"] = "false"

# ── Shared utilities ──────────────────────────────────────────
from shared import COAGENT_DIR, SERVER_PORT, TRAY_PORT, SERVER_LOG, _console, _log, _json_body
from shared import VERSION, AGENT_NAME, BUILD

# ── Flask setup ────────────────────────────────────────────────
from flask import Flask, request, jsonify, send_file, Response, g
import waitress

app = Flask(__name__, static_folder=None)

# ── v7.3: Single-source version ────────────────────────────────

# ── v7.3: Security middleware ───────────────────────────────────
AUTH_EXEMPT_PREFIXES = (
    "/auth/",
    "/static/",
    "/screen",
    "/ocr",
    "/visual",
    "/crop",
    "/describe",
    "/uia",
    "/som",
    "/monitors",
    "/stats",
    "/history",
    "/events",
)
AUTH_EXEMPT_PATHS = {
    "/",
    "/dashboard2",
    "/index.html",
    "/health",
    "/ping",
    "/version",
    "/favicon.ico",
    "/mcp/test",
    "/logs",
    "/screen",
    "/screen/jpeg",
    "/screen/base64",
    "/screen/fresh",
    "/screen/diag",
    "/screen/probe",
    "/monitors",
    "/stats",
    "/history",
    "/events",
    "/features",
    "/cursor/status",
    "/recording/status",
    "/uia/diag",
    "/som/cache/clear",
}

def _is_auth_exempt(path):
    if path in AUTH_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)

@app.before_request
def _auth_gate():
    if _is_auth_exempt(request.path):
        return None
    result = _require_auth(lambda: None)()
    if result is not None:
        return result
    g._auth_passed = True
    return None

@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Cache-Control"] = "no-store"
    return response

# ── v7.3: CORS support for dashboard ───────────────────────────
@app.after_request
def _cors_headers(response):
    origin = request.headers.get("Origin", "")
    allow = {
        "http://localhost:9123", "http://127.0.0.1:9123",
        "http://172.21.192.1:9123",
    }
    if origin in allow:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response

@app.before_request
def _cors_preflight():
    if request.method == "OPTIONS":
        resp = jsonify({"status": "ok"})
        origin = request.headers.get("Origin", "")
        if origin in {"http://localhost:9123", "http://127.0.0.1:9123",
                       "http://172.21.192.1:9123"}:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

# ── v7.3: Request body size enforcement ──────────────────────
_MAX_BODY_SIZE = 16 * 1024 * 1024  # 16 MB

@app.before_request
def _check_body_size():
    if request.content_length and request.content_length > _MAX_BODY_SIZE:
        return jsonify({"error": "Payload too large", "max_bytes": _MAX_BODY_SIZE}), 413

# ── v7.3: Rate limiter (simple token bucket with TTL cleanup) ───
_RATE_LIMITS = {}  # ip -> (tokens, last_refill)
_RATE_MAX_TOKENS = 60
_RATE_REFILL_PER_SEC = 10
_RATE_LOCK = threading.Lock()
_RATE_CLEANUP_INTERVAL = 300  # 5 min

def _rate_cleanup():
    """Evict stale entries every 5 minutes to prevent memory leak."""
    while True:
        time.sleep(_RATE_CLEANUP_INTERVAL)
        now = time.time()
        with _RATE_LOCK:
            stale = [ip for ip, (_, last) in _RATE_LIMITS.items()
                     if now - last > _RATE_CLEANUP_INTERVAL * 2]
            for ip in stale:
                del _RATE_LIMITS[ip]

threading.Thread(target=_rate_cleanup, daemon=True).start()

def _check_rate_limit() -> bool:
    ip = request.remote_addr or "unknown"
    now = time.time()
    with _RATE_LOCK:
        entry = _RATE_LIMITS.get(ip)
        if entry is None:
            _RATE_LIMITS[ip] = (_RATE_MAX_TOKENS - 1, now)
            return True
        tokens, last = entry
        refill = _RATE_REFILL_PER_SEC * (now - last)
        tokens = min(_RATE_MAX_TOKENS, tokens + refill)
        if tokens < 1:
            return False
        _RATE_LIMITS[ip] = (tokens - 1, now)
        return True

@app.before_request
def _rate_limit():
    if request.path in AUTH_EXEMPT_PATHS or request.path.startswith("/auth/"):
        return None
    if not _check_rate_limit():
        return jsonify({"error": "Too many requests",
                        "retry_after": f"{1/_RATE_REFILL_PER_SEC:.1f}s"}), 429

# Global error handlers
@app.errorhandler(400)
def _h400(e): return jsonify({"error": "Bad request", "detail": str(e)}), 400
@app.errorhandler(401)
def _h401(e): return jsonify({"error": "Unauthorized", "detail": str(e)}), 401
@app.errorhandler(403)
def _h403(e): return jsonify({"error": "Forbidden", "detail": str(e)}), 403
@app.errorhandler(404)
def _h404(e): return jsonify({"error": "Not found", "path": request.path}), 404
@app.errorhandler(405)
def _h405(e): return jsonify({"error": "Method not allowed", "method": request.method, "path": request.path}), 405
@app.errorhandler(413)
def _h413(e): return jsonify({"error": "Payload too large", "max_mb": 16}), 413
@app.errorhandler(429)
def _h429(e): return jsonify({"error": "Too many requests"}), 429
@app.errorhandler(500)
def _h500(e): _log(f"[500] Internal error: {e}"); return jsonify({"error": "Internal server error"}), 500
@app.errorhandler(Exception)
def _h_exc(e):
    _log(f"[UNHANDLED] {type(e).__name__}: {e}")
    traceback.print_exc()
    return jsonify({"error": "Internal error", "type": type(e).__name__, "detail": str(e)[:200]}), 500

# v6.4: Singleton mutex
_MUTEX_NAME = "HermesCoAgent_Instance"
try:
    _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:
        _console("[FATAL] Another CoAgent instance is already running. Killing old instance...")
        subprocess.run(["taskkill", "/IM", "pythonw.exe", "/FI", "WINDOWTITLE eq *Hermes*"],
                       capture_output=True, timeout=5)
        time.sleep(1)
except: pass

# ── State ──────────────────────────────────────────────────────
@dataclass
class CoPilotState:
    emergency_stop: bool = False
    input_lock: threading.Lock = field(default_factory=threading.Lock)
    last_action_time: float = 0.0
    min_action_gap: float = 0.05
    action_history: List[dict] = field(default_factory=list)
    max_history: int = 1000
    start_time: float = field(default_factory=time.time)

state = CoPilotState()

# ── Register route modules ─────────────────────────────────────
from routes_mouse import register_routes as reg_mouse
from routes_ocr import register_routes as reg_ocr
from routes_uia import register_routes as reg_uia
from routes_file import register_routes as reg_file
from routes_media import register_routes as reg_media
from routes_v63 import register_routes as reg_v63

reg_mouse(app, state, require_auth)
reg_ocr(app, state, require_auth)
reg_uia(app, state, require_auth)
reg_file(app, state, require_auth)
reg_media(app, state, require_auth)
reg_v63(app, state, require_auth)

# ── Core routes (stay in main) ─────────────────────────────────
@app.route("/", methods=["GET"])
def route_index():
    return jsonify({"agent": AGENT_NAME, "version": VERSION, "status": "running",
                    "features": ["modular_routes", "sse", "sse_mcp", "health_watchdog",
                                 "thread_pool_4", "mss_dxgi", "uia_window_timeout",
                                 "log_rotation_5mb", "recording_cleanup",
                                 "windows_ocr", "uia", "som", "waitress", "watchdog"]})

@app.route("/ping", methods=["GET"])
def route_ping():
    return jsonify({"status": "pong", "agent": f"{AGENT_NAME} v{VERSION}",
                    "uptime": int(time.time() - state.start_time)})

@app.route("/health", methods=["GET"])
def route_health():
    return jsonify({"status": "ok", "agent": AGENT_NAME, "version": VERSION})

@app.route("/version", methods=["GET"])
def route_version():
    return jsonify({"agent": AGENT_NAME, "version": VERSION, "build": BUILD,
                    "features": ["modular_routes", "sse", "sse_mcp", "health_watchdog",
                                 "waitress_wsgi", "mss_dxgi", "uia_window_timeout",
                                 "log_rotation_5mb", "recording_cleanup", "windows_ocr", "uia",
                                 "som", "background_input", "chain_actions", "macro_recorder",
                                 "scheduler", "tunnel", "voice", "session_recording",
                                 "agent_cursor", "element_indexed_uia", "desktop_stabilization",
                                 "file_search", "clipboard", "tts", "rate_limit", "cors",
                                 "security_headers"],
                    "modules": ["mouse", "ocr", "uia", "file", "media", "v63"],
                    "security": ["auth_token", "rate_limit", "input_sanitization",
                                 "cors_restricted", "security_headers"]})

@app.route("/dashboard2", methods=["GET"])
@require_auth
def route_dashboard2():
    try:
        html = Path(COAGENT_DIR / "dashboard.html").read_text(encoding="utf-8")
        return Response(html, mimetype="text/html")
    except: return jsonify({"error": "dashboard.html not found"}), 404

@app.route("/index.html", methods=["GET"])
@require_auth
def route_index_html():
    return route_dashboard2()

@app.route("/mcp/test", methods=["GET"])
@require_auth
def route_mcp_test():
    return jsonify({"status": "mcp_test", "server": AGENT_NAME, "version": VERSION})

register_auth_routes(app)

# ── Short alias routes for MCP compatibility ──────────────────
_short_routes = {
    "/screenshot": "_screen_b64_proxy",
    "/click": "_mouse_click_proxy",
    "/move": "_mouse_move_proxy",
    "/type": "_key_type_proxy",
    "/hotkey": "_key_press_proxy",
    "/scroll": "_mouse_scroll_proxy",
    "/drag": "_mouse_drag_proxy",
    "/activate": "_win_activate_proxy",
    "/cursor": "_cursor_proxy",
    "/screensize": "_monitors_proxy",
    "/uia-click": "_uia_click_proxy",
    "/uia-find": "_uia_find_proxy",
    "/uia-tree": "_uia_tree_proxy",
    "/wait-ui": "_wait_element_proxy",
    "/stabilize": "_stabilize_proxy",
    "/record-start": "_rec_start_proxy",
    "/record-stop": "_rec_stop_proxy",
    "/record-status": "_rec_status_proxy",
    "/cursor-enable": "_cursor_enable_proxy",
    "/cursor-style": "_cursor_style_proxy",
}

def _proxy_get(path): return lambda: jsonify({"proxy": path, "endpoint": f"use HTTP directly"})

for _route, _handler_name in list(_short_routes.items()):
    _ep = _route.lstrip("/").replace("/", "_") or "root"
    app.route(_route, endpoint=_ep)(_proxy_get(_route))

# ── System Tray Icon ──────────────────────────────────────────
def _start_tray():
    try:
        def _ps_quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        tray_script = COAGENT_DIR / "tray_icon.py"
        if not tray_script.exists():
            _console("  [INFO] tray_icon.py not found, skip tray icon")
            return
        pyw_candidates = [
            r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe",
            r"C:\Users\Admin\AppData\Local\Programs\Python\Python312\pythonw.exe",
            str(Path(sys.executable).with_name("pythonw.exe")),
            which("pythonw.exe"),
        ]
        pyw = next((p for p in pyw_candidates if p and Path(p).exists()), None)
        if not pyw:
            _console("  [INFO] Tray icon skipped: pythonw.exe not found")
            return
        task_name = "HermesCoAgent_Tray"
        tray_args = f'"{tray_script}" {SERVER_PORT} {TRAY_PORT}'
        tray_cmd = f'"{pyw}" {tray_args}'
        create_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                       capture_output=True, timeout=5, creationflags=create_flags)
        r = subprocess.run([
            "schtasks", "/Create",
            "/TN", task_name,
            "/TR", tray_cmd,
            "/SC", "ONCE",
            "/ST", "23:59",
            "/RL", "HIGHEST",
            "/IT",
            "/F",
        ], capture_output=True, text=True, timeout=10, creationflags=create_flags)
        if r.returncode == 0:
            subprocess.run(["schtasks", "/Run", "/TN", task_name],
                           capture_output=True, text=True, timeout=10, creationflags=create_flags)
            _console("  [OK] System Tray Icon launched on Session 1 via /IT task")
        else:
            _console(f"  [INFO] schtasks failed ({r.stderr.strip()[:160]}), using hidden Start-Process fallback")
            ps_cmd = (
                "Start-Process "
                f"-FilePath {_ps_quote(pyw)} "
                f"-ArgumentList {_ps_quote(tray_args)} "
                f"-WorkingDirectory {_ps_quote(str(COAGENT_DIR))} "
                "-WindowStyle Hidden"
            )
            subprocess.Popen([
                "powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd
            ], cwd=str(COAGENT_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               creationflags=create_flags)
            _console("  [OK] System Tray Icon launched via hidden PowerShell Start-Process")
    except Exception as e:
        _console(f"  [INFO] Tray icon skipped: {e}")

# ── Log viewer ────────────────────────────────────────────────
@app.route("/logs", methods=["GET"])
@require_auth
def route_logs():
    try:
        lines_raw = request.args.get("lines", "100")
        limit = max(1, min(int(lines_raw), 500))
    except (TypeError, ValueError):
        limit = 100
    if SERVER_LOG.exists():
        try:
            with SERVER_LOG.open("r", encoding="utf-8", errors="replace") as f:
                last_n = "".join(deque(f, maxlen=limit))
            return Response(f"<pre>{escape(last_n)}</pre>", mimetype="text/html")
        except:
            return jsonify({"error": "Cannot read log"}), 500
    return jsonify({"log": "No log file"})

# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    _console("╔════════════════════════════════════════════════╗")
    _console(f"║     {AGENT_NAME} v{VERSION} — MODULAR REFACTOR   ║")
    _console("╚════════════════════════════════════════════════╝")
    _console(f"  PID: {os.getpid()}")
    _console(f"  Directory: {COAGENT_DIR}")

    # Parse args
    bind_host = "127.0.0.1"
    port = SERVER_PORT
    if "--allow-external" in sys.argv:
        bind_host = "0.0.0.0"
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])
    has_secure_arg = "--secure" in sys.argv
    has_token_arg = any(a == "--token" or a.startswith("--token=") for a in sys.argv)
    _init_auth(port, COAGENT_DIR)
    auth_enabled = bool(_auth and _auth.AUTH_ENABLED)
    if "--allow-external" in sys.argv:
        if not (has_secure_arg or has_token_arg):
            _console("  [FATAL] --allow-external requires --secure or --token=KEY.")
            sys.exit(1)
        if not auth_enabled:
            _console("  [FATAL] Auth did not initialize; refusing external bind.")
            sys.exit(1)
    if auth_enabled:
        _console("  Auth: enabled")
        _console("  Rate limit: 60 req/s per IP")
        _console("  Security headers: enabled")
        _console("  CORS: restricted to local origins")
    else:
        _console("  Auth: disabled")

    _console(f"  Server: http://{bind_host}:{port}/")
    _console(f"  Modules: mouse ocr uia file media v63")
    _console()

    # Pre-warm UIA engine
    _console("  [OK] Warming up UIA engine...")
    try:
        from routes_uia import _get_uia_engine
        ue = _get_uia_engine()
        if ue.UIA_READY:
            _console("  [OK] UIA engine ready")
    except: pass

    from routes_ocr import _capture_raw
    _capture_raw(force=True)
    _console("  [OK] Screenshot engine warmed")

    # Start tray icon
    _start_tray()

    # v7.3: Waitress WSGI server
    _console(f"  [OK] Waitress WSGI on http://{bind_host}:{port}/")
    waitress.serve(app, host=bind_host, port=port, threads=8, connection_limit=100)

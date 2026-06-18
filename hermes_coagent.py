# ════════════════════════════════════════════════════════════════
# HERMES COAGENT v7.0 — MODULAR REFACTOR
# ════════════════════════════════════════════════════════════════
"""
Hermes CoAgent — Windows Desktop Co-Pilot (Flask REST + MCP server)
====================================================================
Primary server for the CoAgent desktop automation system.

v7.0: Codebase split into modular route files:
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
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

# Auth module (optional)
try:
    from auth import require_auth as _require_auth, init_auth as _init_auth
    import functools
    from flask import g
    def require_auth(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            ap = getattr(g, '_auth_passed', False)
            if ap: return f(*args, **kwargs)
            return _require_auth(f)(*args, **kwargs)
        return wrapper
except ImportError:
    def require_auth(f): return f

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

# ── Flask setup ────────────────────────────────────────────────
from flask import Flask, request, jsonify, send_file, Response, g

app = Flask(__name__, static_folder=None)

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

reg_mouse(app, state, require_auth)
reg_ocr(app, state, require_auth)
reg_uia(app, state, require_auth)
reg_file(app, state, require_auth)
reg_media(app, state, require_auth)

# ── Core routes (stay in main) ─────────────────────────────────
@app.route("/", methods=["GET"])
def route_index():
    return jsonify({"agent": "Hermes CoAgent", "version": "7.0", "status": "running",
                    "features": ["modular_routes", "sse", "mss_screenshots", "windows_ocr",
                                 "uia", "som", "waitress", "watchdog"]})

@app.route("/ping", methods=["GET"])
def route_ping():
    return jsonify({"status": "pong", "agent": "Hermes CoAgent v7.0",
                    "uptime": int(time.time() - state.start_time)})

@app.route("/version", methods=["GET"])
def route_version():
    return jsonify({"agent": "Hermes CoAgent", "version": "7.0", "build": "2026-06-18",
                    "features": ["modular_routes", "sse", "mss_screenshots", "windows_ocr",
                                 "uia", "som", "background_input", "chain_actions",
                                 "macro_recorder", "scheduler", "tunnel", "voice",
                                 "session_recording", "agent_cursor", "element_indexed_uia",
                                 "desktop_stabilization", "file_search", "clipboard", "tts"],
                    "modules": ["mouse", "ocr", "uia", "file", "media"]})

@app.route("/dashboard2", methods=["GET"])
def route_dashboard2():
    try:
        html = Path(COAGENT_DIR / "dashboard.html").read_text(encoding="utf-8")
        return Response(html, mimetype="text/html")
    except: return jsonify({"error": "dashboard.html not found"}), 404

@app.route("/index.html", methods=["GET"])
def route_index_html():
    return route_dashboard2()

@app.route("/mcp/test", methods=["GET"])
def route_mcp_test():
    return jsonify({"status": "mcp_test", "server": "hermes_coagent", "version": "7.0"})

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
        tray_script = COAGENT_DIR / "tray_icon.py"
        if not tray_script.exists():
            _console("  [INFO] tray_icon.py not found, skip tray icon")
            return
        pyw = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe"
        if not Path(pyw).exists():
            _console("  [INFO] Tray icon skipped: pythonw.exe not found")
            return
        task_name = "HermesCoAgent_Tray"
        from shared import _interactive_task_xml
        subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True, timeout=5)
        xml = _interactive_task_xml(
            pyw,
            f'"{tray_script}" {SERVER_PORT} {TRAY_PORT}',
            author="Admin",
            execution_limit="PT0S",
            working_dir=str(COAGENT_DIR),
        )
        xml_path = COAGENT_DIR / "_tray_task.xml"
        xml_path.write_text(xml, encoding="utf-16")
        r = subprocess.run(["schtasks", "/Create", "/XML", str(xml_path), "/TN", task_name, "/F"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            subprocess.run(["schtasks", "/Run", "/TN", task_name], capture_output=True, text=True, timeout=10)
            _console("  [OK] System Tray Icon launched on Session 1")
        else:
            _console("  [INFO] schtasks fallback to direct subprocess")
        if xml_path.exists(): xml_path.unlink()
    except Exception as e:
        _console(f"  [INFO] Tray icon skipped: {e}")

# ── Log viewer ────────────────────────────────────────────────
@app.route("/logs", methods=["GET"])
def route_logs():
    try:
        lines = request.args.get("lines", "100")
        limit = min(int(lines), 500)
    except: limit = 100
    if SERVER_LOG.exists():
        try:
            log_text = SERVER_LOG.read_text(encoding="utf-8", errors="replace")
            log_lines = log_text.split("\n")
            last_n = "\n".join(log_lines[-limit:])
            return Response(f"<pre>{last_n}</pre>", mimetype="text/html")
        except:
            return jsonify({"error": "Cannot read log"}), 500
    return jsonify({"log": "No log file"})

# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    _console("╔════════════════════════════════════════════════╗")
    _console("║     HERMES COAGENT v7.0 — MODULAR REFACTOR   ║")
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
    if "--secure" in sys.argv or "--token" in sys.argv or "--allow-external" in sys.argv:
        _init_auth(port)
        _console("  Auth: enabled")

    _console(f"  Server: http://{bind_host}:{port}/")
    _console(f"  Modules: mouse ocr uia file media")
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

    # v6.4: Waitress WSGI server
    try:
        from waitress import serve
        _console(f"  [OK] Waitress WSGI on http://{bind_host}:{port}/")
        serve(app, host=bind_host, port=port, threads=8, connection_limit=100)
    except ImportError:
        _console("  [WARN] waitress not installed, using Flask dev server")
        app.run(host=bind_host, port=port, debug=False, threaded=True)

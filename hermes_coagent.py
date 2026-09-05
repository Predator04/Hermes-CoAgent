"""
Hermes CoAgent — Windows Desktop Co-Pilot (Flask REST + MCP server)
====================================================================
Primary entry point for the CoAgent desktop automation system.
Registers all modular route blueprints and starts the Flask/MCP server.

v8.1: UI overhaul, screenshot relay, single-instance lock, goal runner progress UI.
v8.0: MCP mode, cross-session memory, hybrid UIA+Vision, HUD overlay.
v7.3: Codebase split into modular route files, performance optimizations.
  shared.py          - Shared utilities (logging, auth, path safety, SSE)
  routes_mouse.py    - Mouse, keyboard, chain, emergency
  routes_ocr.py      - Screenshots, OCR, crop, describe
  routes_uia.py      - UIA tree, SOM overlays, element find
  routes_file.py     - File ops, app launch, power management
  routes_media.py    - Wallpaper, windows, clipboard, macros, scheduler, voice, tunnel

LAUNCH:
  python hermes_coagent.py                    # REST server on :9123
  python hermes_coagent.py --secure           # Auth enabled (random token)
  python hermes_coagent.py --token=KEY        # Auth with fixed token
  python hermes_coagent.py --allow-external   # Bind 0.0.0.0 (requires --secure)
"""
import sys, os, subprocess, threading, time, traceback
import contextlib
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
    # Use auth module's require_auth directly (no g._auth_passed attribute pollution)
    require_auth = _require_auth
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

# Failsafe safety — allow user override via env var
# WARNING: Setting to "true" enables pyautogui's corner-failsafe (top-left corner)
# but prevents reliable automated mouse control from that corner.
os.environ["PYAUTOGUI_FAILSAFE"] = os.environ.get("HERMES_COAGENT_FAILSAFE", "false")

# -- Shared utilities --------------------------------------------
from shared import COAGENT_DIR, SERVER_PORT, TRAY_PORT, SERVER_LOG, _console, _log, _json_body, _self_port, _wrap_registered_blueprint_routes
from shared import PID_FILE
from shared import acquire_single_instance_lock
from shared import VERSION, AGENT_NAME, BUILD

# -- Flask setup --------------------------------------------------
from flask import Flask, request, jsonify, Response
import waitress

app = Flask(__name__, static_folder=None)

ENDPOINT_HEALTH = {}
_ENDPOINT_HEALTH_LOCK = threading.Lock()
_ENDPOINT_HEALTH_THREAD = None
_ENDPOINT_HEALTH_INTERVAL = 60
_ENDPOINT_HEALTH_WINDOW_STARTED = time.time()

def record_endpoint_health(path: str, ok: bool, error: str = ""):
    now = time.time()
    with _ENDPOINT_HEALTH_LOCK:
        entry = ENDPOINT_HEALTH.setdefault(path, {
            "ok": 0,
            "fail": 0,
            "total": 0,
            "last_5min_ok": 0,
            "last_5min_fail": 0,
            "last_error": "",
            "last_time": now,
        })
        entry["total"] += 1
        if ok:
            entry["ok"] += 1
            entry["last_5min_ok"] += 1
        else:
            entry["fail"] += 1
            entry["last_5min_fail"] += 1
            if error:
                entry["last_error"] = error
        entry["last_time"] = now

def _endpoint_health_snapshot():
    _reset_endpoint_health_window_if_needed()
    with _ENDPOINT_HEALTH_LOCK:
        rows = {}
        for path, entry in ENDPOINT_HEALTH.items():
            total = int(entry.get("total", 0))
            ok_count = int(entry.get("ok", 0))
            fail_count = int(entry.get("fail", 0))
            window_total = int(entry.get("last_5min_ok", 0)) + int(entry.get("last_5min_fail", 0))
            rows[path] = {
                **entry,
                "success_rate_pct": round((ok_count / total) * 100, 2) if total else None,
                "failure_rate_pct": round((fail_count / total) * 100, 2) if total else None,
                "last_5min_success_rate_pct": round((entry.get("last_5min_ok", 0) / window_total) * 100, 2)
                if window_total else None,
                "last_5min_failure_rate_pct": round((entry.get("last_5min_fail", 0) / window_total) * 100, 2)
                if window_total else None,
            }
    return rows

def _endpoint_average_success_rate():
    with _ENDPOINT_HEALTH_LOCK:
        ok_count = sum(int(e.get("ok", 0)) for e in ENDPOINT_HEALTH.values())
        total = sum(int(e.get("total", 0)) for e in ENDPOINT_HEALTH.values())
    if total < 5:
        return None
    return round((ok_count / total) * 100, 2)

def _endpoint_failing_last_window():
    failing = []
    with _ENDPOINT_HEALTH_LOCK:
        for path, entry in ENDPOINT_HEALTH.items():
            ok_count = int(entry.get("last_5min_ok", 0))
            fail_count = int(entry.get("last_5min_fail", 0))
            total = ok_count + fail_count
            if total and (fail_count / total) > 0.5:
                failing.append({
                    "path": path,
                    "ok": ok_count,
                    "fail": fail_count,
                    "failure_rate_pct": round((fail_count / total) * 100, 2),
                    "last_error": entry.get("last_error", ""),
                })
    return failing

def _reset_endpoint_health_window_if_needed():
    global _ENDPOINT_HEALTH_WINDOW_STARTED
    now = time.time()
    if now - _ENDPOINT_HEALTH_WINDOW_STARTED < 300:
        return
    with _ENDPOINT_HEALTH_LOCK:
        for entry in ENDPOINT_HEALTH.values():
            entry["last_5min_ok"] = 0
            entry["last_5min_fail"] = 0
        _ENDPOINT_HEALTH_WINDOW_STARTED = now

# -- v7.3: Single-source version ---------------------------------

# -- v7.3: Security middleware -----------------------------------
AUTH_EXEMPT_PREFIXES = (
    "/static/",
)
AUTH_EXEMPT_PATHS = {
    "/",
    "/health",
    "/ping",
    "/version",
    "/favicon.ico",
    "/setup",
    "/setup-status",
    "/auth/dashboard-handoff/exchange",
    "/mobile",
}
_CORS_ALLOWED_ORIGINS = {
    "http://localhost:9123",
    "http://127.0.0.1:9123",
}
# Dynamically add host IP from shared module if resolved
try:
    from shared import HOST_IP
    if HOST_IP:
        _CORS_ALLOWED_ORIGINS.add(f"http://{HOST_IP}:9123")
except ImportError:
    pass
app.config["AUTH_EXEMPT_PREFIXES"] = AUTH_EXEMPT_PREFIXES
app.config["AUTH_EXEMPT_PATHS"] = AUTH_EXEMPT_PATHS

def _is_auth_exempt(path):
    if path in AUTH_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES)

def _ensure_registered_route_auth():
    """Wrap every non-public registered endpoint with require_auth once."""
    for endpoint, view_func in list(app.view_functions.items()):
        if endpoint == "static" or getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        if getattr(view_func, "_hermes_public", False):
            continue
        rules = [rule for rule in app.url_map.iter_rules() if rule.endpoint == endpoint]
        if rules and all(_is_auth_exempt(rule.rule) for rule in rules):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        app.view_functions[endpoint] = wrapped

@app.before_request
def _cors_preflight():
    if request.method == "OPTIONS":
        resp = jsonify({"status": "ok"})
        origin = request.headers.get("Origin", "")
        if origin in _CORS_ALLOWED_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

# Rate-limiting for failed auth attempts (prevents brute-force)
_AUTH_FAILURES: dict[str, list] = {}  # ip -> [timestamps]
_AUTH_FAIL_LOCK = threading.Lock()
_AUTH_FAIL_MAX = 5       # max failures before throttling
_AUTH_FAIL_WINDOW = 30   # seconds

@ app.before_request
def _auth_gate():
    if _is_auth_exempt(request.path):
        return None
    # Endpoints marked _hermes_public opt out of Bearer auth and rely on their own
    # authentication (e.g. the HMAC-signed inbound webhook receive endpoint).
    rule = getattr(request, "url_rule", None)
    if rule is not None and rule.endpoint in app.view_functions:
        if getattr(app.view_functions[rule.endpoint], "_hermes_public", False):
            return None
    result = _require_auth(lambda: None)()
    if result is not None:
        # Track and throttle failed auth attempts
        ip = request.remote_addr or "unknown"
        now = time.time()
        with _AUTH_FAIL_LOCK:
            failures = _AUTH_FAILURES.setdefault(ip, [])
            failures[:] = [t for t in failures if now - t < _AUTH_FAIL_WINDOW]
            failures.append(now)
            should_throttle = len(failures) > _AUTH_FAIL_MAX
        if should_throttle:
            resp = jsonify({"error": "too many failed auth attempts; slow down"})
            resp.status_code = 429
            resp.headers["Retry-After"] = str(_AUTH_FAIL_WINDOW)
            return resp
        return result
    return None

@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Cache-Control"] = "no-store"
    return response

# -- v7.3: CORS support for dashboard ----------------------------
@app.after_request
def _cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin in _CORS_ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response

@app.after_request
def _record_endpoint_health(response):
    try:
        if request.method != "OPTIONS":
            ok = response.status_code < 500
            record_endpoint_health(request.path, ok, "" if ok else f"HTTP {response.status_code}")
    except Exception:
        pass
    return response

# -- v7.3: Request body size enforcement -------------------------
_MAX_BODY_SIZE = 16 * 1024 * 1024  # 16 MB

@app.before_request
def _check_body_size():
    if request.content_length and request.content_length > _MAX_BODY_SIZE:
        return jsonify({"error": "Payload too large", "max_bytes": _MAX_BODY_SIZE}), 413

# -- v7.3: Rate limiter (simple token bucket with TTL cleanup) ---
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
        # Also evict stale auth failure entries
        with _AUTH_FAIL_LOCK:
            stale_ips = [ip for ip, timestamps in _AUTH_FAILURES.items()
                        if not timestamps or now - timestamps[-1] > _AUTH_FAIL_WINDOW * 2]
            for ip in stale_ips:
                del _AUTH_FAILURES[ip]

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
    if request.path in AUTH_EXEMPT_PATHS:
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
    return jsonify({"error": "Internal server error"}), 500

# -- Metrics Collection ---------------------------------------------
_METRICS = {}  # path -> {"hits": int, "times": [float], "statuses": {}}
_METRICS_LOCK = threading.Lock()
_METRICS_MAX_SAMPLES = 100  # keep last 100 response times per endpoint

@app.before_request
def _metrics_start():
    request._metrics_start = time.time()

@app.after_request
def _metrics_record(response):
    if request.method == "OPTIONS":
        return response
    elapsed = (time.time() - getattr(request, "_metrics_start", time.time())) * 1000
    path = request.path
    status = str(response.status_code)
    with _METRICS_LOCK:
        entry = _METRICS.setdefault(path, {"hits": 0, "times": [], "statuses": {}})
        entry["hits"] += 1
        entry["times"].append(elapsed)
        if len(entry["times"]) > _METRICS_MAX_SAMPLES:
            entry["times"] = entry["times"][-_METRICS_MAX_SAMPLES:]
        entry["statuses"][status] = entry["statuses"].get(status, 0) + 1
    return response

# -- State --------------------------------------------------------
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

# Auto-healing watchdog state
_WATCHDOG_INTERVAL = 60
_WATCHDOG_FAILURE_THRESHOLD = 3
_WATCHDOG_LOCK = threading.Lock()
_WATCHDOG_THREAD = None
_WATCHDOG_STATE = {
    "enabled": False,
    "healthy": True,
    "last_check": None,
    "last_status_code": None,
    "failures": 0,
    "consecutive_failures": 0,
    "last_error": None,
    "started_at": None,
    "last_restart": None,
    "restart_attempts": 0,
    "interval_seconds": _WATCHDOG_INTERVAL,
    "failure_threshold": _WATCHDOG_FAILURE_THRESHOLD,
    "url": None,
    "endpoint_average_success_rate": None,
    "endpoint_low_success_checks": 0,
    "memory_growth_mb_5min": 0.0,
}

def _auto_install_package(module_name: str) -> bool:
    """Auto-install a Python package when its module fails to import."""
    _PKG_MAP = {
        "cv2": "opencv-python",
        "numpy": "numpy",
        "psutil": "psutil",
        "winrt": "winrt",
        "PIL": "pillow",
    }
    pkg = _PKG_MAP.get(module_name, module_name)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode == 0
    except Exception:
        return False

try:
    import psutil as _psutil
except ImportError:
    if _auto_install_package("psutil"):
        try:
            import psutil as _psutil
        except ImportError:
            _psutil = None
    else:
        _psutil = None

_MEMORY_LOCK = threading.Lock()
_MEMORY_SAMPLES = deque(maxlen=5)  # 5 min at 60s interval = 300s window
_MEMORY_STATE = {
    "psutil": _psutil is not None,
    "current_rss": 0,
    "current_rss_mb": 0.0,
    "peak_rss": 0,
    "peak_rss_mb": 0.0,
    "growth_mb_5min": 0.0,
    "growth_rate_mb_per_hour": 0.0,
    "samples": [],
}

def _sample_memory():
    if _psutil is None:
        return dict(_MEMORY_STATE)
    now = time.time()
    try:
        rss = int(_psutil.Process(os.getpid()).memory_info().rss)
    except Exception as e:
        with _MEMORY_LOCK:
            _MEMORY_STATE["error"] = f"{type(e).__name__}: {e}"
            return dict(_MEMORY_STATE)
    with _MEMORY_LOCK:
        _MEMORY_SAMPLES.append({"time": now, "rss": rss, "rss_mb": round(rss / (1024 * 1024), 2)})
        samples = list(_MEMORY_SAMPLES)
        peak = max((sample["rss"] for sample in samples), default=rss)
        window = [sample for sample in samples if now - sample["time"] <= 300]
        if len(window) >= 2:
            first = window[0]
            last = window[-1]
            elapsed = max(1.0, last["time"] - first["time"])
            growth_mb = (last["rss"] - first["rss"]) / (1024 * 1024)
            growth_rate = growth_mb * (3600 / elapsed)
        else:
            growth_mb = 0.0
            growth_rate = 0.0
        _MEMORY_STATE.update({
            "psutil": True,
            "current_rss": rss,
            "current_rss_mb": round(rss / (1024 * 1024), 2),
            "peak_rss": peak,
            "peak_rss_mb": round(peak / (1024 * 1024), 2),
            "growth_mb_5min": round(growth_mb, 2),
            "growth_rate_mb_per_hour": round(growth_rate, 2),
            "samples": samples,
        })
        return dict(_MEMORY_STATE)

def _watchdog_update(**updates):
    with _WATCHDOG_LOCK:
        _WATCHDOG_STATE.update(updates)

def _watchdog_ping(port):
    try:
        import urllib.request
        url = f"http://127.0.0.1:{port}/health"
        with urllib.request.urlopen(url, timeout=10) as resp:
            status = getattr(resp, "status", 200)
            return 200 <= status < 300, None, status
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None

def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"

_RESTARTING = False
_RESTARTING_LOCK = threading.Lock()

def _restart_from_watchdog():
    global _RESTARTING
    # Prevent duplicate restarts from concurrent watchdog/health loops
    with _RESTARTING_LOCK:
        if _RESTARTING:
            _log("[WATCHDOG] Restart already in progress; skipping duplicate")
            return
        _RESTARTING = True
    with _WATCHDOG_LOCK:
        _WATCHDOG_STATE["restart_attempts"] += 1
        _WATCHDOG_STATE["last_restart"] = datetime.now().isoformat(timespec="seconds")
    _log("[WATCHDOG] Failure threshold reached; restarting CoAgent")
    # Clean up PID file before exit so replacement process can acquire lock
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass
    create_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    script = str(Path(__file__).resolve())
    args = [script] + sys.argv[1:]
    arg_string = subprocess.list2cmdline(args)
    ps_cmd = (
        "Start-Sleep -Seconds 2; "
        f"Start-Process -FilePath {_ps_quote(sys.executable)} "
        f"-ArgumentList {_ps_quote(arg_string)} "
        f"-WorkingDirectory {_ps_quote(str(COAGENT_DIR))} "
        "-WindowStyle Hidden"
    )
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            cwd=str(COAGENT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=create_flags,
        )
    except Exception as e:
        _watchdog_update(last_error=f"restart failed: {type(e).__name__}: {e}")
        _log(f"[WATCHDOG] Restart launch failed: {type(e).__name__}: {e}")
        with _RESTARTING_LOCK:
            _RESTARTING = False
        return
    time.sleep(1)
    os._exit(75)

def _endpoint_health_loop():
    _log(f"[ENDPOINT_HEALTH] Started; checking every {_ENDPOINT_HEALTH_INTERVAL}s")
    time.sleep(_ENDPOINT_HEALTH_INTERVAL)
    while True:
        failing = _endpoint_failing_last_window()
        if failing:
            summary = ", ".join(
                f"{item['path']}={item['failure_rate_pct']}%" for item in failing[:10]
            )
            _log(f"[ENDPOINT_HEALTH] High endpoint failure rate: {summary}")
        if len(failing) > 3:
            _log("[ENDPOINT_HEALTH] More than 3 endpoints are failing >50%; restarting CoAgent")
            _restart_from_watchdog()
            return
        _reset_endpoint_health_window_if_needed()
        time.sleep(_ENDPOINT_HEALTH_INTERVAL)

def _start_endpoint_health_monitor():
    global _ENDPOINT_HEALTH_THREAD
    if _ENDPOINT_HEALTH_THREAD and _ENDPOINT_HEALTH_THREAD.is_alive():
        return
    _ENDPOINT_HEALTH_THREAD = threading.Thread(
        target=_endpoint_health_loop,
        name="endpoint-health",
        daemon=True,
    )
    _ENDPOINT_HEALTH_THREAD.start()

def _watchdog_loop(port):
    url = f"http://127.0.0.1:{port}/health"
    _watchdog_update(enabled=True, started_at=time.time(), url=url)
    _log(f"[WATCHDOG] Started; checking {url} every {_WATCHDOG_INTERVAL}s")
    time.sleep(10)
    while True:
        ok, error, status_code = _watchdog_ping(port)
        now = datetime.now().isoformat(timespec="seconds")
        with _WATCHDOG_LOCK:
            _WATCHDOG_STATE["last_check"] = now
            _WATCHDOG_STATE["last_status_code"] = status_code
            if ok:
                _WATCHDOG_STATE["healthy"] = True
                _WATCHDOG_STATE["consecutive_failures"] = 0
                _WATCHDOG_STATE["last_error"] = None
                failures = 0
            else:
                _WATCHDOG_STATE["healthy"] = False
                _WATCHDOG_STATE["failures"] += 1
                _WATCHDOG_STATE["consecutive_failures"] += 1
                _WATCHDOG_STATE["last_error"] = error
                failures = _WATCHDOG_STATE["consecutive_failures"]
        if ok:
            _log(f"[WATCHDOG] Health check OK status={status_code}")
        else:
            _log(f"[WATCHDOG] Health check failed ({failures}/{_WATCHDOG_FAILURE_THRESHOLD}): {error}")
            if failures >= _WATCHDOG_FAILURE_THRESHOLD:
                _restart_from_watchdog()
                return
        average_success = _endpoint_average_success_rate()
        memory_state = _sample_memory()
        with _WATCHDOG_LOCK:
            _WATCHDOG_STATE["endpoint_average_success_rate"] = average_success
            if average_success is not None and average_success < 60:
                _WATCHDOG_STATE["endpoint_low_success_checks"] += 1
            else:
                _WATCHDOG_STATE["endpoint_low_success_checks"] = 0
            low_success_checks = _WATCHDOG_STATE["endpoint_low_success_checks"]
            _WATCHDOG_STATE["memory_growth_mb_5min"] = memory_state.get("growth_mb_5min", 0.0)
        if average_success is not None and average_success < 60:
            _log(f"[WATCHDOG] Endpoint average success low: {average_success}% ({low_success_checks}/2)")
            if low_success_checks >= 2:
                _restart_from_watchdog()
                return
        growth_mb = float(memory_state.get("growth_mb_5min") or 0.0)
        if growth_mb > 100:
            _log(f"[WATCHDOG] Memory growth warning: {growth_mb:.2f} MB in 5 minutes")
            if growth_mb > 150:
                _log("[WATCHDOG] Memory growth exceeded restart threshold")
                _restart_from_watchdog()
                return
        time.sleep(_WATCHDOG_INTERVAL)

def _start_watchdog(port):
    global _WATCHDOG_THREAD
    with _WATCHDOG_LOCK:
        if _WATCHDOG_THREAD and _WATCHDOG_THREAD.is_alive():
            return
        _WATCHDOG_THREAD = threading.Thread(target=_watchdog_loop, args=(port,), name="watchdog", daemon=True)
        _WATCHDOG_THREAD.start()


def _start_office_mcp_servers():
    """Background-thread init of Office MCP servers (Excel, Word, PowerPoint).
    These mount MCP servers via npx for document automation capabilities.
    Non-blocking — failures are logged but don't crash the server.
    """
    office_servers = [
        {"name": "excel", "command": "npx", "args": ["-y", "@harismusa/excel-mcp-server"]},
        {"name": "word", "command": "npx", "args": ["-y", "@gongrzhe/office-word-mcp-server"]},
        {"name": "powerpoint", "command": "npx", "args": ["-y", "@gongrzhe/office-powerpoint-mcp-server"]},
    ]

    def _start_one(srv):
        name = srv["name"]
        try:
            _console(f"  [Office MCP] Starting {name}...")
            import subprocess
            proc = subprocess.Popen(
                [srv["command"]] + srv["args"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            # Store for later reference
            if not hasattr(_start_office_mcp_servers, "procs"):
                _start_office_mcp_servers.procs = {}
            _start_office_mcp_servers.procs[name] = proc
            _console(f"  [OK] Office MCP {name} started (PID {proc.pid})")
        except Exception as e:
            _console(f"  [WARN] Office MCP {name} failed: {e}")

    def _start_all():
        for srv in office_servers:
            _start_one(srv)

    t = threading.Thread(target=_start_all, name="office-mcp-init", daemon=True)
    t.start()

# -- Register route modules --------------------------------------
from routes_mouse import register_routes as reg_mouse
from routes_ocr import register_routes as reg_ocr
from routes_uia import register_routes as reg_uia
from routes_file import register_routes as reg_file
from routes_media import register_routes as reg_media
from routes_system import register_routes as reg_system
from routes_keepawake import register_routes as reg_keepawake
from routes_windowsupdate import register_routes as reg_windowsupdate
from routes_screen_translate import register_routes as reg_screen_translate
from routes_diagnostics import register_routes as reg_diagnostics
from routes_layout import register_routes as reg_layout
from routes_webcam import register_routes as reg_webcam
from routes_v63 import register_routes as reg_v63
from routes_stream import register_routes as reg_stream
from routes_process import register_routes as reg_process
from routes_voice import register_routes as reg_voice
from routes_cua import register_routes as reg_cua
from routes_copilot import register_routes as reg_copilot
from routes_buddy import register_routes as reg_buddy
from routes_bypass import register_routes as reg_bypass
from routes_toast import register_routes as reg_toast
from routes_deps import register_routes as reg_deps
from routes_config import register_routes as reg_config, backup_file
from routes_browser import register_routes as reg_browser
from browser_automation import register_routes as reg_browser_automation
from routes_companion import register_routes as reg_companion
from routes_governance import register_routes as reg_governance, enable_observe
from routes_deploy import register_routes as reg_deploy
from routes_stealth_browser import register_routes as reg_stealth_browser
from routes_google import register_routes as reg_google
from routes_logs import register_routes as reg_logs
from routes_recorder import register_routes as reg_recorder
from routes_mcp import register_routes as reg_mcp, run_stdio_server
from routes_mcp_client import register_routes as reg_mcp_client
from routes_git import register_routes as reg_git
from routes_dashboard import register_routes as reg_dashboard
from routes_onboarding import register_routes as reg_onboarding
from routes_obsidian import register_routes as reg_obsidian
from routes_wol import register_routes as reg_wol
from routes_phone import register_routes as reg_phone
from routes_webrtc import register_routes as reg_webrtc
from routes_plugins import register_routes as reg_plugins
from routes_skills import register_routes as reg_skills
from routes_palmreject import register_routes as reg_palmreject
from routes_agent import register_routes as reg_agent
from routes_hybrid_agent import register_routes as reg_hybrid_agent
from routes_hitl_hud import register_routes as reg_hitl_hud
from routes_recovery_daemon import register_routes as reg_recovery_daemon
from routes_discover import register_routes as reg_discover
from routes_humanize import register_routes as reg_humanize
from routes_approvals import register_routes as reg_approvals
from routes_macro_builder import register_routes as reg_macro_builder
from routes_uia_semantic import register_routes as reg_uia_semantic
from routes_semantic_memory import register_routes as reg_semantic_memory
from routes_pii_redact import register_routes as reg_pii_redact
from routes_brainstem import register_routes as reg_brainstem
from routes_com_toolkit import register_routes as reg_com_toolkit
from routes_screen_vision import register_routes as reg_screen_vision
from routes_rag_workspace import register_routes as reg_rag_workspace
from routes_telegram import register_routes as reg_telegram
from routes_memory import register_routes as reg_memory, memory_stats
from routes_reminders import register_routes as reg_reminders
from routes_hud import register_routes as reg_hud
from routes_idle import register_routes as reg_idle

try:
    from routes_pixel import register_routes as reg_pixel
    PIXEL_AVAILABLE = True
except ImportError:
    PIXEL_AVAILABLE = False
    _console("[WARN] routes_pixel.py not found")

try:
    from routes_display import register_routes as reg_display
    DISPLAY_AVAILABLE = True
except ImportError:
    DISPLAY_AVAILABLE = False
    _console("[WARN] routes_display.py not found")

try:
    from routes_recorder_gif import register_routes as reg_recorder_gif
    RECORDER_GIF_AVAILABLE = True
except ImportError:
    RECORDER_GIF_AVAILABLE = False

try:
    from routes_undo import register_routes as reg_undo
    UNDO_AVAILABLE = True
except ImportError:
    UNDO_AVAILABLE = False

try:
    from routes_diff import register_routes as reg_diff
    DIFF_AVAILABLE = True
except ImportError:
    DIFF_AVAILABLE = False

try:
    from routes_finder import register_routes as reg_finder
    FINDER_AVAILABLE = True
except ImportError:
    FINDER_AVAILABLE = False

try:
    from routes_metrics import register_routes as reg_metrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    _console("[WARN] routes_metrics.py not found")

try:
    from routes_docs import register_routes as reg_docs
    DOCS_AVAILABLE = True
except ImportError:
    DOCS_AVAILABLE = False
    _console("[WARN] routes_docs.py not found")

try:
    from routes_updates import register_routes as reg_updates
    UPDATES_AVAILABLE = True
except ImportError:
    UPDATES_AVAILABLE = False
    _console("[WARN] routes_updates.py not found")

try:
    from routes_webhooks import register_routes as reg_webhooks
    WEBHOOKS_AVAILABLE = True
except ImportError:
    WEBHOOKS_AVAILABLE = False
    _console("[WARN] routes_webhooks.py not found")

try:
    from routes_copilot_enhanced import register_routes as reg_copilot_enhanced
    COPILOT_ENHANCED_AVAILABLE = True
except ImportError:
    COPILOT_ENHANCED_AVAILABLE = False
    _console("[WARN] routes_copilot_enhanced.py not found")

try:
    from routes_swarm import register_routes as reg_swarm
    SWARM_AVAILABLE = True
except ImportError:
    SWARM_AVAILABLE = False
    _console("[WARN] routes_swarm.py not found")

try:
    from routes_recipes import register_routes as reg_recipes
    RECIPES_AVAILABLE = True
except ImportError:
    RECIPES_AVAILABLE = False
    _console("[WARN] routes_recipes.py not found")

try:
    from routes_workflows import register_routes as reg_workflows
    WORKFLOWS_AVAILABLE = True
except ImportError:
    WORKFLOWS_AVAILABLE = False
    _console("[WARN] routes_workflows.py not found")

try:
    from routes_recordings import register_routes as reg_recordings
    RECORDINGS_AVAILABLE = True
except ImportError:
    RECORDINGS_AVAILABLE = False
    _console("[WARN] routes_recordings.py not found")

try:
    from routes_phone_memory import register_routes as reg_phone_memory
    PHONE_MEMORY_AVAILABLE = True
except ImportError:
    PHONE_MEMORY_AVAILABLE = False
    _console("[WARN] routes_phone_memory.py not found")

try:
    from routes_healer import register_routes as reg_healer
    HEALER_AVAILABLE = True
except ImportError:
    HEALER_AVAILABLE = False
    _console("[WARN] routes_healer.py not found")

try:
    from routes_browser_final import register_routes as reg_browser_final
    BROWSER_FINAL_AVAILABLE = True
except ImportError:
    BROWSER_FINAL_AVAILABLE = False
    _console("[WARN] routes_browser_final.py not found")

try:
    from routes_mobile import register_routes as reg_mobile
    MOBILE_AVAILABLE = True
except ImportError:
    MOBILE_AVAILABLE = False
    _console("[WARN] routes_mobile.py not found")

try:
    from routes_help import register_routes as reg_help
    HELP_AVAILABLE = True
except ImportError:
    HELP_AVAILABLE = False
    _console("[WARN] routes_help.py not found")

try:
    from routes_cef import register_routes as reg_cef
    CEF_AVAILABLE = True
except ImportError:
    CEF_AVAILABLE = False
    _console("[WARN] routes_cef.py not found")

try:
    from routes_template import register_routes as reg_template
    TEMPLATE_AVAILABLE = True
except ImportError:
    TEMPLATE_AVAILABLE = False
    _console("[WARN] routes_template.py not found")

try:
    from routes_vision import register_routes as reg_vision
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False
    _console("[WARN] routes_vision.py not found")

try:
    from routes_ground import register_routes as reg_ground
    GROUND_AVAILABLE = True
except ImportError:
    GROUND_AVAILABLE = False
    _console("[WARN] routes_ground.py not found")

try:
    from routes_uac import register_routes as reg_uac
    UAC_AVAILABLE = True
except ImportError:
    UAC_AVAILABLE = False
    _console("[WARN] routes_uac.py not found")

try:
    from routes_context import register_routes as reg_context
    CONTEXT_OPTIMIZER_AVAILABLE = True
except ImportError:
    CONTEXT_OPTIMIZER_AVAILABLE = False
    _console("[WARN] routes_context.py not found")

try:
    from routes_trace import register_routes as reg_trace
    TRACE_AVAILABLE = True
except ImportError:
    TRACE_AVAILABLE = False
    _console("[WARN] routes_trace.py not found")

# Telemetry module
try:
    from telemetry import telem_bp, init_telem
    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False
    _console("[WARN] telemetry.py not found")

# Diff capture module
try:
    from diff_capture import diff_bp
    DIFF_CAPTURE_AVAILABLE = True
except ImportError:
    DIFF_CAPTURE_AVAILABLE = False
    _console("[WARN] diff_capture.py not found")

from routes_auto import register_routes as reg_auto
from routes_background import register_routes as reg_background

features = {}

# v8.53: Modules #167..#73 (issues #167,166,165,164,163,162,134,133,132,131,130,129,77,76,75,74,73)
try:
    from routes_background_agent import register_routes as reg_background_agent
except ImportError:
    reg_background_agent = None
    features["background_agent"] = False
try:
    from routes_macro_recorder import register_routes as reg_macro_recorder
except ImportError:
    reg_macro_recorder = None
    features["macro_recorder"] = False

try:
    from routes_app_launcher import register_routes as reg_app_launcher
except ImportError:
    reg_app_launcher = None
    features["app_launcher"] = False
try:
    from routes_uia_table import register_routes as reg_uia_table
except ImportError:
    reg_uia_table = None
    features["uia_table"] = False

try:
    from routes_verify import register_routes as reg_verify
except ImportError:
    reg_verify = None
    features["self_verify"] = False
try:
    from routes_triggers import register_routes as reg_triggers
except ImportError:
    reg_triggers = None
    features["triggers"] = False

try:
    from routes_perception import register_routes as reg_perception
except ImportError:
    reg_perception = None
    features["perception"] = False

try:
    from routes_video import register_routes as reg_video
except ImportError:
    reg_video = None
    features["video_recording"] = False
try:
    from routes_audio_mixer import register_routes as reg_audio_mixer
except ImportError:
    reg_audio_mixer = None
    features["audio_mixer"] = False
try:
    from routes_usb import register_routes as reg_usb
except ImportError:
    reg_usb = None
    features["usb"] = False
try:
    from routes_vlm import register_routes as reg_vlm
except ImportError:
    reg_vlm = None
    features["vlm"] = False
try:
    from routes_resilient import register_routes as reg_resilient
except ImportError:
    reg_resilient = None
    features["resilient_ui"] = False
try:
    from routes_services import register_routes as reg_services
except ImportError:
    reg_services = None
    features["services_and_tasks"] = False
try:
    from routes_vm import register_routes as reg_vm
except ImportError:
    reg_vm = None
    features["hyperv_vm"] = False
try:
    from routes_fused_map import register_routes as reg_fused_map
except ImportError:
    reg_fused_map = None
    features["fused_map"] = False
try:
    from routes_som import register_routes as reg_som
except ImportError:
    reg_som = None
    features["som"] = False
try:
    from routes_agent_tools import register_routes as reg_agent_tools
except ImportError:
    reg_agent_tools = None
    features["agent_tools"] = False
try:
    from routes_session import register_routes as reg_session
except ImportError:
    reg_session = None
    features["session_state"] = False
try:
    from routes_everything import register_routes as reg_everything
except ImportError:
    reg_everything = None
    features["everything_search"] = False
try:
    from routes_print import register_routes as reg_print
except ImportError:
    reg_print = None
    features["print_queue"] = False
try:
    from routes_conpty import register_routes as reg_conpty
except ImportError:
    reg_conpty = None
    features["conpty"] = False
try:
    from routes_notifications import register_routes as reg_notifications
except ImportError:
    reg_notifications = None
    features["notifications"] = False
try:
    from routes_clipboard_history import register_routes as reg_clipboard_history
except ImportError:
    reg_clipboard_history = None
    features["clipboard_history"] = False
try:
    from routes_virtual_desktop import register_routes as reg_virtual_desktop
except ImportError:
    reg_virtual_desktop = None
    features["virtual_desktop"] = False
try:
    from routes_doc_intel import register_routes as reg_doc_intel
except ImportError:
    reg_doc_intel = None
    features["doc_intel"] = False
try:
    from routes_pdf import register_routes as reg_pdf
except ImportError:
    reg_pdf = None
    features["pdf_form_fill"] = False
try:
    from routes_qr import register_routes as reg_qr
except ImportError:
    reg_qr = None
    features["qr_decode"] = False
try:
    from routes_vault import register_routes as reg_vault
except ImportError:
    reg_vault = None
    features["credential_vault"] = False
try:
    from routes_totp import register_routes as reg_totp
except ImportError:
    reg_totp = None
    features["totp_vault"] = False
try:
    from routes_supervisor import register_routes as reg_supervisor
except ImportError:
    reg_supervisor = None
    features["task_supervisor"] = False
try:
    from routes_dragdrop import register_routes as reg_dragdrop
except ImportError:
    reg_dragdrop = None
    features["dragdrop"] = False
try:
    from routes_hw_monitor import register_routes as reg_hw_monitor
except ImportError:
    reg_hw_monitor = None
    features["hw_monitor"] = False
try:
    from routes_eventlog import register_routes as reg_eventlog
except ImportError:
    reg_eventlog = None
    features["eventlog"] = False
try:
    from routes_ngrok import register_routes as reg_ngrok
except ImportError:
    reg_ngrok = None
    features["ngrok_auto_install"] = False
try:
    from routes_env import register_routes as reg_env
except ImportError:
    reg_env = None
    features["env_management"] = False
try:
    from routes_defender import register_routes as reg_defender
except ImportError:
    reg_defender = None
    features["defender_management"] = False
try:
    from routes_startup import register_routes as reg_startup
except ImportError:
    reg_startup = None
    features["startup_management"] = False
try:
    from routes_capture import register_routes as reg_capture
except ImportError:
    reg_capture = None
    features["semantic_capture"] = False
try:
    from routes_benchmark import register_routes as reg_benchmark
except ImportError:
    reg_benchmark = None
    features["benchmark_harness"] = False
try:
    from routes_midrun_steering import reg_midrun_steering
except ImportError:
    reg_midrun_steering = None
    features["midrun_steering"] = False
try:
    from routes_fleet import register_routes as reg_fleet
except ImportError:
    reg_fleet = None
    features["fleet_mode"] = False
try:
    from routes_guard import register_routes as reg_guard
except ImportError:
    reg_guard = None
    features["prompt_guard"] = False
try:
    from routes_checkpoint import register_routes as reg_checkpoint
except ImportError:
    reg_checkpoint = None
    features["safety_checkpoint"] = False
try:
    from routes_organize import register_routes as reg_organize
except ImportError:
    reg_organize = None
    features["file_organizer"] = False
try:
    from routes_office import register_routes as reg_office
except ImportError:
    reg_office = None
    features["office_authoring"] = False
try:
    from routes_scheduler import register_routes as reg_scheduler_tasks
except ImportError:
    reg_scheduler_tasks = None
    features["task_persistence"] = False
try:
    from routes_email import register_routes as reg_email
except ImportError:
    reg_email = None
    features["smtp_imap_email"] = False
try:
    from routes_bluetooth import register_routes as reg_bluetooth
except ImportError:
    reg_bluetooth = None
    features["bluetooth_device_management"] = False

reg_background(app, state, require_auth)
features["background_control"] = True
reg_mouse(app, state, require_auth)
reg_ocr(app, state, require_auth)
features["fullpage_capture"] = True
reg_uia(app, state, require_auth)
reg_file(app, state, require_auth)
reg_media(app, state, require_auth)
reg_system(app, state, require_auth)
reg_keepawake(app, state, require_auth)
reg_windowsupdate(app, state, require_auth)
reg_screen_translate(app, state, require_auth)
reg_webcam(app, jsonify, request, COAGENT_DIR, _log, _json_body, require_auth)
reg_v63(app, state, require_auth)
reg_stream(app, state, require_auth)
reg_process(app, state, require_auth)
reg_voice(app, state, require_auth)
features["voice_stt"] = True
reg_cua(app, state, require_auth)
reg_copilot(app, state, require_auth)
reg_buddy(app, state, require_auth)
reg_bypass(app, state, require_auth)
reg_toast(app, state, require_auth)
reg_deps(app, state, require_auth)
reg_config(app, state, require_auth)
reg_browser(app, state, require_auth)
reg_browser_automation(app, state, require_auth)
reg_companion(app, state, require_auth)
reg_governance(app, state, require_auth)
if CONTEXT_OPTIMIZER_AVAILABLE:
    reg_context(app, state, require_auth)
    features["context_optimizer"] = True
reg_google(app, state, require_auth)
reg_logs(app, state, require_auth)
reg_recorder(app, state, require_auth)
reg_git(app, state, require_auth)
reg_dashboard(app, state, require_auth)
reg_onboarding(app, state, require_auth)
reg_obsidian(app, state, require_auth)
reg_wol(app, state, require_auth)
reg_phone(app, state, require_auth)
reg_webrtc(app, state, require_auth)
reg_plugins(app, state, require_auth)
reg_skills(app, state, require_auth)
reg_palmreject(app, state, require_auth)
reg_agent(app, state, require_auth)
reg_hybrid_agent(app, state, require_auth)
reg_hitl_hud(app, state, require_auth)
reg_recovery_daemon(app, state, require_auth)
reg_discover(app, state, require_auth)
reg_humanize(app, state, require_auth)
reg_approvals(app, state, require_auth)
reg_macro_builder(app, state, require_auth)
reg_uia_semantic(app, state, require_auth)
reg_semantic_memory(app, state, require_auth)
reg_pii_redact(app, state, require_auth)
reg_brainstem(app, state, require_auth)
reg_com_toolkit(app, state, require_auth)
reg_screen_vision(app, state, require_auth)
reg_rag_workspace(app, state, require_auth)
reg_telegram(app, state, require_auth)
reg_mcp(app, state, require_auth)
reg_mcp_client(app, state, require_auth)
reg_idle(app, state, require_auth)
if PIXEL_AVAILABLE:
    reg_pixel(app, state, require_auth)
    features["screen_pixel"] = True
if DISPLAY_AVAILABLE:
    reg_display(app, state, require_auth)
    features["display_topology"] = True
reg_memory(app, state, require_auth)
features["memory"] = True
reg_reminders(app, state, require_auth)
features["reminders"] = True
reg_hud(app, state, require_auth)
features["hud_overlay"] = True
if TELEMETRY_AVAILABLE:
    app.register_blueprint(telem_bp)
    features["telemetry"] = True
    features["telemetry_best_strategy"] = True
    init_telem(str(COAGENT_DIR))
if DIFF_CAPTURE_AVAILABLE:
    app.register_blueprint(diff_bp)
    _wrap_registered_blueprint_routes(app, diff_bp.name, require_auth)
    features["diff_capture"] = True
if RECORDER_GIF_AVAILABLE:
    reg_recorder_gif(app, state, require_auth)
    features["recorder_gif"] = True
if UNDO_AVAILABLE:
    reg_undo(app, state, require_auth)
    features["undo"] = True
if DIFF_AVAILABLE:
    reg_diff(app, state, require_auth)
    features["diff"] = True
if FINDER_AVAILABLE:
    reg_finder(app, state, require_auth)
    features["finder"] = True
if METRICS_AVAILABLE:
    reg_metrics(app, state, require_auth)
    features["metrics"] = True
if DOCS_AVAILABLE:
    reg_docs(app, state, require_auth)
    features["docs"] = True
if UPDATES_AVAILABLE:
    reg_updates(app, state, require_auth)
    features["updates"] = True
if WEBHOOKS_AVAILABLE:
    reg_webhooks(app, state, require_auth)
    features["webhooks"] = True
if COPILOT_ENHANCED_AVAILABLE:
    reg_copilot_enhanced(app, state, require_auth)
    features["copilot_enhanced"] = True
    features["goal_runner_timeline_sse"] = True
    features["loop_stall_detection"] = True
if SWARM_AVAILABLE:
    reg_swarm(app, state, require_auth)
    features["swarm"] = True
if RECIPES_AVAILABLE:
    reg_recipes(app, state, require_auth)
    features["scheduled_recipes"] = True
if WORKFLOWS_AVAILABLE:
    reg_workflows(app, state, require_auth)
    features["visual_workflows"] = True
    features["workflow_variables"] = True
if RECORDINGS_AVAILABLE:
    reg_recordings(app, state, require_auth)
    features["recordings"] = True
if PHONE_MEMORY_AVAILABLE:
    reg_phone_memory(app, state, require_auth)
    features["phone_sequence_memory"] = True
if HEALER_AVAILABLE:
    reg_healer(app, state, require_auth)
    features["self_healing_mode"] = True
if BROWSER_FINAL_AVAILABLE:
    reg_browser_final(app, state, require_auth)
    features["browser_automation_v2"] = True
if MOBILE_AVAILABLE:
    reg_mobile(app, state, require_auth)
    features["mobile_remote_control"] = True
if HELP_AVAILABLE:
    reg_help(app, state, require_auth)
    features["help"] = True
reg_deploy(app, state, require_auth)
features["deploy"] = True
reg_stealth_browser(app, state, require_auth)
features["stealth_browser"] = True
reg_auto(app, state, require_auth)
features["auto_router"] = True

# v8.53 modules
if reg_background_agent:
    reg_background_agent(app, state, require_auth)
    features["background_agent"] = True
if reg_macro_recorder:
    reg_macro_recorder(app, state, require_auth)
    features["macro_recorder"] = True

if reg_app_launcher:
    reg_app_launcher(app, state, require_auth)
    features["app_launcher"] = True
if reg_uia_table:
    reg_uia_table(app, state, require_auth)
    features["uia_table"] = True

if reg_verify:
    reg_verify(app, state, require_auth)
    features["self_verify"] = True
if reg_triggers:
    reg_triggers(app, state, require_auth)
    features["triggers"] = True

if reg_perception:
    reg_perception(app, state, require_auth)
    features["perception"] = True

if reg_video:
    reg_video(app, state, require_auth)
    features["video_recording"] = True
if reg_audio_mixer:
    reg_audio_mixer(app, state, require_auth)
    features["audio_mixer"] = True
if reg_usb:
    reg_usb(app, state, require_auth)
    features["usb"] = True
if reg_vlm:
    reg_vlm(app, state, require_auth)
    features["vlm"] = True
if reg_resilient:
    reg_resilient(app, state, require_auth)
    features["resilient_ui"] = True
if reg_services:
    reg_services(app, state, require_auth)
    features["services_and_tasks"] = True
if reg_fused_map:
    reg_fused_map(app, state, require_auth)
    features["fused_map"] = True
if reg_vm:
    reg_vm(app, state, require_auth)
    features["hyperv_vm"] = True
if reg_som:
    reg_som(app, state, require_auth)
    features["som"] = True
if reg_agent_tools:
    reg_agent_tools(app, state, require_auth)
    features["agent_tools"] = True
if reg_session:
    reg_session(app, state, require_auth)
    features["session_state"] = True
if reg_everything:
    reg_everything(app, state, require_auth)
    features["everything_search"] = True
if reg_print:
    reg_print(app, state, require_auth)
    features["print_queue"] = True
if reg_conpty:
    reg_conpty(app, state, require_auth)
    features["conpty"] = True
if reg_notifications:
    reg_notifications(app, state, require_auth)
    features["notifications"] = True
if reg_clipboard_history:
    reg_clipboard_history(app, state, require_auth)
    features["clipboard_history"] = True
if reg_virtual_desktop:
    reg_virtual_desktop(app, state, require_auth)
    features["virtual_desktop"] = True
if reg_doc_intel:
    reg_doc_intel(app, state, require_auth)
    features["doc_intel"] = True
if reg_pdf:
    reg_pdf(app, state, require_auth)
    features["pdf_form_fill"] = True
if reg_qr:
    reg_qr(app, state, require_auth)
    features["qr_decode"] = True
if reg_vault:
    reg_vault(app, state, require_auth)
    features["credential_vault"] = True
if reg_totp:
    reg_totp(app, state, require_auth)
    features["totp_vault"] = True
if reg_supervisor:
    reg_supervisor(app, state, require_auth)
    features["task_supervisor"] = True
if reg_organize:
    reg_organize(app, state, require_auth)
    features["file_organizer"] = True
if reg_office:
    reg_office(app, state, require_auth)
    features["office_authoring"] = True
if reg_scheduler_tasks:
    reg_scheduler_tasks(app, state, require_auth)
    features["task_persistence"] = True
if reg_dragdrop:
    reg_dragdrop(app, state, require_auth)
    features["dragdrop"] = True
if reg_hw_monitor:
    reg_hw_monitor(app, state, require_auth)
    features["hw_monitor"] = True
if reg_eventlog:
    reg_eventlog(app, state, require_auth)
    features["eventlog"] = True
if reg_ngrok:
    reg_ngrok(app, state, require_auth)
    features["ngrok_auto_install"] = True
if reg_env:
    reg_env(app, state, require_auth)
    features["env_management"] = True
if reg_defender:
    reg_defender(app, state, require_auth)
    features["defender_management"] = True
if reg_startup:
    reg_startup(app, state, require_auth)
    features["startup_management"] = True
if reg_capture:
    reg_capture(app, state, require_auth)
    features["semantic_capture"] = True
if reg_benchmark:
    reg_benchmark(app, state, require_auth)
    features["benchmark_harness"] = True
if reg_midrun_steering:
    reg_midrun_steering(app, state, require_auth)
    features["midrun_steering"] = True
if reg_fleet:
    reg_fleet(app, state, require_auth)
    features["fleet_mode"] = True
if reg_guard:
    reg_guard(app, state, require_auth)
    features["prompt_guard"] = True
if reg_checkpoint:
    reg_checkpoint(app, state, require_auth)
    features["safety_checkpoint"] = True
if reg_email:
    reg_email(app, state, require_auth)
    features["smtp_imap_email"] = True
if reg_bluetooth:
    reg_bluetooth(app, state, require_auth)
    features["bluetooth_device_management"] = True
reg_diagnostics(app, state, require_auth); features["diagnostics"] = True
reg_layout(app, state, require_auth); features["layout_profiles"] = True
if CEF_AVAILABLE:
    reg_cef(app, state, require_auth)
    features["cef_support"] = True
if TEMPLATE_AVAILABLE:
    reg_template(app, state, require_auth)
    features["template_matching"] = True
if VISION_AVAILABLE:
    reg_vision(app, state, require_auth)
    features["vision_detection"] = True
if GROUND_AVAILABLE:
    reg_ground(app, state, require_auth)
    features["grounding_model"] = True
if UAC_AVAILABLE:
    reg_uac(app, state, require_auth)
    features["uac_automation"] = True
if TRACE_AVAILABLE:
    # Registered LAST so wrap_action_endpoints() sees every earlier route.
    reg_trace(app, state, require_auth)
    features["action_tracing"] = True

features["web_dashboard_overhaul"] = True
features["mcp_mode"] = True
features["dom_mode"] = True
features["cross_session_memory"] = True
features["patchright"] = True
features["multi_provider_ai"] = True
features["speculative_batching"] = True
features["browser_undetectable"] = True
features["hybrid_detection"] = True
features["recipe_verification"] = True
features["reminders"] = True
features["hud_overlay"] = True
state.backup_file = backup_file

# -- Core routes (stay in main) ----------------------------------
@app.route("/", methods=["GET"])
def route_index():
    """Root landing page — tunnel-friendly, no auth required."""
    try:
        html = Path(COAGENT_DIR / "dashboard.html").read_text(encoding="utf-8")
        # Redirect to login if no token yet
        return Response(html.replace(
            'let token = (queryToken || sessionStorage.getItem("hermes_token") || sessionStorage.getItem("coagent_token") || "").replace(/^Bearer\\\\s+/i, "");',
            'let token = (queryToken || sessionStorage.getItem("hermes_token") || sessionStorage.getItem("coagent_token") || "").replace(/^Bearer\\s+/i, "");'
        ), mimetype="text/html")
    except Exception:
        return jsonify({"status": "ok", "agent": AGENT_NAME, "version": VERSION, "docs": "/dashboard2"})

@app.route("/ping", methods=["GET"])
def route_ping():
    return jsonify({"status": "pong", "agent": f"{AGENT_NAME} v{VERSION}",
                    "uptime": int(time.time() - state.start_time)})

@app.route("/health", methods=["GET"])
def route_health():
    return jsonify({"status": "ok", "agent": AGENT_NAME, "version": VERSION})

@app.route("/metrics", methods=["GET"])
def route_metrics():
    """Performance metrics — response time percentiles per endpoint."""
    import statistics
    with _METRICS_LOCK:
        summary = {}
        for path, entry in _METRICS.items():
            times = entry["times"]
            if not times:
                continue
            times_sorted = sorted(times)
            n = len(times_sorted)
            summary[path] = {
                "hits": entry["hits"],
                "avg_ms": round(statistics.mean(times), 1),
                "p50_ms": round(times_sorted[int(n * 0.5)], 1),
                "p95_ms": round(times_sorted[int(n * 0.95)], 1),
                "p99_ms": round(times_sorted[int(n * 0.99)], 1) if n > 10 else None,
                "max_ms": round(times_sorted[-1], 1),
                "samples": n,
                "status_codes": entry["statuses"],
            }
    # Sort slowest first
    sorted_summary = dict(sorted(summary.items(), key=lambda x: x[1]["p95_ms"], reverse=True))
    return jsonify({
        "uptime_s": int(time.time() - state.start_time),
        "endpoints_tracked": len(sorted_summary),
        "endpoints": sorted_summary,
    })

@app.route("/health/endpoints", methods=["GET"])
@require_auth
def route_health_endpoints():
    stats = _endpoint_health_snapshot()
    return jsonify({
        "endpoints": stats,
        "count": len(stats),
        "average_success_rate_pct": _endpoint_average_success_rate(),
        "window_started": _ENDPOINT_HEALTH_WINDOW_STARTED,
    })

@app.route("/health/endpoints/reset", methods=["POST"])
@require_auth
def route_health_endpoints_reset():
    global _ENDPOINT_HEALTH_WINDOW_STARTED
    with _ENDPOINT_HEALTH_LOCK:
        ENDPOINT_HEALTH.clear()
        _ENDPOINT_HEALTH_WINDOW_STARTED = time.time()
    return jsonify({"status": "reset"})

@app.route("/health/memory", methods=["GET"])
@require_auth
def route_health_memory():
    with _MEMORY_LOCK:
        payload = dict(_MEMORY_STATE)
    payload["watchdog_thread_alive"] = bool(_WATCHDOG_THREAD and _WATCHDOG_THREAD.is_alive())
    return jsonify(payload)

@app.route("/watchdog/status", methods=["GET"])
@require_auth
def route_watchdog_status():
    with _WATCHDOG_LOCK:
        payload = dict(_WATCHDOG_STATE)
    payload["uptime"] = int(time.time() - state.start_time)
    payload["watchdog_uptime"] = int(time.time() - payload["started_at"]) if payload.get("started_at") else 0
    payload["thread_alive"] = bool(_WATCHDOG_THREAD and _WATCHDOG_THREAD.is_alive())
    return jsonify(payload)

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
                                 "security_headers", "multi_monitor", "screen_streaming",
                                 "process_management", "voice_commands", "auto_healing_watchdog",
                                 "cua_driver", "operator_dashboard", "remote_tunnel",
                                 "ai_copilot", "bypass_toolkit", "dxcam_capture",
                                 "fallback_chains", "endpoint_health_tracker",
                                 "memory_leak_watchdog", "smart_click_retry",
                                 "toast_notifications", "dependency_manager",
                                 "config_backups", "browser_control",
                                 "google_workspace", "log_analyzer",
                                 "recorder", "mcp_server", "git_backup",
                                 "dashboard", "obsidian", "wake_on_lan",
                                 "phone_bridge", "remote_desktop",
                                 "plugin_system", "palm_rejection",
                                 "agent", "agent_gateway", "metrics",
                                 "docs", "updates", "webhooks",
                                 "recorder_gif", "undo", "diff", "finder",
                                 "web_dashboard_overhaul", "copilot_enhanced",
                                 "goal_runner_timeline_sse",
                                 "scheduled_recipes", "self_healing_mode",
                                 "browser_automation_v2", "browser_undetectable",
                                  "mobile_remote_control",
                                 "memory", "cross_session_memory", "sqlite_bm25_memory",
                                 "mcp_mode", "dom_mode", "patchright", "multi_provider_ai",
                                 "speculative_batching", "hybrid_detection",
                                 "recipe_verification", "reminders", "hud_overlay",
                                 "fullpage_capture", "loop_stall_detection", "voice_stt",
                                 "auto_router", "semantic_capture", "benchmark_harness",
                                 "midrun_steering", "fleet_mode", "prompt_guard",
                                 "safety_checkpoint", "perception_snapshot",
                                 "session_state", "file_organizer",
                                 "office_authoring", "task_persistence",
                                 "qr_decode", "credential_vault", "totp_vault", "task_supervisor",
                                 "humanized_typing", "rich_clipboard", "hyperv_vm",
                                 "pdf_form_fill",
                                 "recordings", "workflow_variables", "telemetry_best_strategy",
                                 "phone_sequence_memory", "uia_text_caret_selection",
                                 "smtp_imap_email", "bluetooth_device_management"],
                    "modules": ["mouse", "ocr", "uia", "file", "media", "v63",
                                "stream", "process", "voice", "cua", "copilot",
                                "bypass", "toast", "deps", "config", "browser",
                                "browser_automation", "google", "logs",
                                "recorder", "mcp", "git", "dashboard", "obsidian", "wol",
                                "phone", "webrtc", "plugins", "palmreject", "agent",
                                "metrics", "docs", "updates", "webhooks",
                                "recorder_gif", "undo", "diff", "finder",
                                "copilot_enhanced", "recipes", "healer",
                                "goal_timeline_sse",
                                "browser_v2", "mobile", "memory", "batching", "speculative_batching",
                                "reminders", "hud", "perception", "session",
                                "organize", "office", "scheduler_tasks",
                                "qr", "vault", "totp", "supervisor", "vm", "pdf", "recordings", "phone_memory",
                                "email", "bluetooth"],
                    "memory": memory_stats(),
                    "security": ["auth_token", "rate_limit", "input_sanitization",
                                 "cors_restricted", "security_headers"]})

@app.route("/dashboard2", methods=["GET"])
@require_auth
def route_dashboard2():
    try:
        html = Path(COAGENT_DIR / "dashboard.html").read_text(encoding="utf-8")
        # Inject token into the HTML JS scope so screen/metrics calls work
        import json as _json
        import auth
        safe_token = _json.dumps(auth.AUTH_TOKEN or "")
        html = html.replace(
            'let token = (queryToken || sessionStorage.getItem("hermes_token") || sessionStorage.getItem("coagent_token") || "").replace(/^Bearer\s+/i, "");',
            f'let token = {safe_token} || queryToken || sessionStorage.getItem("hermes_token") || sessionStorage.getItem("coagent_token") || "";'
        )
        return Response(html, mimetype="text/html")
    except Exception: return jsonify({"error": "dashboard.html not found"}), 404

@app.route("/index.html", methods=["GET"])
@require_auth
def route_index_html():
    return route_dashboard2()

@app.route("/mcp/test", methods=["GET"])
@require_auth
def route_mcp_test():
    return jsonify({"status": "mcp_test", "server": AGENT_NAME, "version": VERSION})

register_auth_routes(app)

# -- Short alias routes for MCP compatibility --------------------
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

def _proxy_get(path): return lambda: jsonify({"proxy": path, "endpoint": f"use {path} directly"})

for _route, _handler_name in list(_short_routes.items()):
    _ep = _route.lstrip("/").replace("/", "_") or "root"
    app.route(_route, endpoint=_ep)(_proxy_get(_route))

# -- System Tray Icon --------------------------------------------
def _start_tray():
    try:
        def _ps_quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        tray_script = COAGENT_DIR / "tray_icon.py"
        if not tray_script.exists():
            _console("  [INFO] tray_icon.py not found, skip tray icon")
            return
        pyw_candidates = [
            str(Path(sys.executable).with_name("pythonw.exe")),
            which("pythonw.exe"),
        ]
        pyw = next((p for p in pyw_candidates if p and Path(p).exists()), None)
        if not pyw:
            _console("  [INFO] Tray icon skipped: pythonw.exe not found")
            return
        task_name = "HermesCoAgent_Tray"
        tray_argv = [str(tray_script), str(_self_port()), str(TRAY_PORT)]
        # Token is read from .token file by tray_icon.py, not passed via argv
        # to avoid exposing the bearer token in process lists and task metadata
        _log("[tray] token will be read from .token file")
        tray_args = subprocess.list2cmdline(tray_argv)
        tray_cmd = subprocess.list2cmdline([pyw, *tray_argv])
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

# -- Log viewer --------------------------------------------------
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
            if request.args.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
                return jsonify({"lines": last_n.splitlines(), "text": last_n, "count": len(last_n.splitlines())})
            return Response(f"<pre>{escape(last_n)}</pre>", mimetype="text/html")
        except Exception:
            return jsonify({"error": "Cannot read log"}), 500
    return jsonify({"lines": [], "text": "", "count": 0, "log": "No log file"})

_ensure_registered_route_auth()

# -- Main ---------------------------------------------------------
def start_server():
    # Parse args
    mcp_stdio = "--mcp-stdio" in sys.argv
    bind_host = "127.0.0.1"
    port = SERVER_PORT
    if "--allow-external" in sys.argv:
        bind_host = "0.0.0.0"
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 >= len(sys.argv):
            _console("  [FATAL] --port requires a value.")
            sys.exit(2)
        try:
            port = int(sys.argv[idx + 1])
        except ValueError:
            _console(f"  [FATAL] --port must be an integer, got: {sys.argv[idx + 1]!r}")
            sys.exit(2)
        if not (1 <= port <= 65535):
            _console(f"  [FATAL] --port out of range (1-65535): {port}")
            sys.exit(2)
    # Publish the effective port so internal self-calls (healer, finder, etc.)
    # and the tray probe the actual bound port, not a hardcoded 9123.
    os.environ["COAGENT_PORT"] = str(port)
    import shared as _shared
    _shared.SERVER_PORT = port
    has_secure_arg = "--secure" in sys.argv
    has_token_arg = any(a == "--token" or a.startswith("--token=") for a in sys.argv)

    if not mcp_stdio and not acquire_single_instance_lock(port=port, bind_host=bind_host):
        sys.exit(0)
    _console("================================================")
    _console(f"     {AGENT_NAME} v{VERSION} - MODULAR REFACTOR")
    _console("================================================")
    _console(f"  PID: {os.getpid()}")
    _console(f"  Directory: {COAGENT_DIR}")
    if mcp_stdio:
        with contextlib.redirect_stdout(sys.stderr):
            _init_auth(port, COAGENT_DIR)
    else:
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

    if "--observe" in sys.argv:
        enable_observe()
        _console("  Observe mode: ENABLED (mutating endpoints blocked, reads live)")

    if mcp_stdio:
        _console("  MCP stdio: enabled")
        run_stdio_server(app)
        return

    _console(f"  Server: http://{bind_host}:{port}/")
    _console(f"  Modules: mouse ocr uia file media v63 stream process voice cua copilot buddy bypass toast deps config browser google logs recorder mcp git dashboard obsidian wol phone webrtc plugins palmreject agent memory batching reminders hud copilot_enhanced recipes healer browser_v2 mobile telemetry diff_capture office_mcp")
    gateway = getattr(state, "agent_gateway", {})
    _console(f"  Agent Gateway: default={gateway.get('default_agent') or 'none'}")
    _console()

    # Defer warm-ups to background so Waitress can start serving immediately.
    def _background_warmups():
        try:
            from routes_uia import _get_uia_engine
            ue = _get_uia_engine()
            if ue.UIA_READY:
                _console("  [OK] UIA engine ready (background)")
        except Exception:
            pass
        try:
            from routes_ocr import _capture_raw
            _capture_raw(force=True)
            _console("  [OK] Screenshot engine warmed (background)")
        except Exception:
            pass

    threading.Thread(target=_background_warmups, name="hermes-warmups", daemon=True).start()

    # Tray icon disabled — v7.13 doesn't need it, and schtasks /Run causes popup windows
    # _start_tray()

    # Start Office MCP servers (background, non-blocking)
    _start_office_mcp_servers()

    # Start auto-healing watchdog
    _start_watchdog(port)
    _start_endpoint_health_monitor()

    # v7.3: Waitress WSGI server
    _console(f"  [OK] Waitress WSGI on http://{bind_host}:{port}/")
    waitress.serve(app, host=bind_host, port=port, threads=8, connection_limit=100)


def main():
    start_server()


if __name__ == "__main__":
    main()

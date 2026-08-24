"""Self-healing health monitor and recovery routes."""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

from flask import Blueprint, jsonify

from shared import _self_port, COAGENT_DIR, _console, _json_body

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False


healer_bp = Blueprint("healer", __name__)

CONFIG_FILE = COAGENT_DIR / "healer_config.json"
DEFAULT_CONFIG = {
    "auto_restart": True,
    "max_errors_before_restart": 5,
    "check_interval_seconds": 30,
    "memory_limit_mb": 500,
}

JSON_PROBE_PATHS = (
    "/ping",
    "/version",
    "/help",
    "/healer/status",
    "/health",
)
NON_JSON_ROUTE_PREFIXES = (
    "/screen",
    "/screenshot",
    "/som",
    "/browser/screenshot",
    "/stream",
)
MIN_HEALTHY_PROBES = 3

_CONFIG_LOCK = threading.RLock()
_LOG_LOCK = threading.RLock()
_STATUS_LOCK = threading.RLock()
_SAMPLES_LOCK = threading.Lock()
_HEALER_CONFIG = dict(DEFAULT_CONFIG)
_HEALER_LOG = deque(maxlen=100)
_ERROR_TOTAL_SAMPLES = deque(maxlen=240)
_HEALER_THREAD = None
_APP = None
_STATE = None
_RESTART_PENDING = False
_LAST_STATUS = {
    "server": {"uptime": 0, "status": "unknown"},
    "memory": {"rss_mb": 0, "limit_mb": DEFAULT_CONFIG["memory_limit_mb"], "status": "unknown"},
    "routes": {"total": 0, "healthy": 0, "failing": []},
    "errors_last_hour": 0,
    "restarts_today": 0,
    "last_check": None,
    "status": "unknown",
}


def _load_config():
    global _HEALER_CONFIG
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _HEALER_CONFIG = _sanitize_config({**DEFAULT_CONFIG, **data})
    except Exception as exc:
        _console(f"[healer] config load failed: {type(exc).__name__}: {exc}")


def _save_config():
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_HEALER_CONFIG, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _int_range(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _sanitize_config(data):
    return {
        "auto_restart": _as_bool(data.get("auto_restart"), DEFAULT_CONFIG["auto_restart"]),
        "max_errors_before_restart": _int_range(
            data.get("max_errors_before_restart"),
            DEFAULT_CONFIG["max_errors_before_restart"],
            1,
            100000,
        ),
        "check_interval_seconds": _int_range(
            data.get("check_interval_seconds"),
            DEFAULT_CONFIG["check_interval_seconds"],
            5,
            3600,
        ),
        "memory_limit_mb": _int_range(data.get("memory_limit_mb"), DEFAULT_CONFIG["memory_limit_mb"], 64, 65536),
    }


def _log_action(action, level="info", detail=None):
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "action": action,
        "detail": detail or {},
    }
    with _LOG_LOCK:
        _HEALER_LOG.append(entry)
    _console(f"[healer] {level}: {action} {detail or ''}")
    return entry


def _memory_rss_mb():
    if HAS_PSUTIL:
        try:
            return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 2)
        except Exception:
            pass
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {os.getpid()}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        line = result.stdout.strip().splitlines()[0]
        import csv
        rows = list(csv.reader([line]))
        if rows and len(rows[0]) >= 5:
            raw = rows[0][4].replace(",", "").replace("K", "").strip()
            return round(int(raw) / 1024, 2)
    except Exception:
        pass
    return 0.0


def _auth_header():
    token_file = COAGENT_DIR / ".token"
    try:
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return f"Bearer {token}"
    except Exception:
        pass
    return ""


def _http_get(path, timeout=5):
    headers = {"Accept": "application/json"}
    token = _auth_header()
    if token:
        headers["Authorization"] = token
    started = time.perf_counter()
    req = urllib.request.Request(f"http://127.0.0.1:{_self_port()}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(4096)
            latency = time.perf_counter() - started
            content_type = response.headers.get("Content-Type", "")
            status_code = getattr(response, "status", 200)
            return {
                "path": path,
                "ok": 200 <= status_code < 300 and "application/json" in content_type,
                "status_code": status_code,
                "content_type": content_type,
                "latency_seconds": round(latency, 3),
                "bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {
            "path": path,
            "ok": False,
            "status_code": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if hasattr(exc, "headers") else "",
            "latency_seconds": round(time.perf_counter() - started, 3),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "path": path,
            "ok": False,
            "status_code": 0,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _metric_error_total():
    try:
        import routes_metrics
        with routes_metrics._lock():
            errors = dict(routes_metrics.ERRORS)
        total = 0
        for key, value in errors.items():
            try:
                path = str(key[1])
                if _is_non_json_route(path):
                    continue
                status = int(key[2])
            except Exception:
                status = 0
            if status >= 500:
                total += int(value)
        return total
    except Exception:
        return 0


def _errors_last_hour():
    now = time.time()
    current = _metric_error_total()
    with _SAMPLES_LOCK:
        _ERROR_TOTAL_SAMPLES.append((now, current))
        while _ERROR_TOTAL_SAMPLES and now - _ERROR_TOTAL_SAMPLES[0][0] > 3600:
            _ERROR_TOTAL_SAMPLES.popleft()
        if len(_ERROR_TOTAL_SAMPLES) < 2:
            return 0
        return max(0, current - _ERROR_TOTAL_SAMPLES[0][1])


def _route_total():
    try:
        return len([rule for rule in _APP.url_map.iter_rules()]) if _APP is not None else 0
    except Exception:
        return 0


def _is_non_json_route(path):
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in NON_JSON_ROUTE_PREFIXES)


def _json_probe_paths():
    return [path for path in JSON_PROBE_PATHS if not _is_non_json_route(path)]


def _restart_count_today():
    today = datetime.now().date().isoformat()
    with _LOG_LOCK:
        return sum(
            1
            for entry in _HEALER_LOG
            if entry.get("action") in {"restart_requested", "restart_spawned"}
            and str(entry.get("time", "")).startswith(today)
        )


def _clear_soft_caches():
    try:
        from shared import _sse_clients, _sse_lock
        with _sse_lock:
            cleared = len(_sse_clients)
            _sse_clients.clear()
        return {"sse_clients_cleared": cleared}
    except Exception as exc:
        return {"cache_clear_error": f"{type(exc).__name__}: {exc}"}


def _python_executable():
    current = os.path.basename(sys.executable).lower()
    if current == "pythonw.exe":
        return sys.executable
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(candidate):
        return candidate
    return sys.executable


def _spawn_restart(reason):
    global _RESTART_PENDING
    with _STATUS_LOCK:
        if _RESTART_PENDING:
            return False
        _RESTART_PENDING = True
    _log_action("restart_requested", "critical", {"reason": reason})

    def worker():
        time.sleep(1.0)
        args = [_python_executable(), str(COAGENT_DIR / "hermes_coagent.py")]
        for _arg in sys.argv[1:]:
            if _arg in ("--secure", "--allow-external") or _arg.startswith("--token="):
                args.append(_arg)
        kwargs = {
            "cwd": str(COAGENT_DIR),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(args, **kwargs)
            _log_action("restart_spawned", "critical", {"reason": reason, "args": args})
        except Exception as exc:
            _log_action("restart_failed", "critical", {"reason": reason, "error": f"{type(exc).__name__}: {exc}"})
            with _STATUS_LOCK:
                global _RESTART_PENDING
                _RESTART_PENDING = False
            return
        os._exit(0)

    threading.Thread(target=worker, name="healer-restart", daemon=True).start()
    return True


def _perform_check(reason="scheduled"):
    with _CONFIG_LOCK:
        config = dict(_HEALER_CONFIG)
    uptime = int(time.time() - getattr(_STATE, "start_time", time.time())) if _STATE is not None else 0
    rss_mb = _memory_rss_mb()
    memory_status = "healthy"
    if rss_mb > config["memory_limit_mb"] * 2:
        memory_status = "critical"
    elif rss_mb > config["memory_limit_mb"]:
        memory_status = "warning"

    checks = [_http_get(path) for path in _json_probe_paths()]
    failing = [check for check in checks if not check.get("ok")]
    slow_threshold = 5.0
    slow = [check for check in checks if check.get("ok") and check.get("latency_seconds", 0) > slow_threshold]
    healthy_count = max(0, len(checks) - len(failing) - len(slow))
    route_status = "healthy" if healthy_count >= MIN_HEALTHY_PROBES else "degraded"
    if failing:
        _log_action("route_check_failed", "warning", {"failing": failing})
    if slow:
        _log_action("route_check_slow", "warning", {"slow": slow})
    if route_status == "degraded":
        _log_action("soft_recovery", "warning", _clear_soft_caches())

    errors = _errors_last_hour()
    overall = "healthy"
    if memory_status == "warning" or route_status == "degraded" or errors > 0:
        overall = "degraded"
    if memory_status == "critical" or errors > config["max_errors_before_restart"]:
        overall = "critical"

    status = {
        "server": {"uptime": uptime, "status": "healthy" if route_status == "healthy" else "degraded"},
        "memory": {"rss_mb": rss_mb, "limit_mb": config["memory_limit_mb"], "status": memory_status},
        "routes": {
            "total": len(checks),
            "registered_total": _route_total(),
            "healthy": healthy_count,
            "failing": failing + slow,
            "probed": checks,
            "minimum_healthy": MIN_HEALTHY_PROBES,
        },
        "errors_last_hour": errors,
        "restarts_today": _restart_count_today(),
        "last_check": datetime.now().isoformat(timespec="seconds"),
        "status": overall,
        "auto_restart": config["auto_restart"],
        "reason": reason,
    }

    with _STATUS_LOCK:
        _LAST_STATUS.update(status)

    if memory_status == "warning":
        _log_action("memory_warning", "warning", {"rss_mb": rss_mb, "limit_mb": config["memory_limit_mb"]})
    if overall == "critical" and config.get("auto_restart"):
        if memory_status == "critical":
            _spawn_restart(f"memory {rss_mb}MB exceeded {config['memory_limit_mb'] * 2}MB")
        elif errors > config["max_errors_before_restart"]:
            _spawn_restart(f"{errors} server errors in last hour")
    return status


def _healer_loop():
    _log_action("healer_started", "info", {"psutil": HAS_PSUTIL})
    while True:
        try:
            _perform_check()
        except Exception as exc:
            _log_action("check_failed", "error", {"error": f"{type(exc).__name__}: {exc}"})
        with _CONFIG_LOCK:
            interval = int(_HEALER_CONFIG.get("check_interval_seconds", DEFAULT_CONFIG["check_interval_seconds"]))
        time.sleep(max(5, interval))


def _start_healer_thread():
    global _HEALER_THREAD
    with _STATUS_LOCK:
        if _HEALER_THREAD and _HEALER_THREAD.is_alive():
            return
        _HEALER_THREAD = threading.Thread(target=_healer_loop, name="healer", daemon=True)
        _HEALER_THREAD.start()


@healer_bp.route("/healer/configure", methods=["POST"])
def route_healer_configure():
    data = _json_body()
    if not isinstance(data, dict):
        return jsonify({"error": "expected JSON object"}), 400
    with _CONFIG_LOCK:
        _HEALER_CONFIG.update(_sanitize_config({**_HEALER_CONFIG, **data}))
        _save_config()
        payload = dict(_HEALER_CONFIG)
    _log_action("configured", "info", payload)
    return jsonify({"status": "configured", **payload})


@healer_bp.route("/healer/config", methods=["GET"])
def route_healer_config():
    with _CONFIG_LOCK:
        return jsonify(dict(_HEALER_CONFIG))


@healer_bp.route("/healer/status", methods=["GET"])
def route_healer_status():
    with _STATUS_LOCK:
        payload = dict(_LAST_STATUS)
        payload["thread_alive"] = bool(_HEALER_THREAD and _HEALER_THREAD.is_alive())
        payload["restart_pending"] = _RESTART_PENDING
        return jsonify(payload)


@healer_bp.route("/healer/log", methods=["GET"])
def route_healer_log():
    with _LOG_LOCK:
        logs = list(_HEALER_LOG)
    return jsonify({"logs": logs, "count": len(logs)})


@healer_bp.route("/healer/check", methods=["POST"])
def route_healer_check():
    return jsonify(_perform_check(reason="manual"))


@healer_bp.route("/healer/restart", methods=["POST"])
def route_healer_restart():
    data = _json_body()
    if not isinstance(data, dict):
        data = {}
    reason = str(data.get("reason") or "manual_healer_restart")
    spawned = _spawn_restart(reason)
    return jsonify({"status": "restarting" if spawned else "restart_already_pending", "restarting": spawned})


def register_routes(app, state, require_auth):
    global _APP, _STATE
    _APP = app
    _STATE = state
    _load_config()
    for endpoint, view_func in list(healer_bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        healer_bp.view_functions[endpoint] = wrapped
    app.register_blueprint(healer_bp)
    _start_healer_thread()
    state.healer = {"config_file": str(CONFIG_FILE), "psutil": HAS_PSUTIL}

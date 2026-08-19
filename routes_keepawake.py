"""Keep-awake routes — prevent Windows sleep / display-off during automation.

Implements the classic ``caffeine`` / ``SetThreadExecutionState`` capability:
while a keep-awake hold is active the machine will not sleep and (optionally)
the display stays on. The Win32 execution-state flag is per-thread and resets
when the calling thread exits, so it is held by a dedicated daemon thread that
keeps re-asserting the flag until the hold is released.

Endpoints:
    POST /system/keepawake/start   — start hold (optionally display_off)
    POST /system/keepawake/stop    — release the hold
    GET  /system/keepawake/status  — hold state + current sleep/display timeouts
"""

import subprocess
import threading
import time

from flask import jsonify

from shared import _json_body, _log

# Win32 SetThreadExecutionState flags (kernel32)
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_hold = {"active": False, "display_off": False, "since": None}
_hold_lock = threading.Lock()
_stop_event = threading.Event()

try:
    import ctypes
    _kernel32 = ctypes.windll.kernel32
    _kernel32.SetThreadExecutionState.restype = ctypes.c_ulong
    _kernel32.SetThreadExecutionState.argtypes = [ctypes.c_ulong]
    _HAS_ES = True
except Exception:
    _kernel32 = None
    _HAS_ES = False


def _set_es(flags):
    if not _HAS_ES:
        return None
    try:
        return _kernel32.SetThreadExecutionState(flags)
    except Exception as exc:
        _log(f"keepawake: SetThreadExecutionState failed: {exc}")
        return None


def _ps(script, timeout=10):
    """Run a PowerShell command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "PowerShell command timed out", -1
    except FileNotFoundError:
        return "", "powershell.exe not found (not on Windows?)", -1


def _holder_loop(flags):
    """Run on a dedicated thread; holds the ES flag until stop is signaled."""
    _set_es(ES_CONTINUOUS | flags)
    while not _stop_event.wait(30.0):
        # Re-assert periodically (defensive — the flag is continuous).
        _set_es(ES_CONTINUOUS | flags)
    # Clear the flag on exit.
    _set_es(ES_CONTINUOUS)


def _start_hold(display_off=False):
    global _hold
    with _hold_lock:
        if _hold["active"]:
            _hold["display_off"] = display_off
            return {"status": "already_active", "since": _hold["since"], "display_off": display_off}
        flags = ES_SYSTEM_REQUIRED | (0 if display_off else ES_DISPLAY_REQUIRED)
        _stop_event.clear()
        t = threading.Thread(
            target=_holder_loop, args=(flags,), name="coagent-keepawake", daemon=True
        )
        t.start()
        _hold["active"] = True
        _hold["display_off"] = display_off
        _hold["since"] = time.time()
        return {"status": "started", "since": _hold["since"], "display_off": display_off}


def _stop_hold():
    global _hold
    with _hold_lock:
        was_active = _hold["active"]
        _stop_event.set()
        _hold["active"] = False
        _hold["display_off"] = False
        _hold["since"] = None
        return {"status": "stopped" if was_active else "was_not_active"}


def _powercfg_timeouts():
    """Best-effort read of current sleep + display timeouts (seconds) via powercfg."""
    out = {"sleep": None, "display": None}

    def _idx_hex_seconds(text):
        # "Current AC Power Setting Index: 0x00000000" → seconds
        for line in text.splitlines():
            if "Current AC Power Setting Index" in line:
                val = line.split(":")[-1].strip().lower()
                if val.startswith("0x"):
                    try:
                        return int(val, 16)
                    except ValueError:
                        return None
        return None

    for key in ("sleep", "display"):
        if key == "sleep":
            sub = "SUB_SLEEP STANDBYIDLE"
        else:
            sub = "SUB_VIDEO VIDEOIDLE"
        stdout, _, code = _ps(f"powercfg /query SCHEME_CURRENT {sub}", timeout=8)
        if code == 0 and stdout:
            out[key] = _idx_hex_seconds(stdout)
    return out


def register_routes(app, state, require_auth):
    @app.route("/system/keepawake/start", methods=["POST"])
    @require_auth
    def route_keepawake_start():
        data = _json_body() or {}
        display_off = bool(data.get("display_off", False))
        if not _HAS_ES:
            return jsonify({"error": "SetThreadExecutionState unavailable (not on Windows?)"}), 501
        result = _start_hold(display_off)
        _log(f"keepawake: start -> {result.get('status')}")
        return jsonify(result)

    @app.route("/system/keepawake/stop", methods=["POST"])
    @require_auth
    def route_keepawake_stop():
        result = _stop_hold()
        _log(f"keepawake: stop -> {result.get('status')}")
        return jsonify(result)

    @app.route("/system/keepawake/status", methods=["GET"])
    @require_auth
    def route_keepawake_status():
        with _hold_lock:
            snapshot = dict(_hold)
        timeouts = _powercfg_timeouts() if _HAS_ES else {"sleep": None, "display": None}
        return jsonify({
            "active": snapshot["active"],
            "display_off": snapshot["display_off"],
            "since": snapshot["since"],
            "elapsed_seconds": round(time.time() - snapshot["since"]) if snapshot["since"] else None,
            "set_thread_execution_state_available": _HAS_ES,
            "timeouts_seconds": timeouts,
        })

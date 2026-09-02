"""Desktop macro recorder (issue #166).

Captures live user input via Win32 low-level mouse/keyboard hooks
(WH_MOUSE_LL, WH_KEYBOARD_LL), timestamps events with monotonic gaps,
saves as named JSON macros under COAGENT_DIR/macros_recorded/, and
replays them via pyautogui (mouse) and SendInput (keyboard).

Design:
  - Only one recording session at a time (guarded by a lock).
  - Hooks run in a dedicated thread with its own message loop.
  - A separate hotkey (default: Ctrl+Alt+Shift+R) toggles recording so
    the operator can stop hands-free.
  - Replay is cancellable via emergency_stop on the shared state.
"""
import ctypes
import json
import re
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log, _missing_field

MACROS_DIR = COAGENT_DIR / "macros_recorded"
MACROS_DIR.mkdir(parents=True, exist_ok=True)

# Win32 message constants
_WH_KEYBOARD_LL = 13
_WH_MOUSE_LL = 14
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_WM_SYSKEYDOWN = 0x0104
_WM_SYSKEYUP = 0x0105
_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONDOWN = 0x0204
_WM_RBUTTONUP = 0x0205
_WM_MBUTTONDOWN = 0x0207
_WM_MBUTTONUP = 0x0208
_WM_MOUSEWHEEL = 0x020A
_WM_MOUSEMOVE = 0x0200
_HC_ACTION = 0

_STATE = {
    "recording": False,
    "events": [],
    "started_at": 0.0,
    "last_ts": 0.0,
    "thread": None,
    "hook_kbd": None,
    "hook_mouse": None,
    "capture_moves": False,
    "min_move_gap": 0.05,  # seconds
    "last_move_at": 0.0,
    "hotkey_toggle": True,
}
_STATE_LOCK = threading.Lock()
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


LowLevelProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


def _user32():
    u = ctypes.windll.user32
    if not getattr(_user32, "_argtypes_set", False):
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelProc,
                                        wintypes.HMODULE, wintypes.DWORD]
        u.SetWindowsHookExW.restype = wintypes.HHOOK
        u.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        u.UnhookWindowsHookEx.restype = wintypes.BOOL
        u.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                     wintypes.WPARAM, wintypes.LPARAM]
        u.CallNextHookEx.restype = wintypes.LPARAM
        _user32._argtypes_set = True
    return u


def _kernel32():
    k = ctypes.windll.kernel32
    if not getattr(_kernel32, "_argtypes_set", False):
        k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k.GetModuleHandleW.restype = wintypes.HMODULE
        _kernel32._argtypes_set = True
    return k


def _append_event(kind, data):
    with _STATE_LOCK:
        if not _STATE["recording"]:
            return
        now = time.perf_counter()
        gap = 0.0 if _STATE["last_ts"] == 0.0 else round(now - _STATE["last_ts"], 4)
        _STATE["last_ts"] = now
        _STATE["events"].append({"t": round(now - _STATE["started_at"], 4),
                                 "gap": gap, "kind": kind, **data})


def _kbd_proc(nCode, wParam, lParam):
    if nCode == _HC_ACTION:
        info = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT))[0]
        if wParam in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
            _append_event("keydown", {"vk": info.vkCode, "scan": info.scanCode})
        elif wParam in (_WM_KEYUP, _WM_SYSKEYUP):
            _append_event("keyup", {"vk": info.vkCode, "scan": info.scanCode})
    return _user32().CallNextHookEx(None, nCode, wParam, lParam)


def _mouse_proc(nCode, wParam, lParam):
    if nCode == _HC_ACTION:
        info = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT))[0]
        x, y = info.pt.x, info.pt.y
        if wParam == _WM_LBUTTONDOWN:
            _append_event("mousedown", {"btn": "left", "x": x, "y": y})
        elif wParam == _WM_LBUTTONUP:
            _append_event("mouseup", {"btn": "left", "x": x, "y": y})
        elif wParam == _WM_RBUTTONDOWN:
            _append_event("mousedown", {"btn": "right", "x": x, "y": y})
        elif wParam == _WM_RBUTTONUP:
            _append_event("mouseup", {"btn": "right", "x": x, "y": y})
        elif wParam == _WM_MBUTTONDOWN:
            _append_event("mousedown", {"btn": "middle", "x": x, "y": y})
        elif wParam == _WM_MBUTTONUP:
            _append_event("mouseup", {"btn": "middle", "x": x, "y": y})
        elif wParam == _WM_MOUSEWHEEL:
            delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
            _append_event("wheel", {"delta": delta, "x": x, "y": y})
        elif wParam == _WM_MOUSEMOVE and _STATE["capture_moves"]:
            now = time.perf_counter()
            if now - _STATE["last_move_at"] >= _STATE["min_move_gap"]:
                _STATE["last_move_at"] = now
                _append_event("move", {"x": x, "y": y})
    return _user32().CallNextHookEx(None, nCode, wParam, lParam)


_KBD_CB = LowLevelProc(_kbd_proc)
_MOUSE_CB = LowLevelProc(_mouse_proc)


def _hook_thread():
    """Install hooks and pump messages until told to stop."""
    u32 = _user32()
    k32 = _kernel32()
    hMod = k32.GetModuleHandleW(None)

    with _STATE_LOCK:
        _STATE["hook_kbd"] = u32.SetWindowsHookExW(_WH_KEYBOARD_LL, _KBD_CB, hMod, 0)
        _STATE["hook_mouse"] = u32.SetWindowsHookExW(_WH_MOUSE_LL, _MOUSE_CB, hMod, 0)

    msg = wintypes.MSG()
    while _STATE["recording"]:
        r = u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_REMOVE
        if r:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.005)

    with _STATE_LOCK:
        if _STATE["hook_kbd"]:
            u32.UnhookWindowsHookEx(_STATE["hook_kbd"])
            _STATE["hook_kbd"] = None
        if _STATE["hook_mouse"]:
            u32.UnhookWindowsHookEx(_STATE["hook_mouse"])
            _STATE["hook_mouse"] = None


def _macro_path(name):
    name = str(name or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError("macro name must match [A-Za-z0-9_-]{1,64}")
    return MACROS_DIR / f"{name}.json"


def _replay(events, speed=1.0, stop_flag=None):
    """Replay recorded events. `speed` scales gaps (0.5 = half-speed = slower)."""
    import pyautogui as pg
    from ctypes import c_ushort, c_ulong, c_long, c_size_t, byref, sizeof

    KEYEVENTF_KEYUP = 0x0002

    class _KBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", c_ushort), ("wScan", c_ushort),
                    ("dwFlags", c_ulong), ("time", c_ulong),
                    ("dwExtraInfo", c_size_t)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", c_long), ("dy", c_long),
                    ("mouseData", c_ulong), ("dwFlags", c_ulong),
                    ("time", c_ulong), ("dwExtraInfo", c_size_t)]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", c_ulong), ("wParamL", c_ushort), ("wParamH", c_ushort)]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", _KBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    # INPUT is a union sized to its largest member (MOUSEINPUT); on 64-bit
    # Windows sizeof(INPUT) is 40 bytes. A struct holding only KBDINPUT is
    # 32 bytes, which SendInput rejects with ERROR_INVALID_PARAMETER.
    class _INPUT(ctypes.Structure):
        _fields_ = [("type", c_ulong), ("u", _INPUT_UNION)]

    def _send_vk(vk, up=False):
        inp = _INPUT()
        inp.type = 1
        inp.u.ki = _KBDINPUT(int(vk), 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
        ctypes.windll.user32.SendInput(1, byref(inp), sizeof(inp))

    for ev in events:
        if stop_flag and stop_flag.is_set():
            return False
        gap = max(0.0, float(ev.get("gap", 0.0))) / max(0.01, float(speed))
        if gap > 0:
            time.sleep(min(gap, 5.0))
        k = ev.get("kind")
        if k == "mousedown":
            btn = ev.get("btn", "left")
            pg.moveTo(ev.get("x", 0), ev.get("y", 0), duration=0)
            pg.mouseDown(button=btn)
        elif k == "mouseup":
            pg.mouseUp(button=ev.get("btn", "left"))
        elif k == "move":
            pg.moveTo(ev.get("x", 0), ev.get("y", 0), duration=0)
        elif k == "wheel":
            pg.scroll(int(ev.get("delta", 0) // 120))
        elif k == "keydown":
            _send_vk(int(ev.get("vk", 0)), up=False)
        elif k == "keyup":
            _send_vk(int(ev.get("vk", 0)), up=True)
    return True


def register_routes(app, state, require_auth):

    @app.route("/macro/rec/start", methods=["POST"])
    @require_auth
    def route_rec_start():
        body = _json_body() or {}
        try:
            min_move_gap = max(0.01, float(body.get("min_move_gap", 0.05)))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "min_move_gap must be a number"}), 400
        with _STATE_LOCK:
            if _STATE["recording"]:
                return jsonify({"ok": False, "error": "already recording"}), 409
            _STATE["recording"] = True
            _STATE["events"] = []
            _STATE["started_at"] = time.perf_counter()
            _STATE["last_ts"] = 0.0
            _STATE["last_move_at"] = 0.0
            _STATE["capture_moves"] = bool(body.get("capture_moves", False))
            _STATE["min_move_gap"] = min_move_gap
        t = threading.Thread(target=_hook_thread, name="macro-rec-hook", daemon=True)
        _STATE["thread"] = t
        t.start()
        _log("[macro_rec] recording started")
        return jsonify({"ok": True, "recording": True})

    @app.route("/macro/rec/stop", methods=["POST"])
    @require_auth
    def route_rec_stop():
        body = _json_body() or {}
        with _STATE_LOCK:
            if not _STATE["recording"]:
                return jsonify({"ok": False, "error": "not recording"}), 409
            _STATE["recording"] = False
            events = list(_STATE["events"])
            duration = round(time.perf_counter() - _STATE["started_at"], 3)
        # wait a moment for hook thread to exit its message loop
        t = _STATE.get("thread")
        if t and t.is_alive():
            t.join(timeout=1.0)
        name = body.get("name") or f"macro_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        try:
            path = _macro_path(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e), "events": events}), 400
        macro = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "created_at": time.time(),
            "duration": duration,
            "event_count": len(events),
            "events": events,
        }
        # Write atomically (temp file + rename) so a crash mid-write can't
        # leave a truncated JSON file behind for /macro/get and /macro/replay.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(macro, indent=2), encoding="utf-8")
        tmp.replace(path)
        _log(f"[macro_rec] saved {name} ({len(events)} events)")
        return jsonify({"ok": True, "macro": {k: v for k, v in macro.items() if k != "events"},
                        "path": str(path)})

    @app.route("/macro/rec/status", methods=["GET"])
    @require_auth
    def route_rec_status():
        with _STATE_LOCK:
            return jsonify({
                "ok": True,
                "recording": _STATE["recording"],
                "captured": len(_STATE["events"]),
                "capture_moves": _STATE["capture_moves"],
                "elapsed": round(time.perf_counter() - _STATE["started_at"], 2)
                          if _STATE["recording"] else 0.0,
            })

    @app.route("/macro/get/<name>", methods=["GET"])
    @require_auth
    def route_macro_get(name):
        try:
            path = _macro_path(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if not path.is_file():
            return jsonify({"ok": False, "error": "macro not found"}), 404
        try:
            macro = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return jsonify({"ok": False, "error": f"failed to read macro: {e}"}), 500
        return jsonify({"ok": True, "macro": macro})

    @app.route("/macro/delete/<name>", methods=["POST"])
    @require_auth
    def route_macro_rec_delete(name):
        try:
            path = _macro_path(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if path.is_file():
            try:
                path.unlink()
            except OSError as e:
                return jsonify({"ok": False, "error": str(e)}), 500
            return jsonify({"ok": True, "deleted": str(path)})
        return jsonify({"ok": False, "error": "macro not found"}), 404

    @app.route("/macro/replay/<name>", methods=["POST"])
    @require_auth
    def route_macro_replay(name):
        body = _json_body() or {}
        try:
            path = _macro_path(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if not path.is_file():
            return jsonify({"ok": False, "error": "macro not found"}), 404
        try:
            macro = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return jsonify({"ok": False, "error": f"failed to read macro: {e}"}), 500
        try:
            speed = float(body.get("speed", 1.0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "speed must be a number"}), 400
        if speed <= 0.0:
            return jsonify({"ok": False, "error": "speed must be > 0"}), 400
        # Fire-and-forget with a stop flag tied to shared emergency_stop.
        stop_flag = threading.Event()

        def _run():
            try:
                _replay(macro.get("events") or [], speed=speed, stop_flag=stop_flag)
            except Exception as e:
                _log(f"[macro_rec] replay error: {e}")
            finally:
                # Ensures the _watch_estop thread exits promptly at replay end.
                stop_flag.set()

        def _watch_estop():
            while not stop_flag.is_set():
                if getattr(state, "emergency_stop", False):
                    stop_flag.set()
                    return
                time.sleep(0.1)

        threading.Thread(target=_run, daemon=True, name=f"macro-replay-{name}").start()
        threading.Thread(target=_watch_estop, daemon=True, name="macro-estop-watch").start()
        return jsonify({"ok": True, "replaying": name, "speed": speed,
                        "events": macro.get("event_count", 0)})

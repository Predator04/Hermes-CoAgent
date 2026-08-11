"""Keyboard and mouse recorder routes."""

import ctypes
import ctypes.wintypes
import json
import re
import threading
import time
from pathlib import Path

from flask import jsonify, request

from shared import COAGENT_DIR, _json_body, _log


RECORDINGS_DIR = COAGENT_DIR / "recordings"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

_LOCK = threading.RLock()
_STOP_EVENT = threading.Event()
_READY_EVENT = threading.Event()
_THREAD = None
_THREAD_ID = None
_RUNNING = False
_HOOK_ERROR = ""
_HOOKS = {}
_CALLBACKS = {}
_RECORDING = []
_START_TIME = 0.0
_LAST_EVENT_TIME = 0.0
_LAST_MOVE_TIME = 0.0
_MOVE_INTERVAL_MS = 0
_MAX_EVENTS = 20000
_DROPPED_EVENTS = 0

_KEY_NAMES = {
    0x08: "backspace",
    0x09: "tab",
    0x0D: "enter",
    0x10: "shift",
    0x11: "ctrl",
    0x12: "alt",
    0x13: "pause",
    0x14: "capslock",
    0x1B: "esc",
    0x20: "space",
    0x21: "pageup",
    0x22: "pagedown",
    0x23: "end",
    0x24: "home",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2D: "insert",
    0x2E: "delete",
    0x5B: "win",
    0x5C: "win",
    0x60: "num0",
    0x61: "num1",
    0x62: "num2",
    0x63: "num3",
    0x64: "num4",
    0x65: "num5",
    0x66: "num6",
    0x67: "num7",
    0x68: "num8",
    0x69: "num9",
    0x6A: "multiply",
    0x6B: "add",
    0x6D: "subtract",
    0x6E: "decimal",
    0x6F: "divide",
}
for _idx in range(1, 25):
    _KEY_NAMES[0x6F + _idx] = f"f{_idx}"


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_ulong),
        ("scanCode", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


def _is_windows_api_available():
    return hasattr(ctypes, "windll") and hasattr(ctypes, "WINFUNCTYPE")


def _event_delay(now):
    global _LAST_EVENT_TIME
    if not _LAST_EVENT_TIME:
        delay_ms = 0
    else:
        delay_ms = max(0, int((now - _LAST_EVENT_TIME) * 1000))
    _LAST_EVENT_TIME = now
    return delay_ms


def _append_event(event):
    global _DROPPED_EVENTS
    with _LOCK:
        if not _RUNNING:
            return
        now = time.time()
        event["timestamp"] = now
        event["offset_ms"] = int((now - _START_TIME) * 1000) if _START_TIME else 0
        event["delay_ms"] = _event_delay(now)
        if len(_RECORDING) >= _MAX_EVENTS:
            _RECORDING.pop(0)
            _DROPPED_EVENTS += 1
        _RECORDING.append(event)


def _button_name(message):
    if message == WM_LBUTTONDOWN:
        return "left"
    if message == WM_RBUTTONDOWN:
        return "right"
    if message == WM_MBUTTONDOWN:
        return "middle"
    return "left"


def _vk_name(vk, scan_code=0, flags=0):
    if vk in _KEY_NAMES:
        return _KEY_NAMES[vk]
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    try:
        user32 = ctypes.windll.user32
        if not scan_code:
            scan_code = user32.MapVirtualKeyW(vk, 0)
        if flags & 0x01:
            scan_code |= 0x100
        name = ctypes.create_unicode_buffer(64)
        result = user32.GetKeyNameTextW(scan_code << 16, name, len(name))
        if result:
            return name.value.lower().replace(" ", "")
    except Exception:
        pass
    return f"vk_{vk}"


def _vk_text(vk, scan_code):
    if vk == 0x20:
        return " "
    try:
        user32 = ctypes.windll.user32
        keyboard_state = (ctypes.c_ubyte * 256)()
        if not user32.GetKeyboardState(ctypes.byref(keyboard_state)):
            return ""
        buff = ctypes.create_unicode_buffer(8)
        result = user32.ToUnicode(vk, scan_code, keyboard_state, buff, len(buff), 0)
        if result > 0:
            return buff.value[:result]
    except Exception:
        pass
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    return ""


def _make_callbacks():
    if not _is_windows_api_available():
        raise RuntimeError("Win32 hook APIs are unavailable on this host")

    lresult = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    hook_proc = ctypes.WINFUNCTYPE(lresult, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p)

    def mouse_proc(n_code, w_param, l_param):
        try:
            if n_code >= 0 and _RUNNING:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = int(info.pt.x), int(info.pt.y)
                message = int(w_param)
                if message == WM_MOUSEMOVE:
                    global _LAST_MOVE_TIME
                    now = time.time()
                    with _LOCK:
                        move_interval = _MOVE_INTERVAL_MS
                        last_move = _LAST_MOVE_TIME
                    if not move_interval or (now - last_move) * 1000 >= move_interval:
                        with _LOCK:
                            _LAST_MOVE_TIME = now
                        _append_event({"type": "move", "x": x, "y": y})
                elif message in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                    _append_event({"type": "click", "x": x, "y": y, "button": _button_name(message)})
                elif message == WM_MOUSEWHEEL:
                    delta = ctypes.c_short((int(info.mouseData) >> 16) & 0xFFFF).value
                    clicks = int(delta / 120) if delta else 0
                    _append_event({"type": "scroll", "x": x, "y": y, "clicks": clicks, "delta": delta})
        except Exception as e:
            _log(f"Recorder mouse hook error: {type(e).__name__}: {e}")
        return ctypes.windll.user32.CallNextHookEx(None, n_code, w_param, l_param)

    def keyboard_proc(n_code, w_param, l_param):
        try:
            if n_code >= 0 and _RUNNING and int(w_param) in (WM_KEYDOWN, WM_SYSKEYDOWN):
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = int(info.vkCode)
                scan_code = int(info.scanCode)
                flags = int(info.flags)
                name = _vk_name(vk, scan_code, flags)
                text = _vk_text(vk, scan_code)
                _append_event({
                    "type": "key",
                    "keys": [name],
                    "text": text,
                    "vk": vk,
                    "scan_code": scan_code,
                })
        except Exception as e:
            _log(f"Recorder keyboard hook error: {type(e).__name__}: {e}")
        return ctypes.windll.user32.CallNextHookEx(None, n_code, w_param, l_param)

    return hook_proc(mouse_proc), hook_proc(keyboard_proc)


def _hook_loop():
    global _RUNNING, _THREAD_ID, _HOOK_ERROR
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        mouse_cb, keyboard_cb = _make_callbacks()
        h_instance = kernel32.GetModuleHandleW(None)
        mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_cb, h_instance, 0)
        keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_cb, h_instance, 0)
        if not mouse_hook or not keyboard_hook:
            err = ctypes.GetLastError()
            if mouse_hook:
                user32.UnhookWindowsHookEx(mouse_hook)
            if keyboard_hook:
                user32.UnhookWindowsHookEx(keyboard_hook)
            raise OSError(err, "SetWindowsHookExW failed")
        with _LOCK:
            _CALLBACKS["mouse"] = mouse_cb
            _CALLBACKS["keyboard"] = keyboard_cb
            _HOOKS["mouse"] = mouse_hook
            _HOOKS["keyboard"] = keyboard_hook
            _THREAD_ID = kernel32.GetCurrentThreadId()
            _RUNNING = True
        _READY_EVENT.set()
        msg = ctypes.wintypes.MSG()
        while not _STOP_EVENT.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:
                break
            if result == -1:
                err = ctypes.GetLastError()
                _log(f"Recorder GetMessageW error: {err}")
                with _LOCK:
                    _RUNNING = False
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except Exception as e:
        with _LOCK:
            _RUNNING = False
            _HOOK_ERROR = f"{type(e).__name__}: {e}"
        _READY_EVENT.set()
        _log(f"Recorder hook setup failed: {_HOOK_ERROR}")
    finally:
        _unhook()
        with _LOCK:
            _RUNNING = False


def _unhook():
    if not _is_windows_api_available():
        return
    user32 = ctypes.windll.user32
    with _LOCK:
        hooks = list(_HOOKS.values())
        _HOOKS.clear()
        _CALLBACKS.clear()
    for hook in hooks:
        try:
            user32.UnhookWindowsHookEx(hook)
        except Exception:
            pass


def _stop_hooks():
    global _RUNNING
    if _is_windows_api_available():
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            with _LOCK:
                thread_id = _THREAD_ID
            if thread_id:
                user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            kernel32.SetLastError(0)
        except Exception:
            pass
    _STOP_EVENT.set()
    _unhook()
    with _LOCK:
        _RUNNING = False


def _safe_recording_name(name):
    if not isinstance(name, str) or not _SAFE_NAME.match(name) or name in {".", ".."}:
        raise ValueError("recording name must be 1-80 chars: letters, numbers, dot, dash, underscore")
    return name[:-5] if name.lower().endswith(".json") else name


def _recording_path(name):
    safe = _safe_recording_name(name)
    return (RECORDINGS_DIR / f"{safe}.json").resolve()


def _current_status():
    with _LOCK:
        return {
            "running": _RUNNING,
            "events": len(_RECORDING),
            "dropped_events": _DROPPED_EVENTS,
            "started_at": _START_TIME or None,
            "move_interval_ms": _MOVE_INTERVAL_MS,
            "max_events": _MAX_EVENTS,
            "hook_error": _HOOK_ERROR,
        }


def _json_response_from_client(resp):
    try:
        payload = resp.get_json(silent=True)
    except Exception:
        payload = None
    if payload is None:
        payload = resp.get_data(as_text=True)[:1000]
    return {"status_code": resp.status_code, "response": payload}


def _replay_event(client, event, auth_header):
    event_type = event.get("type")
    headers = {"Authorization": auth_header} if auth_header else {}
    if event_type == "move":
        resp = client.post("/mouse/move", json={
            "x": int(event.get("x", 0)),
            "y": int(event.get("y", 0)),
            "background": True,
        }, headers=headers)
    elif event_type == "click":
        resp = client.post("/mouse/click", json={
            "x": int(event.get("x", 0)),
            "y": int(event.get("y", 0)),
            "button": event.get("button", "left"),
            "background": True,
            "retry": False,
        }, headers=headers)
    elif event_type == "scroll":
        resp = client.post("/mouse/scroll", json={"clicks": int(event.get("clicks", 0))}, headers=headers)
    elif event_type == "type":
        resp = client.post("/key/type", json={"text": str(event.get("text", ""))}, headers=headers)
    elif event_type == "key":
        text = event.get("text", "")
        if isinstance(text, str) and text and len(text) <= 8:
            resp = client.post("/key/type", json={"text": text}, headers=headers)
        else:
            resp = client.post("/key/press", json={"keys": event.get("keys", [])}, headers=headers)
    else:
        return {"status_code": 400, "response": {"error": f"unknown event type: {event_type}"}}
    return _json_response_from_client(resp)


def register_routes(app, state, require_auth):
    @app.route("/recorder/status", methods=["GET"])
    @require_auth
    def route_recorder_status():
        return jsonify(_current_status())

    @app.route("/recorder/start", methods=["POST"])
    @require_auth
    def route_recorder_start():
        global _THREAD, _START_TIME, _LAST_EVENT_TIME, _LAST_MOVE_TIME
        global _MOVE_INTERVAL_MS, _MAX_EVENTS, _DROPPED_EVENTS, _HOOK_ERROR
        if not _is_windows_api_available():
            return jsonify({"error": "Win32 global hooks require Windows interactive desktop"}), 501
        data = _json_body()
        with _LOCK:
            if _RUNNING:
                return jsonify({"status": "already_running", **_current_status()})
            if not data.get("append"):
                _RECORDING.clear()
                _DROPPED_EVENTS = 0
            _MOVE_INTERVAL_MS = max(0, min(int(data.get("move_interval_ms", 0)), 10000))
            _MAX_EVENTS = max(100, min(int(data.get("max_events", 20000)), 500000))
            _START_TIME = time.time()
            _LAST_EVENT_TIME = 0.0
            _LAST_MOVE_TIME = 0.0
            _HOOK_ERROR = ""
            _STOP_EVENT.clear()
            _READY_EVENT.clear()
            _THREAD = threading.Thread(target=_hook_loop, name="recorder_hooks", daemon=True)
            _THREAD.start()
        _READY_EVENT.wait(timeout=3.0)
        status = _current_status()
        if not status["running"]:
            return jsonify({"error": "recorder failed to start", **status}), 500
        return jsonify({"status": "recording", **status})

    @app.route("/recorder/stop", methods=["POST"])
    @require_auth
    def route_recorder_stop():
        _stop_hooks()
        thread = _THREAD
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        with _LOCK:
            recording = list(_RECORDING)
        return jsonify({"status": "stopped", "count": len(recording), "recording": recording, **_current_status()})

    @app.route("/recorder/replay", methods=["POST"])
    @require_auth
    def route_recorder_replay():
        data = _json_body()
        recording = data.get("recording")
        if recording is None:
            with _LOCK:
                recording = list(_RECORDING)
        if not isinstance(recording, list):
            return jsonify({"error": "recording must be a JSON array"}), 400
        speed = float(data.get("speed", 1.0) or 1.0)
        speed = max(0.05, min(speed, 20.0))
        max_events = max(1, min(int(data.get("max_events", len(recording))), len(recording)))
        max_total_ms = int(data.get("max_total_ms", 300000))  # 5 minute default cap
        max_total_ms = max(1000, min(max_total_ms, 3600000))
        auth_header = request.headers.get("Authorization", "")
        results = []
        total_slept_ms = 0
        with app.test_client() as client:
            for event in recording[:max_events]:
                if not isinstance(event, dict):
                    results.append({"status_code": 400, "response": {"error": "event must be an object"}})
                    continue
                delay_ms = max(0, int(event.get("delay_ms", 0)))
                effective_delay = min(delay_ms, max(0, max_total_ms - total_slept_ms))
                if effective_delay > 0:
                    time.sleep((effective_delay / 1000.0) / speed)
                    total_slept_ms += effective_delay
                result = _replay_event(client, event, auth_header)
                results.append(result)
                if int(result.get("status_code", 500)) >= 500 and data.get("stop_on_error", True):
                    break
        return jsonify({"status": "replayed", "requested": len(recording), "replayed": len(results), "results": results})

    @app.route("/recorder/list", methods=["POST", "GET"])
    @require_auth
    def route_recorder_list():
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        items = []
        for path in sorted(RECORDINGS_DIR.glob("*.json")):
            item = {"name": path.stem, "file": str(path), "bytes": path.stat().st_size, "mtime": path.stat().st_mtime}
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                item["events"] = len(loaded) if isinstance(loaded, list) else len(loaded.get("recording", []))
            except Exception:
                item["events"] = None
            items.append(item)
        return jsonify({"recordings": items, "count": len(items), "directory": str(RECORDINGS_DIR)})

    @app.route("/recorder/save/<name>", methods=["POST"])
    @require_auth
    def route_recorder_save(name):
        data = _json_body()
        recording = data.get("recording")
        if recording is None:
            with _LOCK:
                recording = list(_RECORDING)
        if not isinstance(recording, list):
            return jsonify({"error": "recording must be a JSON array"}), 400
        try:
            path = _recording_path(name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(recording, indent=2), encoding="utf-8")
        return jsonify({"status": "saved", "name": path.stem, "file": str(path), "count": len(recording)})

    @app.route("/recorder/load/<name>", methods=["POST", "GET"])
    @require_auth
    def route_recorder_load(name):
        try:
            path = _recording_path(name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not path.exists():
            return jsonify({"error": "recording not found", "name": name}), 404
        try:
            recording = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return jsonify({"error": f"failed to read recording: {e}"}), 500
        if isinstance(recording, dict):
            recording = recording.get("recording", [])
        if not isinstance(recording, list):
            return jsonify({"error": "recording file does not contain a JSON array"}), 400
        with _LOCK:
            _RECORDING.clear()
            _RECORDING.extend(recording)
        return jsonify({"status": "loaded", "name": path.stem, "file": str(path), "count": len(recording), "recording": recording})

    # ── Macro Auto-Verification (v8.2) ──────────────────────────────────

    def _verify_replay(macro_name, before_path, after_path):
        """
        Compare before/after screenshots and return verification result.
        Uses PIL pixel-diff to compute difference score.
        """
        try:
            from PIL import Image, ImageChops, ImageDraw
        except ImportError:
            return {"verified": None, "error": "Pillow not available"}

        try:
            before = Image.open(before_path).convert("RGB")
            after = Image.open(after_path).convert("RGB")
        except Exception as e:
            return {"verified": None, "error": f"Failed to open images: {e}"}

        if before.size != after.size:
            after = after.resize(before.size)

        try:
            diff = ImageChops.difference(before, after)
            bbox = diff.getbbox()
            changed_pixels = sum(1 for p in diff.getdata() if p != (0, 0, 0))
            total_pixels = before.width * before.height
            diff_score = round(changed_pixels / max(total_pixels, 1), 4)

            # Create highlighted diff image
            highlighted = after.copy()
            draw = ImageDraw.Draw(highlighted, "RGBA")
            # Only highlight if there's a meaningful change
            if bbox and diff_score > 0.01:
                # Red overlay on changed regions
                changed_data = [
                    (255, 0, 0, 80) if p != (0, 0, 0) else (0, 0, 0, 0)
                    for p in diff.getdata()
                ]
                overlay = Image.new("RGBA", before.size)
                overlay.putdata(changed_data)
                highlighted = Image.alpha_composite(highlighted.convert("RGBA"), overlay)
                highlighted = highlighted.convert("RGB")

            diff_dir = Path(RECORDINGS_DIR) / macro_name
            diff_dir.mkdir(parents=True, exist_ok=True)
            diff_path = str(diff_dir / "verification_diff.png")
            highlighted.save(diff_path)

            result = {
                "verified": diff_score < 0.1,  # < 10% change = same screen
                "diff_score": diff_score,
                "changed_pixels": changed_pixels,
                "total_pixels": total_pixels,
                "before_path": before_path,
                "after_path": after_path,
                "diff_image_path": diff_path,
            }

            # Save verification result
            ver_path = diff_dir / "verification.json"
            ver_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

            return result
        except Exception as e:
            return {"verified": None, "error": str(e)}

    @app.route("/macro/verify/<name>", methods=["GET"])
    @require_auth
    def route_macro_verify(name):
        """Retrieve macro verification results."""
        try:
            name = _safe_recording_name(name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        ver_path = RECORDINGS_DIR / name / "verification.json"
        if not ver_path.exists():
            return jsonify({"error": "No verification found", "name": name}), 404
        try:
            data = json.loads(ver_path.read_text(encoding="utf-8"))
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/macro/verify/<name>/run", methods=["POST"])
    @require_auth
    def route_macro_verify_run(name):
        """Run verification on the most recent replay of a macro."""
        try:
            from routes_ocr import _capture_raw
        except ImportError:
            return jsonify({"error": "OCR module not available"}), 500

        try:
            name = _safe_recording_name(name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        # Take before screenshot
        try:
            before_data = _capture_raw(force=True)
            before_path = str(RECORDINGS_DIR / name / "verify_before.png")
            if isinstance(before_data, bytes):
                with open(before_path, "wb") as f:
                    f.write(before_data)
            else:
                import mss as _mss_mod
                from PIL import Image as _PILImage
                with _mss_mod.mss() as _sct:
                    _mon = _sct.monitors[0]
                    _sct_img = _sct.grab(_mon)
                    PIL_before = _PILImage.frombytes("RGB", _sct_img.size, _sct_img.rgb)
                PIL_before.save(before_path)
        except Exception as e:
            return jsonify({"error": f"Before screenshot failed: {e}"}), 500

        # Load and replay the macro
        rec_path = RECORDINGS_DIR / f"{name}.json"
        if not rec_path.exists():
            return jsonify({"error": "Recording not found", "name": name}), 404
        recording = json.loads(rec_path.read_text(encoding="utf-8"))
        if isinstance(recording, dict):
            recording = recording.get("recording", [])

        auth_header = request.headers.get("Authorization", "")
        results = []
        with app.test_client() as client:
            for event in recording:
                delay_ms = max(0, int(event.get("delay_ms", 0)))
                if delay_ms > 0:
                    time.sleep(min(delay_ms / 1000.0, 5.0))
                result = _replay_event(client, event, auth_header)
                results.append(result)

        # Take after screenshot
        try:
            after_data = _capture_raw(force=True)
            after_path = str(RECORDINGS_DIR / name / "verify_after.png")
            if isinstance(after_data, bytes):
                with open(after_path, "wb") as f:
                    f.write(after_data)
            else:
                import mss as _mss_mod
                from PIL import Image as _PILImage
                with _mss_mod.mss() as _sct:
                    _mon = _sct.monitors[0]
                    _sct_img = _sct.grab(_mon)
                    PIL_after = _PILImage.frombytes("RGB", _sct_img.size, _sct_img.rgb)
                PIL_after.save(after_path)
        except Exception as e:
            return jsonify({"error": f"After screenshot failed: {e}"}), 500

        # Verify
        verification = _verify_replay(name, before_path, after_path)
        return jsonify({
            "status": "verified",
            "name": name,
            "events_replayed": len(recording),
            "verification": verification,
            "results": results[:5],  # First 5 event results
        })

"""Mouse, keyboard, input, and action-chain routes."""
import threading
import time
import ctypes
import ctypes.wintypes
import hashlib
import math
import random
from flask import jsonify
from shared import _json_body, _log, _missing_field, _result_response

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None
    import types as _t
    _s = _t.ModuleType('pyautogui')
    for a in ('position','moveTo','click','doubleClick','rightClick','typewrite','hotkey','scroll','drag'):
        setattr(_s, a, lambda *a,**kw: None)
    _s.FAILSAFE = False
    pyautogui = _s

PULSE_DEFAULT_COLOR = 0x00FF00
PULSE_ACTION_COLORS = {"click": 0xFF4400, "doubleclick": 0xFF4400, "rightclick": 0xFF4400,
                       "type": 0x4488FF, "hotkey": 0xFF00FF, "scroll": 0xFFFF00, "drag": 0xFFAA00}

def _as_bool(value, default=True):
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

def _screen_hash():
    try:
        from routes_ocr import _capture_raw
        data = _capture_raw(force=True)
        if not data:
            return None
        return hashlib.blake2b(data, digest_size=16).hexdigest()
    except Exception as e:
        _log(f"Click retry screenshot hash failed: {type(e).__name__}: {e}")
        return None

def _response_failed(result):
    if isinstance(result, tuple):
        try:
            return int(result[1]) >= 400
        except Exception:
            return False
    status_code = getattr(result, "status_code", 200)
    try:
        return int(status_code) >= 400
    except Exception:
        return False

def _result_payload(result):
    response = result
    status_code = getattr(result, "status_code", 200)
    if isinstance(result, tuple):
        response = result[0]
        if len(result) > 1:
            status_code = result[1]
    try:
        status_code = int(status_code)
    except Exception:
        status_code = 200
    if hasattr(response, "get_json"):
        payload = response.get_json(silent=True)
    elif hasattr(response, "json"):
        payload = response.json() if callable(response.json) else response.json
    else:
        payload = response
    if isinstance(payload, (dict, list, str, int, float, bool)) or payload is None:
        return payload, status_code
    return str(payload), status_code

def _record_action(action_type, data, result=None):
    try:
        import coagent_features as cf
        recorder = getattr(cf, "record_action", None)
        if recorder:
            recorder(action_type, data, result)
    except ModuleNotFoundError as e:
        if e.name != "coagent_features":
            _log(f"Session recording failed for {action_type}: {type(e).__name__}: {e}")
    except Exception as e:
        _log(f"Session recording failed for {action_type}: {type(e).__name__}: {e}")

def _set_cursor_pos(x, y):
    if hasattr(ctypes, "windll"):
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        return
    pyautogui.moveTo(int(x), int(y))

# ── Input preflight guard (opt-in target verification) ───────────────────
# The #1 silent failure in unattended desktop automation is input landing in
# the wrong window: a focus change, stray popup, or stale coordinate turns a
# "click OK" into typing into the wrong app. This guard, when a caller supplies
# a `target` object, verifies the foreground window matches (by hwnd / pid /
# title / process) and that any supplied coordinates fall inside that window's
# screen rect BEFORE any input is injected. Without `target` it is a no-op.

def _process_name(pid):
    """Resolve a PID to its executable basename (lowercase) via Win32."""
    try:
        if not hasattr(ctypes, "windll"):
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return ""
        try:
            import os
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.wintypes.DWORD(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return ""


def _fg_window_info():
    """Return {hwnd, title, pid, proc, rect} for the foreground window, or None."""
    try:
        if not hasattr(ctypes, "windll"):
            return None
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        title = ""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return {
            "hwnd": int(hwnd),
            "title": title,
            "pid": int(pid.value),
            "proc": _process_name(pid.value),
            "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
        }
    except Exception:
        return None


def _preflight_guard(body):
    """Verify foreground window + coordinate bounds before input lands.

    Returns (ok: bool, error_response_or_None). Opt-in: only active when the
    request body carries a non-empty `target` object, so existing callers are
    unaffected. On mismatch returns a structured 409 so the agent can react
    instead of mis-clicking/typing into the wrong window.
    """
    if not isinstance(body, dict):
        return True, None
    target = body.get("target")
    if not isinstance(target, dict) or not target:
        return True, None

    fg = _fg_window_info()
    if fg is None:
        return False, (jsonify({
            "error": "input preflight: cannot resolve foreground window",
            "reason": "fg_window_unavailable",
            "target": target,
        }), 409)

    failed = None
    try:
        if target.get("hwnd") is not None:
            want = int(target["hwnd"])
            if want != fg["hwnd"]:
                failed = {"reason": "hwnd_mismatch", "expected": want, "actual": fg["hwnd"]}
        if failed is None and target.get("pid") is not None:
            want = int(target["pid"])
            if want != fg["pid"]:
                failed = {"reason": "pid_mismatch", "expected": want, "actual": fg["pid"]}
    except (TypeError, ValueError):
        return False, (jsonify({"error": "input preflight: hwnd/pid must be integers"}), 400)
    if failed is None and target.get("title"):
        want = str(target["title"]).lower()
        if want not in fg["title"].lower():
            failed = {"reason": "title_mismatch", "expected": target["title"], "actual": fg["title"]}
    if failed is None and target.get("process"):
        want = str(target["process"]).lower()
        if want not in fg["proc"] and want not in fg["title"].lower():
            failed = {"reason": "process_mismatch", "expected": target["process"], "actual": fg["proc"]}

    if failed is not None:
        return False, (jsonify({
            "error": "input preflight: foreground window does not match target",
            "reason": failed["reason"],
            "expected": failed.get("expected"),
            "foreground": {
                "hwnd": fg["hwnd"], "pid": fg["pid"],
                "title": fg["title"][:200], "process": fg["proc"],
            },
            "target": target,
        }), 409)

    # Coordinate bounds check — collect every (x, y) pair the action may use.
    points = []
    if body.get("x") is not None and body.get("y") is not None:
        points.append((body.get("x"), body.get("y")))
    for key in ("x1", "x2"):
        if body.get(key) is not None and body.get(key.replace("x", "y")) is not None:
            points.append((body.get(key), body.get(key.replace("x", "y"))))
    for key in ("from", "to"):
        sub = body.get(key)
        if isinstance(sub, dict) and sub.get("x") is not None and sub.get("y") is not None:
            points.append((sub.get("x"), sub.get("y")))

    r = fg["rect"]
    for sx, sy in points:
        try:
            px, py = int(sx), int(sy)
        except (TypeError, ValueError):
            return False, (jsonify({"error": "input preflight: coordinates must be integers"}), 400)
        if not (r["left"] <= px <= r["right"] and r["top"] <= py <= r["bottom"]):
            return False, (jsonify({
                "error": "input preflight: coordinates outside target window",
                "reason": "coord_out_of_bounds",
                "point": {"x": px, "y": py},
                "rect": r,
            }), 409)

    return True, None

def _mouse_click_with_retry(x, y, button="left", background=True, state=None):
    offsets = [(0, 0), (10, 10), (-10, -10), (20, 20), (-20, -20), (0, 15), (0, -15)]
    attempts = []
    baseline_hash = _screen_hash()
    for index, (dx, dy) in enumerate(offsets):
        cx, cy = x + dx, y + dy
        result = _mouse_action("click", cx, cy, button, background, state)
        if _response_failed(result):
            return result
        time.sleep(0.3)
        after_hash = _screen_hash()
        changed = bool(baseline_hash and after_hash and baseline_hash != after_hash)
        attempts.append({
            "position": [cx, cy],
            "changed": changed,
            "screenshot_compared": bool(baseline_hash and after_hash),
        })
        if changed or not (baseline_hash and after_hash):
            return jsonify({
                "status": "ok",
                "clicked": True,
                "action": "click",
                "retries": index,
                "final_position": [cx, cy],
                "attempts": attempts,
            })
        baseline_hash = after_hash
    final = attempts[-1]["position"] if attempts else [x, y]
    return jsonify({
        "status": "ok",
        "clicked": True,
        "action": "click",
        "retries": max(0, len(attempts) - 1),
        "final_position": final,
        "attempts": attempts,
        "warning": "Screen appeared unchanged after all retry positions",
    })

_GLOBAL_INPUT_LOCK = threading.RLock()

def _background_sendinput(action, x, y, button="left"):
    """Send input without stealing focus using SendInput."""
    if action == "move":
        return _set_cursor_pos(x, y)
    if not hasattr(ctypes, 'windll'):
        return pyautogui.click(x, y, button=button)
    try:
        MOUSEEVENTF_LEFTDOWN = 0x0002; MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008; MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_ABSOLUTE = 0x8000
        MOUSEEVENTF_MOVE = 0x0001
        btn_down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        btn_up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
        # Normalize coordinates for absolute positioning across the full virtual desktop
        # (GetSystemMetrics(0/1) only covers the primary monitor).
        MOUSEEVENTF_VIRTUALDESK = 0x4000
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
        screen_x = ctypes.windll.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        screen_y = ctypes.windll.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        screen_w = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        screen_h = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        nx = int(((x - screen_x) * 65535) / screen_w) if screen_w else 0
        ny = int(((y - screen_y) * 65535) / screen_h) if screen_h else 0
        # Move cursor to absolute position first
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MOVE, nx, ny, 0, 0)
        time.sleep(0.01)
        if action == "doubleclick":
            ctypes.windll.user32.mouse_event(btn_down, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(btn_up, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(btn_down, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(btn_up, 0, 0, 0, 0)
    except Exception:
        # Fallback: respect the requested action instead of collapsing everything
        # to a single click (doubleclick/rightclick must not silently degrade).
        if action == "doubleclick":
            pyautogui.doubleClick(x, y, button=button)
        elif action == "rightclick":
            pyautogui.rightClick(x, y)
        else:
            pyautogui.click(x, y, button=button)

def _mouse_action(action, x, y, button="left", background=True, state=None):
    if state and state.emergency_stop:
        return jsonify({
            "ok": False,
            "error": "Emergency stop is engaged",
            "detail": "The emergency stop flag was set, all mouse input is blocked",
            "suggestion": "POST /stop to release the emergency stop, then retry",
            "code": "EMERGENCY_STOP",
        }), 503
    lock = state.input_lock if (state and hasattr(state, 'input_lock')) else _GLOBAL_INPUT_LOCK
    with lock:
        # Re-check emergency stop after acquiring lock
        if state and state.emergency_stop:
            return jsonify({
                "ok": False,
                "error": "Emergency stop is engaged",
                "detail": "The emergency stop flag was set after acquiring the input lock",
                "suggestion": "POST /stop to release the emergency stop, then retry",
                "code": "EMERGENCY_STOP",
            }), 503
        now = time.time()
        gap = now - (state.last_action_time if state else 0)
        if gap < (state.min_action_gap if state else 0.05):
            time.sleep((state.min_action_gap if state else 0.05) - gap)
        _set_cursor_pos(x, y)
        if action == "move":
            if state: state.last_action_time = time.time()
            payload = {"status": "ok", "action": action, "x": x, "y": y}
            _log(f"Mouse {action} ({x},{y}) button={button} bg={background}")
            _record_action(action, {"x": x, "y": y, "button": button, "background": background}, payload)
            return jsonify(payload)
        time.sleep(0.02)
        if background:
            _background_sendinput(action, x, y, button)
        else:
            # Normalize action names: routes use lowercase, pyautogui uses camelCase
            _action_map = {"click": "click", "doubleclick": "doubleClick", "rightclick": "rightClick"}
            _pa_action = _action_map.get(action, "click")
            getattr(pyautogui, _pa_action)(x, y, button=button)
        if state: state.last_action_time = time.time()
    _log(f"Mouse {action} ({x},{y}) button={button} bg={background}")
    payload = {"status": "ok", "action": action, "x": x, "y": y}
    _record_action(action, {"x": x, "y": y, "button": button, "background": background}, payload)
    return jsonify(payload)

def _execute_action_wrapper(action, state=None):
    """Execute a stored action dict."""
    _ok, _err = _preflight_guard(action)
    if not _ok:
        return _err
    typ = action.get("type", "")
    if typ == "click":
        return _mouse_action("click", action.get("x", 0), action.get("y", 0),
                             action.get("button", "left"), action.get("background", True), state)
    elif typ == "move":
        return _mouse_action("move", action.get("x", 0), action.get("y", 0),
                             "left", True, state)
    elif typ == "type":
        return _key_action("type", action.get("text", ""), state)
    elif typ == "hotkey":
        return _key_action("hotkey", action.get("keys", []), state)
    elif typ == "scroll":
        return _scroll_action(action.get("clicks", -3), state)
    return jsonify({"error": f"Unknown action type: {typ}"}), 400

def _key_action(action, data, state=None):
    if state and state.emergency_stop:
        return jsonify({
            "ok": False,
            "error": "Emergency stop is engaged",
            "detail": "The emergency stop flag was set, all keyboard input is blocked",
            "suggestion": "POST /stop to release the emergency stop, then retry",
            "code": "EMERGENCY_STOP",
        }), 503
    lock = state.input_lock if (state and hasattr(state, 'input_lock')) else _GLOBAL_INPUT_LOCK
    with lock:
        if state and state.emergency_stop:
            return jsonify({
                "ok": False,
                "error": "Emergency stop is engaged",
                "detail": "Emergency stop set after acquiring the input lock",
                "suggestion": "POST /stop to release the emergency stop, then retry",
                "code": "EMERGENCY_STOP",
            }), 503
        try:
            if action == "type":
                text = str(data)
                pyautogui.typewrite(text, interval=0.01)
            elif action == "hotkey":
                if isinstance(data, list):
                    pyautogui.hotkey(*data)
                else:
                    pyautogui.write(str(data))
            _log(f"Key {action}: {data}")
            payload = {"status": "ok", "action": action}
            record_data = {"text": str(data)} if action == "type" else {"keys": data if isinstance(data, list) else str(data)}
            _record_action(action, record_data, payload)
            return jsonify(payload)
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": f"Keyboard action {action!r} failed",
                "detail": f"{type(e).__name__}: {e}",
                "suggestion": "Ensure pyautogui is installed and an active desktop session exists",
                "code": "KEY_ACTION_FAILED",
            }), 500

def _scroll_action(clicks, state=None):
    if state and state.emergency_stop:
        return jsonify({
            "ok": False,
            "error": "Emergency stop is engaged",
            "detail": "The emergency stop flag was set, all scroll input is blocked",
            "suggestion": "POST /stop to release the emergency stop, then retry",
            "code": "EMERGENCY_STOP",
        }), 503
    try:
        amount = int(clicks)
        pyautogui.scroll(amount)
        payload = {"status": "ok", "clicks": amount}
        _record_action("scroll", {"clicks": amount}, payload)
        return jsonify(payload)
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "Scroll action failed",
            "detail": f"{type(e).__name__}: {e}",
            "suggestion": "Ensure pyautogui is installed and a window is focused",
            "code": "SCROLL_FAILED",
        }), 500

def register_routes(app, state, require_auth):
    @app.route("/mouse/move", methods=["POST"])
    @require_auth
    def route_mouse_move():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        return _mouse_action("move", int(d.get("x", 0)), int(d.get("y", 0)),
                             "left", d.get("background", True), state)

    @app.route("/mouse/click", methods=["POST"])
    @require_auth
    def route_mouse_click():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        x = int(d.get("x", 0))
        y = int(d.get("y", 0))
        # Guard: block (0,0) clicks — likely a rogue automation call
        if x == 0 and y == 0:
            _log(f"[GUARD] Blocked click at (0,0) from caller")
            return jsonify({"status": "blocked", "reason": "click_at_origin_blocked", "x": 0, "y": 0})
        retry = _as_bool(d.get("retry"), True)
        if retry:
            return _mouse_click_with_retry(x, y,
                                           d.get("button", "left"), d.get("background", True), state)
        return _mouse_action("click", x, y,
                             d.get("button", "left"), d.get("background", True), state)

    @app.route("/mouse/click/focus", methods=["POST"])
    @require_auth
    def route_mouse_click_focus():
        """Click with focus transfer. Uses pyautogui.click() which naturally transfers window focus
        to the clicked window, enabling subsequent keyboard input to go there.
        NOTE: MOUSEEVENTF_ABSOLUTE via ctypes requires normalized 0-65535 coordinates, not raw pixels.
        pyautogui handles this correctly internally, so we use it directly."""
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        x = int(d.get("x", 0))
        y = int(d.get("y", 0))
        button = d.get("button", "left")
        if state and state.emergency_stop:
            return jsonify({"error": "Emergency stop engaged"}), 503
        try:
            pyautogui.click(x, y, button=button)
        except Exception as e:
            _log(f"Focus-click pyautogui failed: {e}")
            return jsonify({"error": str(e)}), 500
        if state:
            state.last_action_time = time.time()
        _log(f"Mouse focus-click ({x},{y}) button={button}")
        return jsonify({"status": "ok", "action": "focus_click", "x": x, "y": y, "button": button})

    @app.route("/window/list", methods=["GET"])
    @require_auth
    def route_window_list():
        """List all visible windows on the desktop with their titles and PIDs."""
        try:
            windows = []
            def _enum_cb(hwnd, _lparam):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    if title.strip():
                        pid = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        rect = ctypes.wintypes.RECT()
                        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        visible = ctypes.windll.user32.IsWindowVisible(hwnd)
                        windows.append({
                            "hwnd": hwnd,
                            "pid": pid.value,
                            "title": title[:200],
                            "visible": bool(visible),
                            "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}
                        })
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            cb = WNDENUMPROC(_enum_cb)
            ctypes.windll.user32.EnumWindows(cb, 0)
            return jsonify({"status": "ok", "count": len(windows), "windows": windows})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/window/focus", methods=["POST"])
    @require_auth
    def route_window_focus():
        """Bring a window to the foreground by PID or title substring match.
        POST body: {"pid": 1234} or {"title": "Shopify"} or {"name": "msedge"}"""
        d = _json_body()
        target_pid = d.get("pid")
        if target_pid is not None:
            try:
                target_pid = int(target_pid)
            except (TypeError, ValueError):
                return jsonify({"error": "pid must be an integer"}), 400
        target_title = d.get("title")
        target_name = d.get("name")
        if not any([target_pid, target_title, target_name]):
            return jsonify({"error": "Provide pid, title, or name"}), 400
        try:
            windows = []
            def _enum_cb(hwnd, _lparam):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    if title.strip():
                        pid = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        windows.append((hwnd, title, pid.value))
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            cb = WNDENUMPROC(_enum_cb)
            ctypes.windll.user32.EnumWindows(cb, 0)

            matches = []
            for hwnd, title, pid in windows:
                if target_pid and pid == target_pid:
                    matches.append((hwnd, title, pid))
                elif target_title and target_title.lower() in title.lower():
                    matches.append((hwnd, title, pid))
                elif target_name:
                    proc_name = ""
                    try:
                        import psutil
                        proc_name = psutil.Process(pid).name().lower()
                    except Exception:
                        pass
                    if target_name.lower() in title.lower() or target_name.lower() in proc_name:
                        matches.append((hwnd, title, pid))

            if not matches:
                return jsonify({"error": f"No window found matching criteria", "windows_found": len(windows)}), 404

            hwnd, title, pid = matches[0]

            # Suppress known overlay/blocker windows that can prevent focus transfer
            overlay_keywords = ["Windows Input Experience", "NVIDIA GeForce Overlay"]
            for ohwnd, otitle, opid in windows:
                for kw in overlay_keywords:
                    if kw.lower() in otitle.lower():
                        ctypes.windll.user32.ShowWindow(ohwnd, 0)  # SW_HIDE
                        _log(f"Hidden overlay: '{otitle[:60]}' HWND={ohwnd}")
                        break

            time.sleep(0.1)
            SW_RESTORE = 9
            SW_SHOW = 5
            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.05)
            ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
            time.sleep(0.05)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            ctypes.windll.user32.BringWindowToTop(hwnd)
            time.sleep(0.05)

            fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
            success = (fg_hwnd == hwnd)
            _log(f"Window focus: '{title}' PID={pid} HWND={hwnd} success={success}")
            return jsonify({
                "status": "ok",
                "action": "window_focus",
                "hwnd": hwnd,
                "pid": pid,
                "title": title[:200],
                "foreground_matches": success,
                "total_matches": len(matches)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/mouse/click/smart", methods=["POST"])
    @require_auth
    def route_mouse_click_smart():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        x = int(d.get("x", 0))
        y = int(d.get("y", 0))
        if x == 0 and y == 0:
            return jsonify({"status": "blocked", "reason": "click_at_origin_blocked"})
        return _mouse_click_with_retry(x, y,
                                       d.get("button", "left"), d.get("background", True), state)

    @app.route("/mouse/dblclick", methods=["POST"])
    @require_auth
    def route_mouse_dblclick():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        return _mouse_action("doubleclick", int(d.get("x", 0)), int(d.get("y", 0)),
                             d.get("button", "left"), d.get("background", True), state)

    @app.route("/mouse/rclick", methods=["POST"])
    @require_auth
    def route_mouse_rclick():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        return _mouse_action("rightclick", int(d.get("x", 0)), int(d.get("y", 0)),
                             "right", d.get("background", True), state)

    @app.route("/mouse/drag", methods=["POST"])
    @require_auth
    def route_mouse_drag():
        """Smooth drag with human-like path interpolation.

        Accepts either:
          {"from": {"x": N, "y": N}, "to": {"x": N, "y": N}, ...}
        or legacy flat format:
          {"x1": N, "y1": N, "x2": N, "y2": N, ...}

        Optional: button ("left"|"right"), steps (default 20),
                  duration_ms (default 500), background (bool).
        """
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        btn = d.get("button", "left")
        steps = max(5, min(200, int(d.get("steps", 20))))
        duration_ms = max(50, min(10000, int(d.get("duration_ms", 500))))

        if "from" in d and "to" in d:
            src = d["from"]
            dst = d["to"]
            x1, y1 = int(src.get("x", 0)), int(src.get("y", 0))
            x2, y2 = int(dst.get("x", 0)), int(dst.get("y", 0))
        else:
            x1, y1 = int(d.get("x1", 0)), int(d.get("y1", 0))
            x2, y2 = int(d.get("x2", 0)), int(d.get("y2", 0))

        if state and state.emergency_stop:
            return jsonify({"ok": False, "error": "Emergency stop engaged",
                            "code": "EMERGENCY_STOP"}), 503

        lock = state.input_lock if (state and hasattr(state, "input_lock")) else _GLOBAL_INPUT_LOCK
        with lock:
            if state and state.emergency_stop:
                return jsonify({"ok": False, "error": "Emergency stop engaged",
                                "code": "EMERGENCY_STOP"}), 503
            try:
                step_delay = (duration_ms / 1000.0) / max(1, steps)
                dx = x2 - x1
                dy = y2 - y1
                dist = math.hypot(dx, dy)
                max_jitter = dist * 0.025  # 2.5% of drag distance as max jitter

                if hasattr(ctypes, "windll"):
                    MOUSEEVENTF_LEFTDOWN = 0x0002
                    MOUSEEVENTF_LEFTUP = 0x0004
                    MOUSEEVENTF_RIGHTDOWN = 0x0008
                    MOUSEEVENTF_RIGHTUP = 0x0010
                    btn_down = MOUSEEVENTF_LEFTDOWN if btn == "left" else MOUSEEVENTF_RIGHTDOWN
                    btn_up = MOUSEEVENTF_LEFTUP if btn == "left" else MOUSEEVENTF_RIGHTUP

                    pressed = False
                    try:
                        ctypes.windll.user32.SetCursorPos(x1, y1)
                        time.sleep(0.05)
                        ctypes.windll.user32.mouse_event(btn_down, 0, 0, 0, 0)
                        pressed = True
                        time.sleep(0.02)

                        for i in range(1, steps + 1):
                            t = i / steps
                            # Cubic ease-in-out for natural acceleration/deceleration
                            t_e = t * t * (3.0 - 2.0 * t)
                            cx = x1 + dx * t_e
                            cy = y1 + dy * t_e
                            # Perpendicular jitter that tapers at endpoints
                            if dist > 1 and max_jitter > 0:
                                taper = min(t, 1.0 - t) * 4.0
                                jitter = random.gauss(0, max_jitter * taper * 0.4)
                                perp_x = -dy / dist
                                perp_y = dx / dist
                                cx += perp_x * jitter
                                cy += perp_y * jitter
                            ctypes.windll.user32.SetCursorPos(int(cx), int(cy))
                            time.sleep(step_delay)

                        ctypes.windll.user32.SetCursorPos(x2, y2)
                        time.sleep(0.02)
                    finally:
                        # Always release the button, even if interpolation raised
                        if pressed:
                            ctypes.windll.user32.mouse_event(btn_up, 0, 0, 0, 0)
                else:
                    pyautogui.moveTo(x1, y1)
                    pyautogui.drag(x2 - x1, y2 - y1, button=btn,
                                   duration=duration_ms / 1000.0)

                if state:
                    state.last_action_time = time.time()
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        _log(f"Drag ({x1},{y1})->({x2},{y2}) btn={btn} steps={steps} dur={duration_ms}ms")
        payload = {"status": "ok", "action": "drag",
                   "from": {"x": x1, "y": y1}, "to": {"x": x2, "y": y2},
                   "button": btn, "steps": steps, "duration_ms": duration_ms}
        _record_action("drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                                "button": btn, "steps": steps,
                                "duration_ms": duration_ms}, payload)
        return jsonify(payload)

    @app.route("/mouse/scroll", methods=["POST"])
    @require_auth
    def route_mouse_scroll():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        return _scroll_action(d.get("clicks", -3), state)

    @app.route("/key/type", methods=["POST"])
    @require_auth
    def route_key_type():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        text = d.get("text", "")
        mode = str(d.get("mode", "unicode")).lower()
        if len(text) <= 5:
            _log(f"[GUARD] Blocked short/trivial keystroke: '{text}'")
            return jsonify({"status": "blocked", "reason": "trivial_keystroke_blocked"})
        if mode == "scancode":
            try:
                from uia_engine import send_keys_scancode
            except ImportError:
                return jsonify({"error": "uia_engine unavailable for scancode typing"}), 501
            try:
                hold_ms = int(d.get("hold_ms", 10))
            except (TypeError, ValueError):
                hold_ms = 10
            result = send_keys_scancode(text, hold_ms=hold_ms)
            if not result.get("success"):
                return jsonify(result), 500
            _log(f"Key type (scancode): {len(text)} chars")
            _record_action("type", {"text": text, "mode": "scancode"}, result)
            return jsonify({"status": "ok", "action": "type", "mode": "scancode", **result})
        return _key_action("type", text, state)

    @app.route("/key/method", methods=["GET"])
    @require_auth
    def route_key_method():
        """Report supported keyboard injection modes."""
        return jsonify({
            "status": "ok",
            "default": "unicode",
            "supported": ["unicode", "scancode"],
            "usage": "POST /key/type with {\"mode\": \"scancode\"} for hardware scan-code "
                     "injection (RDP / games / elevated windows); unicode is the default.",
        })

    @app.route("/key/press", methods=["POST"])
    @require_auth
    def route_key_press():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        return _key_action("hotkey", d.get("keys", []), state)

    @app.route("/chain", methods=["POST"])
    @require_auth
    def route_chain():
        d = _json_body()
        actions = d.get("actions", [])
        results = []
        for a in actions:
            r = _execute_action_wrapper(a, state)
            payload, status_code = _result_payload(r)
            if status_code >= 400 and isinstance(payload, dict):
                payload = {**payload, "status_code": status_code}
            results.append(payload)
        return jsonify({"status": "ok", "count": len(results), "results": results})

    @app.route("/act", methods=["POST"])
    @require_auth
    def route_act():
        d = _json_body()
        action = d.get("action", {})
        if not action:
            return _missing_field("action")
        result = _execute_action_wrapper(action, state)
        return _result_response(result)

    @app.route("/cursor/pos", methods=["GET"])
    @require_auth
    def route_cursor():
        try:
            from ctypes import wintypes
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return jsonify({"x": int(pt.x), "y": int(pt.y)})
        except Exception:
            try:
                x, y = pyautogui.position()
                return jsonify({"x": int(x), "y": int(y)})
            except Exception:
                return jsonify({"x": 0, "y": 0})

    @app.route("/copilot/mode", methods=["GET"])
    @require_auth
    def route_copilot_mode():
        try:
            from cua_bridge import cua_available
            cua_ok = cua_available()
        except Exception:
            cua_ok = False
        return jsonify({"mode": "background", "sendinput": True, "cua_available": cua_ok})

    @app.route("/input/send", methods=["POST"])
    @require_auth
    def route_input_send():
        d = _json_body()
        _ok, _err = _preflight_guard(d)
        if not _ok:
            return _err
        keys = d.get("keys", "")
        action = "hotkey" if isinstance(keys, list) else "type"
        return _key_action(action, keys, state)

    @app.route("/input/preflight", methods=["GET"])
    @require_auth
    def route_input_preflight():
        """Describe the opt-in input preflight guard."""
        return jsonify({
            "status": "ok",
            "feature": "input_preflight_guard",
            "opt_in": True,
            "usage": "include a 'target' object in /mouse/* or /key/* requests to verify "
                     "foreground window (hwnd/pid/title/process) and coordinate bounds "
                     "before injection; on mismatch returns 409.",
            "target_fields": ["hwnd", "pid", "title", "process"],
        })

    @app.route("/emergency/stop", methods=["POST"])
    @require_auth
    def route_emergency_stop():
        state.emergency_stop = True
        _log("[EMERGENCY] STOP")
        return jsonify({"status": "emergency_stop", "emergency": True})

    @app.route("/emergency/resume", methods=["POST"])
    @require_auth
    def route_emergency_resume():
        state.emergency_stop = False
        _log("[EMERGENCY] RESUME")
        return jsonify({"status": "resumed", "emergency": False})

    @app.route("/emergency/status", methods=["GET"])
    @require_auth
    def route_emergency_status():
        return jsonify({"emergency": state.emergency_stop})

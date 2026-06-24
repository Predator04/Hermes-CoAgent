"""Mouse, keyboard, input, and action-chain routes."""
import threading, time, json, ctypes, hashlib
from flask import jsonify
from shared import _json_body, _log, _console, _missing_field, _result_response, COAGENT_DIR, SCREENSHOTS_DIR, _interactive_task_xml

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
        payload = response.json
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

def _background_sendinput(action, x, y, button="left"):
    """Send input without stealing focus using SendInput."""
    if action == "move":
        return _set_cursor_pos(x, y)
    if not hasattr(ctypes, 'windll'):
        return pyautogui.click(x, y, button=button)
    try:
        import ctypes.wintypes as w
        MOUSEEVENTF_LEFTDOWN = 0x0002; MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008; MOUSEEVENTF_RIGHTUP = 0x0010
        btn_down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        btn_up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
        extra = 0
        if action == "doubleclick":
            ctypes.windll.user32.mouse_event(btn_down, x, y, extra, 0)
            ctypes.windll.user32.mouse_event(btn_up, x, y, extra, 0)
        ctypes.windll.user32.mouse_event(btn_down, x, y, extra, 0)
        ctypes.windll.user32.mouse_event(btn_up, x, y, extra, 0)
    except Exception:
        pyautogui.click(x, y, button=button)

def _mouse_action(action, x, y, button="left", background=True, state=None):
    if state and state.emergency_stop:
        return jsonify({"error": "Emergency stop engaged"}), 503
    lock = state.input_lock if state else threading.Lock()
    with lock:
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
            getattr(pyautogui, action)(x, y) if action in ("click", "doubleClick", "rightClick") else pyautogui.click(x, y, button=button)
        if state: state.last_action_time = time.time()
    _log(f"Mouse {action} ({x},{y}) button={button} bg={background}")
    payload = {"status": "ok", "action": action, "x": x, "y": y}
    _record_action(action, {"x": x, "y": y, "button": button, "background": background}, payload)
    return jsonify(payload)

def _execute_action_wrapper(action, state=None):
    """Execute a stored action dict."""
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
        return jsonify({"error": "Emergency stop engaged"}), 503
    try:
        if action == "type":
            pyautogui.typewrite(str(data), interval=0.02)
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
        return jsonify({"error": str(e)}), 500

def _scroll_action(clicks, state=None):
    if state and state.emergency_stop:
        return jsonify({"error": "Emergency stop engaged"}), 503
    try:
        amount = int(clicks)
        pyautogui.scroll(amount)
        payload = {"status": "ok", "clicks": amount}
        _record_action("scroll", {"clicks": amount}, payload)
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def register_routes(app, state, require_auth):
    @app.route("/mouse/move", methods=["POST"])
    @require_auth
    def route_mouse_move():
        d = _json_body()
        return _mouse_action("move", int(d.get("x", 0)), int(d.get("y", 0)),
                             "left", d.get("background", True), state)

    @app.route("/mouse/click", methods=["POST"])
    @require_auth
    def route_mouse_click():
        d = _json_body()
        retry = _as_bool(d.get("retry"), True)
        if retry:
            return _mouse_click_with_retry(int(d.get("x", 0)), int(d.get("y", 0)),
                                           d.get("button", "left"), d.get("background", True), state)
        return _mouse_action("click", int(d.get("x", 0)), int(d.get("y", 0)),
                             d.get("button", "left"), d.get("background", True), state)

    @app.route("/mouse/click/smart", methods=["POST"])
    @require_auth
    def route_mouse_click_smart():
        d = _json_body()
        return _mouse_click_with_retry(int(d.get("x", 0)), int(d.get("y", 0)),
                                       d.get("button", "left"), d.get("background", True), state)

    @app.route("/mouse/dblclick", methods=["POST"])
    @require_auth
    def route_mouse_dblclick():
        d = _json_body()
        return _mouse_action("doubleclick", int(d.get("x", 0)), int(d.get("y", 0)),
                             d.get("button", "left"), d.get("background", True), state)

    @app.route("/mouse/rclick", methods=["POST"])
    @require_auth
    def route_mouse_rclick():
        d = _json_body()
        return _mouse_action("rightclick", int(d.get("x", 0)), int(d.get("y", 0)),
                             "right", d.get("background", True), state)

    @app.route("/mouse/drag", methods=["POST"])
    @require_auth
    def route_mouse_drag():
        d = _json_body()
        x1, y1, x2, y2 = int(d.get("x1", 0)), int(d.get("y1", 0)), int(d.get("x2", 0)), int(d.get("y2", 0))
        bg = d.get("background", True)
        if state and state.emergency_stop:
            return jsonify({"error": "Emergency stop engaged"}), 503
        try:
            if bg and hasattr(ctypes, 'windll'):
                ctypes.windll.user32.SetCursorPos(x1, y1)
                time.sleep(0.02)
                _background_sendinput("click", x1, y1, d.get("button", "left"))
                steps = 20
                for i in range(1, steps+1):
                    cx = x1 + (x2 - x1) * i // steps
                    cy = y1 + (y2 - y1) * i // steps
                    ctypes.windll.user32.SetCursorPos(cx, cy)
                    time.sleep(0.01)
                _background_sendinput("click", x2, y2, d.get("button", "left"))
            else:
                pyautogui.drag(x2 - x1, y2 - y1, button=d.get("button", "left"))
            _log(f"Drag ({x1},{y1})->({x2},{y2})")
            payload = {"status": "ok", "x1": x1, "y1": y1, "x2": x2, "y2": y2}
            _record_action("drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "button": d.get("button", "left"), "background": bg}, payload)
            return jsonify(payload)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/mouse/scroll", methods=["POST"])
    @require_auth
    def route_mouse_scroll():
        d = _json_body()
        return _scroll_action(d.get("clicks", -3), state)

    @app.route("/key/type", methods=["POST"])
    @require_auth
    def route_key_type():
        d = _json_body()
        return _key_action("type", d.get("text", ""), state)

    @app.route("/key/press", methods=["POST"])
    @require_auth
    def route_key_press():
        d = _json_body()
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
            x, y = pyautogui.position()
            return jsonify({"x": x, "y": y})
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
        return _key_action("type", d.get("keys", ""), state)

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
    def route_emergency_status():
        return jsonify({"emergency": state.emergency_stop})

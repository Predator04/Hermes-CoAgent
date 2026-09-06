"""Virtual gamepad / XInput injection (issue #1245).

Present a virtual Xbox 360 controller so agents can drive games, emulators,
and controller-based apps that ignore synthetic keyboard/mouse. Builds on the
optional `vgamepad` package backed by the ViGEmBus driver.

Endpoints:
    POST /gamepad/connect    - create a virtual Xbox 360 controller
    POST /gamepad/button     - press / release / tap a button
    POST /gamepad/stick      - set analog stick axes and trigger pressure
    POST /gamepad/reset      - release all inputs on a pad
    POST /gamepad/disconnect - remove a virtual controller
    GET  /gamepad/status     - list connected pads and their tracked state

All state is pure numeric (sticks/triggers clamped to [-1,1] / [0,1], buttons
name-mapped) so there is no injection surface. When `vgamepad` or the
ViGEmBus driver is absent the endpoints return HTTP 501 with an actionable
hint, mirroring the other optional-dependency modules.
"""

import threading

from flask import jsonify, request

from shared import _json_body, _log, _missing_field

try:
    import vgamepad as vg
    VG_AVAILABLE = True
except ImportError:
    vg = None
    VG_AVAILABLE = False

_MAX_PADS = 4
_LOCK = threading.Lock()
_pads = {}        # pad_id -> vg.VX360Gamepad
_pad_state = {}   # pad_id -> tracked input state


# Canonical friendly name -> XUSB_BUTTON enum attribute
_BUTTON_ENUM = {
    "a": "XUSB_GAMEPAD_A",
    "b": "XUSB_GAMEPAD_B",
    "x": "XUSB_GAMEPAD_X",
    "y": "XUSB_GAMEPAD_Y",
    "dpad_up": "XUSB_GAMEPAD_DPAD_UP",
    "dpad_down": "XUSB_GAMEPAD_DPAD_DOWN",
    "dpad_left": "XUSB_GAMEPAD_DPAD_LEFT",
    "dpad_right": "XUSB_GAMEPAD_DPAD_RIGHT",
    "left_shoulder": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "right_shoulder": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "left_bumper": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "right_bumper": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "start": "XUSB_GAMEPAD_START",
    "menu": "XUSB_GAMEPAD_START",
    "back": "XUSB_GAMEPAD_BACK",
    "view": "XUSB_GAMEPAD_BACK",
    "left_thumb": "XUSB_GAMEPAD_LEFT_THUMB",
    "right_thumb": "XUSB_GAMEPAD_RIGHT_THUMB",
    "guide": "XUSB_GAMEPAD_GUIDE",
}

# Triggers-as-buttons are mapped to the analog trigger axis.
_TRIGGER_BUTTONS = {"left_trigger": "lt", "right_trigger": "rt"}

_ACTIONS = {"press", "release", "tap"}


def _unavailable(detail=None):
    if not VG_AVAILABLE:
        payload = {
            "error": "vgamepad not installed (optional dependency)",
            "hint": "pip install vgamepad",
        }
    else:
        payload = {
            "error": "ViGEmBus driver not installed",
            "hint": "Install ViGEmBus from https://github.com/nefarius/ViGEmBus/releases",
        }
    if detail:
        payload["detail"] = str(detail)[:300]
    return jsonify(payload), 501


def _get_pad(pad_id):
    if pad_id not in _pads:
        return None
    return _pads[pad_id]


def _resolve_pad(payload):
    pad_id = payload.get("pad_id")
    if pad_id is None:
        with _LOCK:
            ids = list(_pads.keys())
        if not ids:
            return None
        pad_id = ids[0]
    if not isinstance(pad_id, int):
        return None
    return pad_id


def _new_state(pad_id):
    return {
        "pad_id": pad_id,
        "buttons": {},
        "left_stick": [0.0, 0.0],
        "right_stick": [0.0, 0.0],
        "left_trigger": 0.0,
        "right_trigger": 0.0,
    }


def _clamp(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, value))


def register_routes(app, state=None, require_auth=None):
    @app.route("/gamepad/connect", methods=["POST"])
    def gamepad_connect():
        if not VG_AVAILABLE:
            return _unavailable()
        payload = _json_body()
        with _LOCK:
            if len(_pads) >= _MAX_PADS:
                return jsonify({"error": f"Maximum of {_MAX_PADS} virtual pads reached"}), 429
            requested = payload.get("pad_id")
            if requested is not None and (not isinstance(requested, int) or requested in _pads):
                return jsonify({"error": "pad_id must be an unused integer"}), 400
            pad_id = requested if requested is not None else next(i for i in range(_MAX_PADS) if i not in _pads)
            try:
                pad = vg.VX360Gamepad()
            except Exception as exc:  # noqa: BLE001
                _log(f"gamepad: connect failed (driver?): {exc}")
                return _unavailable(str(exc))
            _pads[pad_id] = pad
            _pad_state[pad_id] = _new_state(pad_id)
        return jsonify({"ok": True, "pad_id": pad_id, "connected": len(_pads)})

    @app.route("/gamepad/button", methods=["POST"])
    def gamepad_button():
        if not VG_AVAILABLE:
            return _unavailable()
        payload = _json_body()
        name = (payload.get("button") or "").lower().strip()
        if not name:
            return _missing_field("button")
        action = (payload.get("action") or "tap").lower().strip()
        if action not in _ACTIONS:
            return jsonify({"error": f"action must be one of {sorted(_ACTIONS)}"}), 400
        pad_id = _resolve_pad(payload)
        if pad_id is None:
            return jsonify({"error": "No connected gamepad"}), 404
        pad = _get_pad(pad_id)
        if pad is None:
            return jsonify({"error": f"No gamepad with pad_id {pad_id}"}), 404

        with _LOCK:
            state = _pad_state[pad_id]
            if name in _TRIGGER_BUTTONS:
                axis = _TRIGGER_BUTTONS[name]
                press_val, release_val = 1.0, 0.0
                try:
                    if action == "press":
                        _set_trigger(pad, state, axis, press_val)
                    elif action == "release":
                        _set_trigger(pad, state, axis, release_val)
                    else:  # tap
                        _set_trigger(pad, state, axis, press_val)
                        pad.update()
                        _set_trigger(pad, state, axis, release_val)
                except Exception as exc:  # noqa: BLE001
                    return _unavailable(str(exc))
                pad.update()
                return jsonify({"ok": True, "pad_id": pad_id, "button": name, "action": action})

            enum_name = _BUTTON_ENUM.get(name)
            if enum_name is None:
                return jsonify({
                    "error": f"Unknown button '{name}'",
                    "valid": sorted(set(_BUTTON_ENUM) | set(_TRIGGER_BUTTONS)),
                }), 400
            try:
                btn = getattr(vg.XUSB_BUTTON, enum_name)
                if action == "press":
                    pad.press_button(button=btn)
                    state["buttons"][name] = True
                elif action == "release":
                    pad.release_button(button=btn)
                    state["buttons"][name] = False
                else:  # tap
                    pad.press_button(button=btn)
                    state["buttons"][name] = True
                    pad.update()
                    pad.release_button(button=btn)
                    state["buttons"][name] = False
            except Exception as exc:  # noqa: BLE001
                return _unavailable(str(exc))
            pad.update()
        return jsonify({"ok": True, "pad_id": pad_id, "button": name, "action": action})

    @app.route("/gamepad/stick", methods=["POST"])
    def gamepad_stick():
        if not VG_AVAILABLE:
            return _unavailable()
        payload = _json_body()
        pad_id = _resolve_pad(payload)
        if pad_id is None:
            return jsonify({"error": "No connected gamepad"}), 404
        pad = _get_pad(pad_id)
        if pad is None:
            return jsonify({"error": f"No gamepad with pad_id {pad_id}"}), 404

        stick = (payload.get("stick") or "left").lower().strip()
        if stick not in ("left", "right"):
            return jsonify({"error": "stick must be 'left' or 'right'"}), 400

        x = _clamp(payload.get("x", 0.0), -1.0, 1.0)
        y = _clamp(payload.get("y", 0.0), -1.0, 1.0)
        if x is None or y is None:
            return jsonify({"error": "x and y must be numeric in [-1, 1]"}), 400

        lt = payload.get("left_trigger")
        rt = payload.get("right_trigger")
        lt_val = _clamp(lt, 0.0, 1.0) if lt is not None else None
        rt_val = _clamp(rt, 0.0, 1.0) if rt is not None else None
        if lt is not None and lt_val is None:
            return jsonify({"error": "left_trigger must be numeric in [0, 1]"}), 400
        if rt is not None and rt_val is None:
            return jsonify({"error": "right_trigger must be numeric in [0, 1]"}), 400

        with _LOCK:
            state = _pad_state[pad_id]
            try:
                if stick == "left":
                    pad.left_joystick_float(x_value_float=x, y_value_float=y)
                    state["left_stick"] = [x, y]
                else:
                    pad.right_joystick_float(x_value_float=x, y_value_float=y)
                    state["right_stick"] = [x, y]
                if lt_val is not None:
                    pad.left_trigger_float(value_float=lt_val)
                    state["left_trigger"] = lt_val
                if rt_val is not None:
                    pad.right_trigger_float(value_float=rt_val)
                    state["right_trigger"] = rt_val
            except Exception as exc:  # noqa: BLE001
                return _unavailable(str(exc))
            pad.update()
        return jsonify({"ok": True, "pad_id": pad_id, "stick": stick, "x": x, "y": y,
                        "left_trigger": lt_val, "right_trigger": rt_val})

    @app.route("/gamepad/reset", methods=["POST"])
    def gamepad_reset():
        if not VG_AVAILABLE:
            return _unavailable()
        payload = _json_body()
        pad_id = _resolve_pad(payload)
        if pad_id is None:
            return jsonify({"error": "No connected gamepad"}), 404
        pad = _get_pad(pad_id)
        if pad is None:
            return jsonify({"error": f"No gamepad with pad_id {pad_id}"}), 404
        with _LOCK:
            try:
                pad.reset()
            except Exception as exc:  # noqa: BLE001
                return _unavailable(str(exc))
            pad.update()
            _pad_state[pad_id] = _new_state(pad_id)
        return jsonify({"ok": True, "pad_id": pad_id})

    @app.route("/gamepad/disconnect", methods=["POST"])
    def gamepad_disconnect():
        payload = _json_body()
        pad_id = _resolve_pad(payload)
        if pad_id is None:
            return jsonify({"error": "No connected gamepad"}), 404
        with _LOCK:
            pad = _pads.pop(pad_id, None)
            _pad_state.pop(pad_id, None)
        if pad is None:
            return jsonify({"error": f"No gamepad with pad_id {pad_id}"}), 404
        try:
            del pad
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"ok": True, "disconnected": pad_id, "remaining": list(_pads.keys())})

    @app.route("/gamepad/status", methods=["GET"])
    def gamepad_status():
        with _LOCK:
            pads = [dict(_pad_state[i]) for i in sorted(_pads)]
        return jsonify({"connected": list(_pads.keys()), "pads": pads, "vgamepad_available": VG_AVAILABLE})

"""Compound / batch action execution routes.

Endpoint:
  POST /actions/compound - run an ordered sequence of primitive actions
                           server-side in a single HTTP round-trip.

Round-trip latency is the dominant cost in agentic desktop automation. This
endpoint lets a controlling agent submit a pre-planned action sequence
(click -> type -> wait -> screenshot -> assert) and get one consolidated
result back instead of one HTTP round-trip per primitive.

Request body:
  {
    "actions": [ { "type": ..., ... }, ... ],
    "stop_on_fail": true,      optional, default true
    "max_steps": 30,           optional, default 30
    "max_duration_ms": 60000,  optional, default 60000
  }

Action types:
  {"type":"move","x":int,"y":int}
  {"type":"click","x":int,"y":int,"button":"left|right|middle","clicks":int}
  {"type":"type","text":str,"interval":float}
  {"type":"key","keys":"enter"|"tab"|"ctrl+l"|"alt+f4"|...}
  {"type":"scroll","amount":int}   (negative scrolls down)
  {"type":"wait","ms":int}
  {"type":"screenshot","label":str}
  {"type":"assert","window_title_contains":str}

Response:
  { "ok": bool, "results": [...], "failed_at": int|null,
    "final_screenshot": base64jpeg|null, "step_count": int, "elapsed_ms": float }

Windows-only imports are wrapped in try/except so the Linux syntax-check CI
stays green; the endpoint returns HTTP 501 when the backend is unavailable.
"""

import base64
import io
import time

from flask import jsonify

from shared import _json_body, _log, _missing_field

try:
    import ctypes
    from ctypes import wintypes
    _HAS_CTYPES = hasattr(ctypes, "windll")
except Exception:  # pragma: no cover - Linux import guard
    ctypes = None
    wintypes = None
    _HAS_CTYPES = False


# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_MIDDLEDOWN = 0x0020
_MOUSEEVENTF_MIDDLEUP = 0x0040
_MOUSEEVENTF_WHEEL = 0x0800

_WHEEL_DELTA = 120

_MODIFIER_VKS = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}

_VK_MAP = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "space": 0x20, " ": 0x20,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "capslock": 0x14, "printscreen": 0x2C,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
}
for _i in range(1, 13):
    _VK_MAP[f"f{_i}"] = 0x6F + _i


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (input backend unavailable)"}
    if detail:
        payload["detail"] = detail
    return jsonify(payload), 501


def _backend_available():
    return bool(_HAS_CTYPES)


# ---------------------------------------------------------------------------
# Low-level input helpers
# ---------------------------------------------------------------------------
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _send_input(inputs):
    user32 = ctypes.windll.user32
    n = len(inputs)
    arr = (_INPUT * n)(*inputs)
    return user32.SendInput(n, arr, ctypes.sizeof(_INPUT))


def _key_event(vk, flags):
    inp = _INPUT(type=_INPUT_KEYBOARD,
                 union=_INPUTUNION(ki=_KEYBDINPUT(vk, 0, flags, 0, None)))
    _send_input([inp])


def _tap_vk(vk):
    _key_event(vk, 0)
    _key_event(vk, _KEYEVENTF_KEYUP)


def _type_unicode(text, interval=0.0):
    for ch in text:
        code = ord(ch)
        inp_dn = _INPUT(type=_INPUT_KEYBOARD,
                        union=_INPUTUNION(ki=_KEYBDINPUT(0, code, _KEYEVENTF_UNICODE, 0, None)))
        inp_up = _INPUT(type=_INPUT_KEYBOARD,
                        union=_INPUTUNION(ki=_KEYBDINPUT(0, code, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, None)))
        _send_input([inp_dn, inp_up])
        if interval > 0:
            time.sleep(interval)


def _press_keys(keys):
    """Press a key or combo like 'ctrl+l'. Raises ValueError on unknown key."""
    parts = [p.strip().lower() for p in str(keys).split("+") if p.strip()]
    if not parts:
        raise ValueError("empty keys")
    modifiers = []
    while parts and parts[0] in _MODIFIER_VKS:
        modifiers.append(_MODIFIER_VKS[parts.pop(0)])
    key = parts.pop(0) if parts else ""
    if not key:
        raise ValueError("no key after modifiers")
    vk = _VK_MAP.get(key)
    if vk is None and len(key) == 1:
        vk = ord(key.upper())
    if vk is None:
        raise ValueError(f"unknown key: {key}")
    for m in modifiers:
        _key_event(m, 0)
    _tap_vk(vk)
    for m in reversed(modifiers):
        _key_event(m, _KEYEVENTF_KEYUP)


def _move(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def _mouse_flags(button, is_up):
    if button == "right":
        return _MOUSEEVENTF_RIGHTUP if is_up else _MOUSEEVENTF_RIGHTDOWN
    if button == "middle":
        return _MOUSEEVENTF_MIDDLEUP if is_up else _MOUSEEVENTF_MIDDLEDOWN
    return _MOUSEEVENTF_LEFTUP if is_up else _MOUSEEVENTF_LEFTDOWN


def _click(x, y, button="left", clicks=1):
    user32 = ctypes.windll.user32
    for _ in range(max(1, int(clicks))):
        _move(x, y)
        time.sleep(0.02)
        user32.mouse_event(_mouse_flags(button, False), 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(_mouse_flags(button, True), 0, 0, 0, 0)
        time.sleep(0.02)


def _scroll(amount):
    user32 = ctypes.windll.user32
    user32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, int(amount) * _WHEEL_DELTA, 0)


def _foreground_title():
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _screenshot_b64():
    """Capture the screen as a JPEG base64 string (via the canonical chain)."""
    try:
        from routes_ocr import _screen_img
        img = _screen_img(force=True)
        if img is None:
            return None
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=50)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        _log(f"compound: screenshot failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Action executor
# ---------------------------------------------------------------------------
def _execute_action(act, state):
    """Run one action. Returns (ok, detail). Raises on hard input failure."""
    atype = (act.get("type") or "").lower()
    if atype == "move":
        _move(act.get("x", 0), act.get("y", 0))
        return True, f"moved to {act.get('x')},{act.get('y')}"
    if atype == "click":
        _click(act.get("x", 0), act.get("y", 0),
               button=act.get("button") or "left",
               clicks=act.get("clicks", 1))
        return True, f"clicked {act.get('x')},{act.get('y')}"
    if atype == "type":
        text = act.get("text", "")
        interval = float(act.get("interval", 0.0) or 0.0)
        _type_unicode(str(text), interval=interval)
        return True, f"typed {len(str(text))} chars"
    if atype == "key":
        _press_keys(act.get("keys", ""))
        return True, f"pressed {act.get('keys')}"
    if atype == "scroll":
        _scroll(act.get("amount", 1))
        return True, f"scrolled {act.get('amount')}"
    if atype == "wait":
        ms = max(0, int(act.get("ms", 0) or 0))
        time.sleep(ms / 1000.0)
        return True, f"waited {ms}ms"
    if atype == "screenshot":
        b64 = _screenshot_b64()
        if b64 is None:
            return False, "screenshot failed"
        return True, b64
    if atype == "assert":
        needle = act.get("window_title_contains")
        if needle is None:
            return False, "assert requires 'window_title_contains'"
        title = _foreground_title()
        ok = str(needle).lower() in title.lower()
        return ok, f"window title {'contains' if ok else 'missing'} '{needle}'"
    return False, f"unknown action type: {atype}"


def register_routes(app, state, require_auth):

    @app.route("/actions/compound", methods=["POST"])
    @require_auth
    def route_actions_compound():
        if not _backend_available():
            return _windows_only("ctypes windll unavailable")

        body = _json_body()
        if not isinstance(body, dict):
            body = {}
        actions = body.get("actions")
        if not isinstance(actions, list) or not actions:
            return _missing_field("actions")

        stop_on_fail = bool(body.get("stop_on_fail", True))
        try:
            max_steps = min(100, max(1, int(body.get("max_steps", 30))))
        except (TypeError, ValueError):
            max_steps = 30
        try:
            max_duration_ms = min(300000, max(1, int(body.get("max_duration_ms", 60000))))
        except (TypeError, ValueError):
            max_duration_ms = 60000

        results = []
        final_screenshot = None
        failed_at = None
        ok = True

        start = time.monotonic()
        for idx, act in enumerate(actions[:max_steps]):
            if getattr(state, "emergency_stop", False):
                results.append({"index": idx, "type": act.get("type"), "ok": False,
                                "detail": "emergency stop", "elapsed_ms": 0})
                failed_at = idx
                ok = False
                break

            step_start = time.monotonic()
            try:
                step_ok, detail = _execute_action(act, state)
            except Exception as exc:  # noqa: BLE001
                step_ok, detail = False, f"{type(exc).__name__}: {exc}"

            elapsed = round((time.monotonic() - step_start) * 1000.0, 2)
            result = {"index": idx, "type": act.get("type"), "ok": step_ok,
                      "detail": detail, "elapsed_ms": elapsed}
            if act.get("type") == "screenshot":
                if step_ok:
                    result["screenshot"] = detail
                    result["detail"] = "screenshot captured"
            results.append(result)

            if not step_ok:
                failed_at = idx
                ok = False
                if stop_on_fail:
                    break

            if (time.monotonic() - start) * 1000.0 >= max_duration_ms:
                results.append({"index": idx + 1, "type": "_", "ok": False,
                                "detail": "max_duration_ms exceeded", "elapsed_ms": 0})
                ok = False
                break

        # Capture a final screenshot showing the state after the last executed step.
        final_screenshot = _screenshot_b64()

        total_ms = round((time.monotonic() - start) * 1000.0, 2)
        _log(f"compound: {len(results)} steps ok={ok} failed_at={failed_at}")
        return jsonify({
            "ok": ok,
            "results": results,
            "failed_at": failed_at,
            "final_screenshot": final_screenshot,
            "step_count": len(results),
            "elapsed_ms": total_ms,
        })

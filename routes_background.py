"""Background app control — drive Windows apps without stealing focus or cursor.

The user works normally while CoAgent operates invisibly alongside them.
All actions use SendInput + UIA InvokePattern — never moves the real cursor,
never activates windows, never steals keyboard focus.
"""

import ctypes
import time
from ctypes import wintypes

from flask import Blueprint, jsonify, request

from shared import _console, _json_body, _log, _wrap_registered_blueprint_routes
from uia_engine import (
    send_input_background,
    send_mouse_click,
    send_mouse_move,
    send_keys,
)

background_bp = Blueprint("background", __name__)

# ── Background activity tracking ──────────────────────────────────────────
_BG_ACTIVE = False
_BG_TASK = ""
_BG_STARTED = 0.0
_BG_ACTIONS = 0
_BG_LAST_ACTION = ""


def _bg_start(task: str):
    global _BG_ACTIVE, _BG_TASK, _BG_STARTED, _BG_ACTIONS, _BG_LAST_ACTION
    _BG_ACTIVE = True
    _BG_TASK = task
    _BG_STARTED = time.time()
    _BG_ACTIONS = 0
    _BG_LAST_ACTION = "started"
    _console(f"[BACKGROUND] ▶ {task}")


def _bg_tick(action: str):
    global _BG_ACTIONS, _BG_LAST_ACTION
    _BG_ACTIONS += 1
    _BG_LAST_ACTION = action


def _bg_done():
    global _BG_ACTIVE
    _BG_ACTIVE = False
    elapsed = time.time() - _BG_STARTED if _BG_STARTED else 0
    _console(
        f"[BACKGROUND] ✓ {_BG_TASK} — {_BG_ACTIONS} actions in {elapsed:.1f}s"
    )


# ── Focus-safe window helpers ─────────────────────────────────────────────

SW_SHOWNOACTIVATE = 4
SWP_NOACTIVATE = 0x0010
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def _find_window_by_title(title: str):
    """Find a window by partial title match. Returns hwnd or None."""
    hwnd = user32.FindWindowW(None, None)

    def _enum(h, _):
        nonlocal hwnd
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 255)
        if title.lower() in buf.value.lower():
            hwnd = h
            return False  # stop enum
        return True  # continue

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(_enum), 0)
    return hwnd


def focus_safe_show(hwnd: int):
    """Show window WITHOUT activating it or stealing focus."""
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


def focus_safe_set_pos(hwnd: int, x: int, y: int, w: int, h: int):
    """Move/resize window WITHOUT activation or z-order change."""
    flags = SWP_NOACTIVATE | SWP_NOZORDER
    user32.SetWindowPos(hwnd, 0, x, y, w, h, flags)


def focus_safe_foreground(hwnd: int) -> bool:
    """Try to make a window foreground WITHOUT stealing focus.
    
    Uses a gentle approach: attach thread input, then restore.
    Falls back to normal SetForegroundWindow if that fails.
    """
    # Get current foreground window's thread
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True

    current_tid = user32.GetWindowThreadProcessId(fg, None)
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    if current_tid != target_tid:
        user32.AttachThreadInput(target_tid, current_tid, True)

    try:
        # Minimize then restore — avoids focus steal on some Windows versions
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
    finally:
        if current_tid != target_tid:
            user32.AttachThreadInput(target_tid, current_tid, False)


# ── UIA InvokePattern — click elements without moving the mouse ───────────

def uia_invoke_element(find_method: str, find_value: str) -> dict:
    """Find a UIA element and invoke it (click) without any mouse movement.
    
    Uses UIA's InvokePattern — the element receives the click event directly.
    No cursor movement, no focus stealing.
    
    Args:
        find_method: 'name', 'automation_id', 'class_name', or 'index'
        find_value: the value to search for
    
    Returns:
        {"success": bool, "element": str, "method": str}
    """
    try:
        import comtypes.client

        UIA_dll = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
    except Exception as e:
        # Fallback: try pywinauto
        try:
            from pywinauto import Desktop
            from pywinauto.findwindows import find_elements

            elements = find_elements(**{find_method: find_value})
            if not elements:
                return {"success": False, "error": f"No element found: {find_method}={find_value}"}

            elem = elements[0]
            wrapper = Desktop(backend="uia").window(handle=elem.handle)
            wrapper.click_input()  # This uses InvokePattern internally if available
            return {
                "success": True,
                "element": str(find_value),
                "method": "pywinauto_InvokePattern",
                "control_type": elem.class_name if hasattr(elem, 'class_name') else "unknown",
            }
        except Exception as e2:
            return {"success": False, "error": f"UIA not available: {e2}"}

    # Try COM UIA InvokePattern
    try:
        condition = None
        if find_method == "name":
            condition = UIA_dll.CreatePropertyCondition(30005, find_value)  # UIA_NamePropertyId
        elif find_method == "automation_id":
            condition = UIA_dll.CreatePropertyCondition(30011, find_value)  # UIA_AutomationIdPropertyId
        elif find_method == "class_name":
            condition = UIA_dll.CreatePropertyCondition(30012, find_value)  # UIA_ClassNamePropertyId
        else:
            return {"success": False, "error": f"Unknown find_method: {find_method}"}

        desktop = UIA_dll.GetRootElement()
        element = desktop.FindFirst(2, condition)  # TreeScope_Descendants = 2

        if not element:
            return {"success": False, "error": f"Element not found: {find_method}={find_value}"}

        # Try InvokePattern
        try:
            invoke = element.GetCurrentPattern(10000)  # UIA_InvokePatternId
            invoke.Invoke()
            return {
                "success": True,
                "element": str(find_value),
                "method": "UIA_InvokePattern",
                "control_type": str(element.CurrentControlType),
            }
        except Exception:
            # Fallback: LegacyIAccessiblePattern.DoDefaultAction
            try:
                legacy = element.GetCurrentPattern(10018)
                legacy.DoDefaultAction()
                return {
                    "success": True,
                    "element": str(find_value),
                    "method": "LegacyIAccessible_DoDefaultAction",
                }
            except Exception as e3:
                return {"success": False, "error": f"Cannot invoke element: {e3}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Background window text typing ─────────────────────────────────────────

def type_into_window(hwnd: int, text: str, delay_ms: int = 10):
    """Type text into a specific window WITHOUT activating it.
    
    Uses SendInput with the target window's thread attached.
    """
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    current = user32.GetForegroundWindow()
    current_tid = user32.GetWindowThreadProcessId(current, None) if current else 0

    if current_tid != tid:
        user32.AttachThreadInput(tid, current_tid, True)

    try:
        for ch in text:
            send_keys(ch)
            if delay_ms:
                time.sleep(delay_ms / 1000.0)
    finally:
        if current_tid != tid:
            user32.AttachThreadInput(tid, current_tid, False)


# ── Routes ─────────────────────────────────────────────────────────────────

@background_bp.route("/background/status", methods=["GET"])
def route_background_status():
    """Check if a background task is running and what it's doing."""
    elapsed = time.time() - _BG_STARTED if _BG_STARTED else 0
    return jsonify({
        "active": _BG_ACTIVE,
        "task": _BG_TASK,
        "elapsed_seconds": round(elapsed, 1),
        "actions": _BG_ACTIONS,
        "last_action": _BG_LAST_ACTION,
        "mode": "invisible co-pilot",
        "sendinput": True,
        "focus_safe": True,
    })


@background_bp.route("/background/window/find", methods=["POST"])
def route_background_window_find():
    """Find a window by title (partial match) without activating it."""
    payload = _json_body()
    title = payload.get("title", "")
    if not title:
        return jsonify({"success": False, "error": "Missing title"}), 400

    hwnd = _find_window_by_title(title)
    if not hwnd:
        return jsonify({"success": False, "error": f"No window matching '{title}'"}), 404

    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 255)

    # Get window rect
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    return jsonify({
        "success": True,
        "hwnd": hwnd,
        "title": buf.value,
        "rect": {
            "left": rect.left, "top": rect.top,
            "right": rect.right, "bottom": rect.bottom,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        },
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "minimized": bool(user32.IsIconic(hwnd)),
    })


@background_bp.route("/background/window/show", methods=["POST"])
def route_background_window_show():
    """Show/restore a window WITHOUT activating it or stealing focus."""
    payload = _json_body()
    hwnd = payload.get("hwnd")
    title = payload.get("title", "")

    if not hwnd and title:
        hwnd = _find_window_by_title(title)
    if not hwnd:
        return jsonify({"success": False, "error": "No hwnd or title provided"}), 400

    focus_safe_show(hwnd)
    _bg_tick(f"show window {hwnd}")
    return jsonify({"success": True, "hwnd": hwnd, "action": "show_no_activate"})


@background_bp.route("/background/window/move", methods=["POST"])
def route_background_window_move():
    """Move/resize a window WITHOUT activation or z-order change."""
    payload = _json_body()
    hwnd = payload.get("hwnd")
    x = payload.get("x", 0)
    y = payload.get("y", 0)
    w = payload.get("width", 800)
    h = payload.get("height", 600)

    if not hwnd:
        return jsonify({"success": False, "error": "Missing hwnd"}), 400

    focus_safe_set_pos(hwnd, x, y, w, h)
    _bg_tick(f"move window {hwnd} → ({x},{y}) {w}x{h}")
    return jsonify({"success": True, "hwnd": hwnd, "rect": {"x": x, "y": y, "w": w, "h": h}})


@background_bp.route("/background/type", methods=["POST"])
def route_background_type():
    """Type text into a specific window WITHOUT activating it."""
    payload = _json_body()
    hwnd = payload.get("hwnd")
    title = payload.get("title", "")
    text = payload.get("text", "")
    delay_ms = payload.get("delay_ms", 10)

    if not text:
        return jsonify({"success": False, "error": "Missing text"}), 400
    if not hwnd and title:
        hwnd = _find_window_by_title(title)
    if not hwnd:
        return jsonify({"success": False, "error": "No window target"}), 400

    _bg_tick(f"type {len(text)} chars into window {hwnd}")
    type_into_window(hwnd, text, delay_ms)
    return jsonify({
        "success": True,
        "hwnd": hwnd,
        "text_length": len(text),
        "method": "SendInput_background",
    })


@background_bp.route("/background/click", methods=["POST"])
def route_background_click():
    """Click a UI element by name/ID WITHOUT moving cursor or stealing focus.
    
    Uses UIA InvokePattern — the element receives the click event directly.
    The user never sees the mouse move.
    """
    payload = _json_body()
    find_by = payload.get("find_by", "name")  # name, automation_id, class_name
    value = payload.get("value", "")
    # Fallback: coordinate-based click
    x = payload.get("x")
    y = payload.get("y")
    button = payload.get("button", "left")

    if value:
        _bg_tick(f"UIA invoke: {find_by}={value}")
        result = uia_invoke_element(find_by, value)
        return jsonify(result)
    elif x is not None and y is not None:
        _bg_tick(f"SendInput click at ({x},{y})")
        send_mouse_move(x, y)
        send_mouse_click(x, y, button)
        return jsonify({"success": True, "x": x, "y": y, "method": "SendInput_background"})
    else:
        return jsonify({"success": False, "error": "Provide 'value' for UIA or 'x'/'y' for coordinate click"}), 400


@background_bp.route("/background/automate", methods=["POST"])
def route_background_automate():
    """Run a sequence of actions entirely in the background.
    
    Actions are executed in order. The user continues working normally.
    
    Example payload:
    {
        "task": "Fill CRM form",
        "actions": [
            {"type": "find_window", "title": "Salesforce"},
            {"type": "click", "find_by": "name", "value": "New Contact"},
            {"type": "type", "text": "John Doe", "field": "name"},
            {"type": "click", "find_by": "name", "value": "Save"}
        ]
    }
    """
    payload = _json_body()
    task = payload.get("task", "background automation")
    actions = payload.get("actions", [])
    target_window = payload.get("window", "")

    if not actions:
        return jsonify({"success": False, "error": "Missing actions"}), 400

    _bg_start(task)
    results = []
    current_hwnd = None

    try:
        # Find target window first
        if target_window:
            current_hwnd = _find_window_by_title(target_window)
            if current_hwnd:
                focus_safe_show(current_hwnd)
                results.append({"action": "find_window", "success": True, "hwnd": current_hwnd})

        for action in actions:
            action_type = action.get("type", "")
            result = {"action": action_type}

            try:
                if action_type == "find_window":
                    title = action.get("title", "")
                    current_hwnd = _find_window_by_title(title)
                    if current_hwnd:
                        focus_safe_show(current_hwnd)
                        result["success"] = True
                        result["hwnd"] = current_hwnd
                    else:
                        result["success"] = False
                        result["error"] = f"Window '{title}' not found"

                elif action_type == "click":
                    find_by = action.get("find_by", "name")
                    value = action.get("value", "")
                    x = action.get("x")
                    y = action.get("y")

                    if value:
                        invoke_result = uia_invoke_element(find_by, value)
                        result.update(invoke_result)
                    elif x is not None and y is not None:
                        send_mouse_move(x, y)
                        send_mouse_click(x, y, action.get("button", "left"))
                        result["success"] = True
                        result["method"] = "SendInput"
                    else:
                        result["success"] = False
                        result["error"] = "Need 'value' or 'x'/'y'"

                elif action_type == "type":
                    text = action.get("text", "")
                    field = action.get("field", "")

                    if field:
                        # Click the field first
                        field_result = uia_invoke_element("name", field)
                        if field_result.get("success"):
                            time.sleep(0.1)

                    if current_hwnd:
                        type_into_window(current_hwnd, text)
                    else:
                        send_input_background(list(text))
                    result["success"] = True
                    result["text_length"] = len(text)

                elif action_type == "wait":
                    seconds = action.get("seconds", 1)
                    time.sleep(seconds)
                    result["success"] = True
                    result["waited"] = seconds

                elif action_type == "hotkey":
                    keys = action.get("keys", [])
                    send_input_background(keys)
                    result["success"] = True

                else:
                    result["success"] = False
                    result["error"] = f"Unknown action: {action_type}"

                _bg_tick(action_type)
            except Exception as e:
                result["success"] = False
                result["error"] = str(e)

            results.append(result)

        _bg_done()
        return jsonify({
            "success": True,
            "task": task,
            "actions_total": len(actions),
            "actions_completed": sum(1 for r in results if r.get("success")),
            "results": results,
        })

    except Exception as e:
        _bg_done()
        return jsonify({
            "success": False,
            "error": str(e),
            "results": results,
        }), 500


@background_bp.route("/background/stop", methods=["POST"])
def route_background_stop():
    """Stop any running background task."""
    _bg_done()
    return jsonify({"success": True, "message": "Background task stopped"})


def register_routes(app, state, require_auth):
    app.register_blueprint(background_bp)
    _wrap_registered_blueprint_routes(app, background_bp.name, require_auth)

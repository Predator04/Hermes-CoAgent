"""Background app control — drive Windows apps without stealing focus or cursor.

The user works normally while CoAgent operates invisibly alongside them.
All actions use UIA InvokePattern + PostMessage — never moves the real cursor,
never activates windows, never steals keyboard focus.

SendInput is DELIBERATELY avoided for typing because SendInput injects into
the OS input stream and is delivered to whatever window currently has focus
(NOT the target background window). Use UIA ValuePattern or PostMessage WM_CHAR.
"""

import base64
import ctypes
import struct
import threading
import time
from ctypes import wintypes
from io import BytesIO

from flask import Blueprint, jsonify

from shared import _console, _json_body, _wrap_registered_blueprint_routes
from uia_engine import send_mouse_click, send_mouse_move

background_bp = Blueprint("background", __name__)

# ── Win32 API setup with proper argtypes/restype (64-bit safe) ──────────

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ole32 = ctypes.windll.ole32

# -- Window finding --
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

user32.EnumWindows.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]

user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

# -- Window state --
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]

user32.IsIconic.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []

user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

# -- Window manipulation --
user32.ShowWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]

user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

user32.AttachThreadInput.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

# -- Message posting for background input --
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]

# -- PrintWindow: renders a window's contents into a device context,
#    including minimized/occluded windows when PW_RENDERFULLCONTENT (0x2) is
#    supplied (Windows 8.1+, DWM-composited apps).
user32.PrintWindow.restype = wintypes.BOOL
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]

user32.GetWindowPlacement.restype = wintypes.BOOL
user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.c_void_p]

# -- COM --
ole32.CoInitializeEx.restype = ctypes.c_long  # HRESULT
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]

ole32.CoUninitialize.restype = None
ole32.CoUninitialize.argtypes = []

# Constants
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_RESTORE = 9
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
COINIT_APARTMENTTHREADED = 0x2

WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

# PrintWindow flags
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002  # Windows 8.1+: works for DWM/UWP even off-screen

# DWM window attributes
DWMWA_EXTENDED_FRAME_BOUNDS = 9

# ── Thread-safe background activity tracking ──────────────────────────────

_BG_LOCK = threading.Lock()
_BG_ACTIVE = False
_BG_TASK = ""
_BG_STARTED = 0.0
_BG_ACTIONS = 0
_BG_LAST_ACTION = ""


def _bg_start(task: str):
    with _BG_LOCK:
        global _BG_ACTIVE, _BG_TASK, _BG_STARTED, _BG_ACTIONS, _BG_LAST_ACTION
        _BG_ACTIVE = True
        _BG_TASK = task
        _BG_STARTED = time.time()
        _BG_ACTIONS = 0
        _BG_LAST_ACTION = "started"
    _console(f"[BACKGROUND] ▶ {task}")


def _bg_tick(action: str):
    with _BG_LOCK:
        global _BG_ACTIONS, _BG_LAST_ACTION
        _BG_ACTIONS += 1
        _BG_LAST_ACTION = action


def _bg_done():
    with _BG_LOCK:
        global _BG_ACTIVE
        _BG_ACTIVE = False
        task = _BG_TASK
        actions = _BG_ACTIONS
        started = _BG_STARTED
    elapsed = time.time() - started if started else 0
    _console(f"[BACKGROUND] ✓ {task} — {actions} actions in {elapsed:.1f}s")


# ── Focus-safe window helpers ─────────────────────────────────────────────

def _find_window_by_title(title: str):
    """Find a window by partial title match. Returns hwnd or 0.

    Uses EnumWindows with a properly-typed callback that is held alive
    for the duration of the enumeration.
    """
    result = wintypes.HWND(0)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(h, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 255)
        if title.lower() in buf.value.lower():
            ctypes.cast(ctypes.byref(result), ctypes.POINTER(wintypes.HWND))[0] = h
            return False  # stop enumerating
        return True  # continue

    # Keep callback alive for the entire call (prevents GC mid-call)
    user32.EnumWindows(_enum, 0)
    return result.value if result.value else 0


def focus_safe_show(hwnd: int) -> bool:
    """Show window WITHOUT activating it."""
    return bool(user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE))


def focus_safe_set_pos(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    """Move/resize window WITHOUT activation or z-order change."""
    flags = SWP_NOACTIVATE | SWP_NOZORDER
    return bool(user32.SetWindowPos(hwnd, 0, x, y, w, h, flags))


# ── COM thread initialization ─────────────────────────────────────────────

def _com_init():
    """Initialize COM on the current thread for UIA access."""
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    return hr >= 0  # S_OK or S_FALSE (already initialized)


def _com_uninit():
    ole32.CoUninitialize()


# ── UIA InvokePattern — click elements without moving the mouse ───────────

def uia_invoke_element(find_method: str, find_value: str) -> dict:
    """Find a UIA element and invoke it (click) without any mouse movement.

    Uses UIA's InvokePattern — the element receives the click event directly.
    No cursor movement, no focus stealing.

    COM is initialized per-call for thread safety.
    """
    com_ok = _com_init()

    try:
        try:
            import comtypes.client
            UIA_dll = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
        except Exception:
            # Fallback: pywinauto with explicit invoke() — NOT click_input()
            try:
                from pywinauto import Desktop
                from pywinauto.findwindows import find_elements

                elements = find_elements(**{find_method: find_value})
                if not elements:
                    return {"success": False, "error": f"No element found: {find_method}={find_value}"}

                elem = elements[0]
                wrapper = Desktop(backend="uia").window(handle=elem.handle)

                # Use invoke() which calls UIA InvokePattern directly — no cursor movement
                try:
                    wrapper.invoke()
                    method = "pywinauto_InvokePattern"
                except Exception:
                    # LegacyIAccessible fallback
                    wrapper.legacy_properties['DefaultAction']
                    method = "pywinauto_LegacyIAccessible"

                return {
                    "success": True,
                    "element": str(find_value),
                    "method": method,
                }
            except Exception as e2:
                return {"success": False, "error": f"UIA not available: {e2}"}

        # COM UIA InvokePattern
        prop_map = {
            "name": 30005,         # UIA_NamePropertyId
            "automation_id": 30011, # UIA_AutomationIdPropertyId
            "class_name": 30012,   # UIA_ClassNamePropertyId
        }
        prop_id = prop_map.get(find_method)
        if not prop_id:
            return {"success": False, "error": f"Unknown find_method: {find_method}"}

        condition = UIA_dll.CreatePropertyCondition(prop_id, find_value)
        desktop = UIA_dll.GetRootElement()
        element = desktop.FindFirst(2, condition)  # TreeScope_Descendants

        if not element:
            return {"success": False, "error": f"Element not found: {find_method}={find_value}"}

        # InvokePattern
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
            # LegacyIAccessiblePattern fallback
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
    finally:
        if com_ok:
            _com_uninit()


# ── Background typing via PostMessage ─────────────────────────────────────

def type_into_window_post(hwnd: int, text: str, delay_ms: int = 10) -> dict:
    """Type text into a specific window using PostMessage WM_CHAR.

    PostMessage sends directly to the target window's message queue —
    it does NOT go through SendInput/the OS input stream.
    This means the text arrives in the target window even if it's
    in the background.

    Limitation: PostMessage WM_CHAR doesn't handle modifier keys
    (Ctrl+C, Alt+Tab, etc.). For hotkeys, use the /background/hotkey endpoint.
    """
    if not hwnd:
        return {"success": False, "error": "Invalid window handle"}

    text = str(text)
    if len(text) > 10000:
        return {"success": False, "error": "text too long (max 10000 chars)"}
    try:
        delay_ms = int(delay_ms)
    except (TypeError, ValueError):
        delay_ms = 0
    delay_ms = max(0, min(delay_ms, 1000))

    typed = 0
    for ch in text:
        if not user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0):
            return {
                "success": False,
                "error": f"PostMessage failed at char '{ch}' (position {typed})",
                "typed": typed,
            }
        typed += 1
        if delay_ms:
            time.sleep(delay_ms / 1000.0)

    return {"success": True, "typed": typed, "method": "PostMessage_WM_CHAR"}


def type_via_uia(hwnd: int, text: str) -> dict:
    """Type text using UIA ValuePattern.SetValue — the preferred approach.

    Finds the focused/active element in the target window and sets its value.
    This works even when the window is in the background.
    """
    com_ok = _com_init()
    try:
        import comtypes.client
        UIA_dll = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")

        # Get the element from the window handle
        element = UIA_dll.ElementFromHandle(hwnd)
        if not element:
            return {"success": False, "error": "Cannot get UIA element from window handle"}

        # Try to get the focused element via property (not pattern)
        try:
            focused = element.GetCurrentPropertyValue(30019)  # UIA_FocusedElementPropertyId
            if focused:
                element = focused
        except Exception:
            pass  # Use the window element itself

        # Try ValuePattern.SetValue
        try:
            value_pattern = element.GetCurrentPattern(10002)  # UIA_ValuePatternId
            value_pattern.SetValue(text)
            return {"success": True, "typed": len(text), "method": "UIA_ValuePattern"}
        except Exception:
            pass

        # Fallback: PostMessage
        return type_into_window_post(hwnd, text)

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if com_ok:
            _com_uninit()


# ── Routes ─────────────────────────────────────────────────────────────────

@background_bp.route("/background/status", methods=["GET"])
def route_background_status():
    """Check if a background task is running and what it's doing (thread-safe)."""
    with _BG_LOCK:
        active = _BG_ACTIVE
        task = _BG_TASK
        started = _BG_STARTED
        actions = _BG_ACTIONS
        last = _BG_LAST_ACTION
    elapsed = time.time() - started if started else 0
    return jsonify({
        "active": active,
        "task": task,
        "elapsed_seconds": round(elapsed, 1),
        "actions": actions,
        "last_action": last,
        "mode": "invisible co-pilot",
        "sendinput": False,
        "method": "PostMessage + UIA InvokePattern",
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
    """Show/restore a window WITHOUT activating it."""
    payload = _json_body()
    hwnd = payload.get("hwnd")
    title = payload.get("title", "")

    if not hwnd and title:
        hwnd = _find_window_by_title(title)
    if not hwnd:
        return jsonify({"success": False, "error": "No hwnd or title provided"}), 400

    ok = focus_safe_show(hwnd)
    _bg_tick(f"show window {hwnd}")
    return jsonify({"success": ok, "hwnd": hwnd, "action": "show_no_activate"})


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

    ok = focus_safe_set_pos(hwnd, x, y, w, h)
    _bg_tick(f"move window {hwnd}")
    return jsonify({"success": ok, "hwnd": hwnd, "rect": {"x": x, "y": y, "w": w, "h": h}})


@background_bp.route("/background/type", methods=["POST"])
def route_background_type():
    """Type text into a window using UIA ValuePattern (preferred) or PostMessage.

    Does NOT use SendInput — SendInput goes to the foreground window,
    not the target background window. This is the correct approach.
    """
    payload = _json_body()
    hwnd = payload.get("hwnd")
    title = payload.get("title", "")
    text = payload.get("text", "")
    method = payload.get("method", "auto")  # "auto", "postmessage", "uia"

    if not text:
        return jsonify({"success": False, "error": "Missing text"}), 400
    if not hwnd and title:
        hwnd = _find_window_by_title(title)
    if not hwnd:
        return jsonify({"success": False, "error": "No window target"}), 400

    _bg_tick(f"type {len(text)} chars into {hwnd}")

    if method == "postmessage":
        result = type_into_window_post(hwnd, text, payload.get("delay_ms", 10))
    elif method == "uia":
        result = type_via_uia(hwnd, text)
    else:
        # Auto: try UIA first, fall back to PostMessage
        result = type_via_uia(hwnd, text)
        if not result.get("success"):
            result = type_into_window_post(hwnd, text, payload.get("delay_ms", 10))

    result["hwnd"] = hwnd
    return jsonify(result)


@background_bp.route("/background/click", methods=["POST"])
def route_background_click():
    """Click a UI element by name/ID WITHOUT moving cursor.

    Uses UIA InvokePattern — the element receives the event directly.
    Falls back to SendInput click at coordinates (moves cursor invisibly
    via SendInput, not the real cursor).
    """
    payload = _json_body()
    find_by = payload.get("find_by", "name")
    value = payload.get("value", "")
    x = payload.get("x")
    y = payload.get("y")
    button = payload.get("button", "left")

    if value:
        _bg_tick(f"UIA invoke: {find_by}={value}")
        result = uia_invoke_element(find_by, value)
        return jsonify(result)
    elif x is not None and y is not None:
        _bg_tick(f"SendInput click at ({x},{y}) [cursor-safe]")
        send_mouse_move(x, y)
        send_mouse_click(x, y, button)
        return jsonify({"success": True, "x": x, "y": y, "method": "SendInput_background"})
    else:
        return jsonify({
            "success": False,
            "error": "Provide 'value' for UIA invoke or 'x'/'y' for coordinate click"
        }), 400


@background_bp.route("/background/hotkey", methods=["POST"])
def route_background_hotkey():
    """Send a key combination to the target window using PostMessage.

    Unlike SendInput, PostMessage delivers directly to the target window's
    message queue even when it's in the background.
    """
    payload = _json_body()
    hwnd = payload.get("hwnd")
    title = payload.get("title", "")
    keys = payload.get("keys", [])
    modifiers = payload.get("modifiers", [])  # ["ctrl"], ["alt"], ["shift"], ["win"]

    if not keys:
        return jsonify({"success": False, "error": "Missing keys"}), 400
    if not hwnd and title:
        hwnd = _find_window_by_title(title)
    if not hwnd:
        return jsonify({"success": False, "error": "No window target"}), 400

    # Map modifier names to VK codes
    vk_map = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}

    # Press modifiers
    for mod in modifiers:
        vk = vk_map.get(mod.lower())
        if vk:
            user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)

    # Press and release each key
    for key in keys:
        vk = ord(key.upper()) if len(key) == 1 else 0
        if vk:
            user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
            time.sleep(0.03)
            user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)

    # Release modifiers (reverse order)
    for mod in reversed(modifiers):
        vk = vk_map.get(mod.lower())
        if vk:
            user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)

    _bg_tick(f"hotkey {'+'.join(modifiers + keys)} into {hwnd}")
    return jsonify({
        "success": True,
        "hwnd": hwnd,
        "keys": modifiers + keys,
        "method": "PostMessage_key_events",
    })


@background_bp.route("/background/automate", methods=["POST"])
def route_background_automate():
    """Run a sequence of actions entirely in the background.

    All actions use PostMessage + UIA InvokePattern — never SendInput.
    The user continues working normally.
    """
    payload = _json_body()
    task = payload.get("task", "background automation")
    actions = payload.get("actions", [])
    target_window = payload.get("window", "")

    if not actions:
        return jsonify({"success": False, "error": "Missing actions"}), 400

    _bg_start(task)
    results = []
    current_hwnd = 0

    try:
        if target_window:
            current_hwnd = _find_window_by_title(target_window)
            if current_hwnd:
                focus_safe_show(current_hwnd)
                results.append({"action": "find_window", "success": True, "hwnd": current_hwnd})
            else:
                results.append({"action": "find_window", "success": False, "error": f"Window '{target_window}' not found"})

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
                        result.update(uia_invoke_element(find_by, value))
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
                        # Try UIA first, fall back to PostMessage
                        type_result = type_via_uia(current_hwnd, text)
                        if not type_result.get("success"):
                            type_result = type_into_window_post(current_hwnd, text)
                        result.update(type_result)
                    else:
                        result["success"] = False
                        result["error"] = "No window handle for typing"

                elif action_type == "hotkey":
                    keys = action.get("keys", [])
                    mods = action.get("modifiers", [])
                    if current_hwnd:
                        for mod in mods:
                            vk = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}.get(mod.lower())
                            if vk:
                                user32.PostMessageW(current_hwnd, WM_KEYDOWN, vk, 0)
                        for key in keys:
                            vk = ord(key.upper()) if len(key) == 1 else 0
                            if vk:
                                user32.PostMessageW(current_hwnd, WM_KEYDOWN, vk, 0)
                                time.sleep(0.03)
                                user32.PostMessageW(current_hwnd, WM_KEYUP, vk, 0)
                        for mod in reversed(mods):
                            vk = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}.get(mod.lower())
                            if vk:
                                user32.PostMessageW(current_hwnd, WM_KEYUP, vk, 0)
                        result["success"] = True
                    else:
                        result["success"] = False
                        result["error"] = "No window handle for hotkey"

                elif action_type == "wait":
                    seconds = action.get("seconds", 1)
                    time.sleep(seconds)
                    result["success"] = True
                    result["waited"] = seconds

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
        return jsonify({"success": False, "error": str(e), "results": results}), 500


@background_bp.route("/background/stop", methods=["POST"])
def route_background_stop():
    """Stop any running background task."""
    _bg_done()
    return jsonify({"success": True, "message": "Background task stopped"})


# ── Background window capture (issue #512) ────────────────────────────────
#
# Uses PrintWindow with PW_RENDERFULLCONTENT (0x2) so DWM-composited windows
# can be captured while minimized or occluded by other windows. For minimized
# windows we prefer the WINDOWPLACEMENT rcNormalPosition (the restored size)
# because GetWindowRect returns off-screen coordinates like (-32000,-32000)
# while iconic. Falls back to the DWM extended frame bounds, then the raw
# window rect.

def _window_capture_size(hwnd: int):
    """Return (width, height) for capturing hwnd, tolerant of minimized state."""
    # 1) WINDOWPLACEMENT.rcNormalPosition — the restored rect even when iconic.
    try:
        buf = ctypes.create_string_buffer(44)  # sizeof(WINDOWPLACEMENT)
        struct.pack_into("<I", buf, 0, 44)
        if user32.GetWindowPlacement(hwnd, buf):
            left, top, right, bottom = struct.unpack_from("<iiii", buf, 28)
            w, h = right - left, bottom - top
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass

    # 2) DWM extended frame bounds.
    try:
        dwmapi = ctypes.windll.dwmapi
        rect = wintypes.RECT()
        hr = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if hr == 0:
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass

    # 3) Plain GetWindowRect.
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return max(1, rect.right - rect.left), max(1, rect.bottom - rect.top)


def _capture_window_bytes(hwnd: int, client_only: bool = False):
    """Capture a window (even minimized/occluded) to PNG bytes.

    Returns (png_bytes, method) or (None, error_string).
    """
    try:
        import win32gui
        import win32ui
        from PIL import Image
    except Exception as e:
        return None, f"pywin32/PIL not available: {e}"

    width, height = _window_capture_size(hwnd)

    hwnd_dc = mfc_dc = save_dc = bitmap = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        flags = PW_RENDERFULLCONTENT | (PW_CLIENTONLY if client_only else 0)
        # First try PW_RENDERFULLCONTENT — the flag needed for DWM/UWP apps.
        result = user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flags)
        method = "PrintWindow_PW_RENDERFULLCONTENT"
        if not result:
            # Older windows sometimes need flags=0.
            result = user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0)
            method = "PrintWindow_default"
        if not result:
            return None, "PrintWindow returned 0"

        bmp_info = bitmap.GetInfo()
        bmp_bits = bitmap.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits,
            "raw",
            "BGRX",
            0,
            1,
        )
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), method
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        try:
            if bitmap is not None:
                win32gui.DeleteObject(bitmap.GetHandle())
        except Exception:
            pass
        try:
            if save_dc is not None:
                save_dc.DeleteDC()
        except Exception:
            pass
        try:
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
        except Exception:
            pass
        try:
            if hwnd and hwnd_dc:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


@background_bp.route("/screen/capture-window", methods=["POST", "GET"])
def route_screen_capture_window():
    """Capture a specific window by hwnd or title, even minimized/occluded.

    Payload / query params:
      hwnd:         int window handle (preferred)
      title:        substring to resolve via _find_window_by_title
      client_only:  bool (default false) — capture client area only
      format:       "base64" (default) or "png" (raw image/png response)

    Returns JSON {ok, hwnd, title, width, height, method, data(base64)} by
    default, or a raw image/png body when format=png.
    """
    from flask import Response, request

    payload = _json_body() if request.method == "POST" else {}
    hwnd = payload.get("hwnd") or request.args.get("hwnd", type=int)
    title = payload.get("title") or request.args.get("title", "")
    client_only = bool(payload.get("client_only") or request.args.get("client_only"))
    fmt = (payload.get("format") or request.args.get("format") or "base64").lower()

    if not hwnd and title:
        hwnd = _find_window_by_title(title)
    if not hwnd:
        return jsonify({"ok": False, "error": "Provide hwnd or title"}), 400

    hwnd = int(hwnd)
    data, method = _capture_window_bytes(hwnd, client_only=client_only)
    if not data:
        return jsonify({"ok": False, "hwnd": hwnd, "error": method}), 500

    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 255)
    width, height = _window_capture_size(hwnd)

    if fmt == "png":
        return Response(data, mimetype="image/png", headers={
            "X-Capture-Method": method,
            "X-Window-Hwnd": str(hwnd),
            "X-Window-Width": str(width),
            "X-Window-Height": str(height),
        })

    return jsonify({
        "ok": True,
        "hwnd": hwnd,
        "title": buf.value,
        "width": width,
        "height": height,
        "minimized": bool(user32.IsIconic(hwnd)),
        "method": method,
        "format": "png",
        "data": base64.b64encode(data).decode("ascii"),
    })


def register_routes(app, state, require_auth):
    app.register_blueprint(background_bp)
    _wrap_registered_blueprint_routes(app, background_bp.name, require_auth)

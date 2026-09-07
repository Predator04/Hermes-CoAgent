"""File dialog automation routes.

Endpoints:
  POST /filedialog/choose   - drive the Win32 Open dialog to pick a file/folder
  POST /filedialog/save     - drive the Win32 Save As dialog to save to a path
  POST /filedialog/set-path - set a full path into the dialog filename field

The Win32 Open/Save file-picker is notoriously UIA-hostile (the filename box
and address bar often expose no usable automation ids, and the same dialog
renders differently across MFC / WinForms / Electron apps). This module tries
strategies in order of reliability:

  1. UI Automation (comtypes UIAutomationClient): locate the dialog window,
     find the filename Edit control, set its value via ValuePattern, then find
     the Open/Save Button and Invoke it.
  2. Keyboard — filename field: focus the "File name:" field (Alt+N), type the
     full path, press Enter.
  3. Keyboard — address bar: Ctrl+L, type the folder path, press Enter, then
     type the filename and press Enter.

All Windows-only imports are wrapped in try/except so the Linux syntax-check
CI stays green; endpoints return HTTP 501 when the backend is unavailable.
"""

import os
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

_VK_RETURN = 0x0D
_VK_CONTROL = 0x11
_VK_MENU = 0x12          # Alt
_VK_N = 0x4E
_VK_L = 0x4C

_DIALOG_TITLE_HINTS = ("open", "save as", "save", "select")


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (file dialog backend unavailable)"}
    if detail:
        payload["detail"] = detail
    return jsonify(payload), 501


def _backend_available():
    return bool(_HAS_CTYPES)


# ---------------------------------------------------------------------------
# Low-level keyboard input via SendInput
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


def _tap(vk):
    _key_event(vk, 0)
    _key_event(vk, _KEYEVENTF_KEYUP)


def _combo(mod_vk, key_vk):
    _key_event(mod_vk, 0)
    _key_event(key_vk, 0)
    _key_event(key_vk, _KEYEVENTF_KEYUP)
    _key_event(mod_vk, _KEYEVENTF_KEYUP)


def _type_unicode(text):
    """Type arbitrary text using KEYEVENTF_UNICODE (handles any character)."""
    for ch in text:
        code = ord(ch)
        # KEYEVENTF_UNICODE carries the code point in wScan, not wVk.
        inp_dn = _INPUT(type=_INPUT_KEYBOARD,
                        union=_INPUTUNION(ki=_KEYBDINPUT(0, code, _KEYEVENTF_UNICODE, 0, None)))
        inp_up = _INPUT(type=_INPUT_KEYBOARD,
                        union=_INPUTUNION(ki=_KEYBDINPUT(0, code, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, None)))
        _send_input([inp_dn, inp_up])


# ---------------------------------------------------------------------------
# Window discovery
# ---------------------------------------------------------------------------
def _enum_dialog_windows():
    """Return visible top-level windows whose title hints at a file dialog."""
    if not _HAS_CTYPES:
        return []
    user32 = ctypes.windll.user32
    results = []

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        low = title.lower()
        if any(h in low for h in _DIALOG_TITLE_HINTS):
            results.append((hwnd, title))
        return True

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return results


def _find_dialog():
    wins = _enum_dialog_windows()
    if not wins:
        return None, None
    # Most recent dialog-looking window.
    return wins[-1][0], wins[-1][1]


def _focus_window(hwnd):
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return True


# ---------------------------------------------------------------------------
# Strategy 1 — UI Automation (comtypes)
# ---------------------------------------------------------------------------
def _uia_get_engine():
    """Return an (iuia, UIA) pair, or (None, None) on failure."""
    import comtypes
    import comtypes.client

    try:
        comtypes.CoInitialize()
    except Exception:
        pass

    try:
        from comtypes.gen import UIAutomationClient as UIA
    except Exception:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA

    iuia = comtypes.CoCreateInstance(
        UIA.CUIAutomation._reg_clsid_,
        interface=UIA.IUIAutomation,
        clsctx=comtypes.CLSCTX_INPROC_SERVER,
    )
    return iuia, UIA


def _uia_set_value(hwnd, full_path):
    """Set the filename Edit control's value via ValuePattern. Returns bool."""
    try:
        iuia, UIA = _uia_get_engine()
        dialog_el = iuia.ElementFromHandle(hwnd)
        if not dialog_el:
            return False
        edit_cond = iuia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId,
                                                 UIA.UIA_EditControlId)
        edit = dialog_el.FindFirst(UIA.TreeScope_Descendants, edit_cond)
        if edit is None:
            return False
        try:
            vp = edit.GetCurrentPattern(UIA.UIA_ValuePatternId).QueryInterface(
                UIA.IUIAutomationValuePattern
            )
            vp.SetValue(full_path)
            return True
        except Exception:
            return False
    except Exception as exc:
        _log(f"filedialog: UIA set-value failed: {exc}")
        return False


def _uia_invoke_button(hwnd, button_name):
    """Locate and invoke the accept button by name. Returns bool."""
    try:
        iuia, UIA = _uia_get_engine()
        dialog_el = iuia.ElementFromHandle(hwnd)
        if not dialog_el:
            return False
        ctrl_cond = iuia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId,
                                                 UIA.UIA_ButtonControlId)
        name_cond = iuia.CreatePropertyCondition(UIA.UIA_NamePropertyId, button_name)
        btn_cond = iuia.CreateAndCondition(ctrl_cond, name_cond)
        button = dialog_el.FindFirst(UIA.TreeScope_Descendants, btn_cond)
        if button is None:
            return False
        inv = button.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(
            UIA.IUIAutomationInvokePattern
        )
        inv.Invoke()
        return True
    except Exception as exc:
        _log(f"filedialog: UIA invoke-button failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Strategies 2/3 — keyboard fallbacks
# ---------------------------------------------------------------------------
def _keyboard_filename(full_path, press_enter=True):
    """Alt+N (focus filename field), type full path, optional Enter."""
    _combo(_VK_MENU, _VK_N)
    time.sleep(0.2)
    _type_unicode(full_path)
    time.sleep(0.15)
    if press_enter:
        _tap(_VK_RETURN)
    return True


def _keyboard_address_bar(folder, filename):
    """Ctrl+L (address bar), type folder, Enter, then filename, Enter."""
    _combo(_VK_CONTROL, _VK_L)
    time.sleep(0.2)
    _type_unicode(folder)
    time.sleep(0.3)
    _tap(_VK_RETURN)
    time.sleep(0.4)
    if filename:
        _combo(_VK_MENU, _VK_N)
        time.sleep(0.2)
        _type_unicode(filename)
        time.sleep(0.15)
        _tap(_VK_RETURN)
    return True


# ---------------------------------------------------------------------------
# Shared request handling
# ---------------------------------------------------------------------------
def _resolve_path(body):
    """Return (folder, full_path) from the request body."""
    path = body.get("path")
    filename = body.get("filename")
    if not path or not isinstance(path, str):
        return None, None

    full_path = path
    folder = path
    if filename and isinstance(filename, str):
        if os.path.isabs(filename):
            full_path = filename
            folder = os.path.dirname(full_path) or path
        else:
            full_path = os.path.join(path.rstrip("\\/"), filename)
            folder = path
    return folder, full_path


def _run_dialog(body, action):
    """Common driver for choose/save/set-path. Returns a Flask response."""
    if not _backend_available():
        return _windows_only("ctypes windll unavailable")

    if not isinstance(body, dict):
        body = {}

    folder, full_path = _resolve_path(body)
    if full_path is None:
        return _missing_field("path")

    button = None
    if action == "choose":
        button = body.get("button") or "Open"
    elif action == "save":
        button = body.get("button") or "Save"

    hwnd, title = _find_dialog()
    if hwnd is None:
        return jsonify({"ok": False, "error": "no file dialog window found", "strategy": None}), 404

    _focus_window(hwnd)
    strategy = None

    if action == "set-path":
        # Fill the filename field only (no commit).
        if _uia_set_value(hwnd, full_path):
            strategy = "uia"
        else:
            try:
                _keyboard_filename(full_path, press_enter=False)
                strategy = "filename"
            except Exception as exc:
                return jsonify({"ok": False, "error": f"failed to set path: {exc}",
                                "dialog": title}), 500
    else:
        # choose / save: set value then accept.
        if _uia_set_value(hwnd, full_path) and _uia_invoke_button(hwnd, button):
            strategy = "uia"
        else:
            try:
                _keyboard_filename(full_path, press_enter=True)
                strategy = "filename"
            except Exception as exc:
                _log(f"filedialog: filename fallback failed: {exc}")
                try:
                    _keyboard_address_bar(folder, body.get("filename"))
                    strategy = "address_bar"
                except Exception as exc2:
                    return jsonify({"ok": False, "error": f"all strategies failed: {exc2}",
                                    "dialog": title}), 500

    return jsonify({
        "ok": True, "dialog": title, "strategy": strategy,
        "path": full_path, "action": action,
    })


def register_routes(app, state, require_auth):

    @app.route("/filedialog/choose", methods=["POST"])
    @require_auth
    def route_filedialog_choose():
        return _run_dialog(_json_body(), "choose")

    @app.route("/filedialog/save", methods=["POST"])
    @require_auth
    def route_filedialog_save():
        return _run_dialog(_json_body(), "save")

    @app.route("/filedialog/set-path", methods=["POST"])
    @require_auth
    def route_filedialog_set_path():
        return _run_dialog(_json_body(), "set-path")

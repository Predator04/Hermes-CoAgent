"""Native drag-and-drop routes.

Endpoint:
  POST /drag/drop  - perform a native Win32 drag-and-drop between two screen
                     points, optionally carrying a list of file paths so that
                     Explorer / browser upload zones receive them as if they
                     were dropped from File Explorer.

Input (JSON body):
  {
    "from": {"x": N, "y": N},          optional when "files" given
    "to":   {"x": N, "y": N},          required
    "button": "left",                  optional, default "left"
    "steps": 30,                       optional, path interpolation steps
    "duration_ms": 600,                optional, total path duration
    "files": ["C:\\path\\a.png", ...]  optional, uses CF_HDROP + Ctrl+V drop
  }

Behavior:
  * files present: put the paths on the clipboard as CF_HDROP, move cursor
                   to "to", left-click to focus the drop zone, then send
                   Ctrl+V. This is how modern browser upload zones and most
                   Explorer views accept "pasted" files identically to a
                   real drop.
  * no files:      standard Win32 mouse down -> interpolated move -> mouse
                   up drag from "from" to "to", mirroring the low-level
                   pattern used by routes_mouse.route_mouse_drag.

All Windows-only deps are imported inside try/except so the Linux
syntax-check CI stays green. All PowerShell / subprocess strings (none
here at the moment) would be ASCII-only.
"""

import os
import time

from flask import jsonify

from shared import _json_body, _log, _missing_field

try:
    import ctypes
    from ctypes import wintypes
    _HAS_CTYPES = hasattr(ctypes, "windll")
except Exception:
    ctypes = None
    wintypes = None
    _HAS_CTYPES = False


# Win32 mouse_event flags.
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010

# Win32 keybd_event flags / VK codes for Ctrl+V paste fallback.
_KEYEVENTF_KEYUP = 0x0002
_VK_CONTROL = 0x11
_VK_V = 0x56

# Clipboard formats.
_CF_HDROP = 15
_GMEM_MOVEABLE = 0x0002

# Set ctypes prototypes so 64-bit handles/pointers are not truncated to
# 32-bit. ctypes otherwise defaults function returns to c_int, which silently
# corrupts HGLOBAL handles and lock pointers on 64-bit Python.
if _HAS_CTYPES and wintypes is not None:
    _kernel32 = ctypes.windll.kernel32
    _user32 = ctypes.windll.user32
    try:
        _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        _kernel32.GlobalLock.restype = wintypes.LPVOID
        _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        _kernel32.GlobalUnlock.restype = wintypes.BOOL
        _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        _kernel32.GlobalFree.restype = wintypes.HGLOBAL
        _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        _user32.OpenClipboard.restype = wintypes.BOOL
        _user32.OpenClipboard.argtypes = [wintypes.HWND]
        _user32.EmptyClipboard.restype = wintypes.BOOL
        _user32.EmptyClipboard.argtypes = []
        _user32.SetClipboardData.restype = wintypes.HANDLE
        _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        _user32.CloseClipboard.restype = wintypes.BOOL
        _user32.CloseClipboard.argtypes = []
    except Exception:
        pass


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _coerce_xy(obj):
    if not isinstance(obj, dict):
        return None
    try:
        return int(obj.get("x", 0)), int(obj.get("y", 0))
    except (TypeError, ValueError):
        return None


def _set_files_on_clipboard(paths):
    """Place a list of absolute paths on the clipboard as CF_HDROP.

    Returns (ok, error_or_none). Mirrors the DROPFILES + double-NUL-terminated
    wide-char path list layout that File Explorer expects.
    """
    if not _HAS_CTYPES:
        return False, "ctypes not available"

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # DROPFILES struct: DWORD pFiles, POINT pt (2*LONG), BOOL fNC, BOOL fWide.
    class DROPFILES(ctypes.Structure):
        _fields_ = [
            ("pFiles", wintypes.DWORD),
            ("pt_x", wintypes.LONG),
            ("pt_y", wintypes.LONG),
            ("fNC", wintypes.BOOL),
            ("fWide", wintypes.BOOL),
        ]

    header_size = ctypes.sizeof(DROPFILES)
    # Build double-NUL-terminated wide string of the file list.
    joined = "\0".join(paths) + "\0\0"
    payload = joined.encode("utf-16-le")
    total = header_size + len(payload)

    h_mem = kernel32.GlobalAlloc(_GMEM_MOVEABLE, total)
    if not h_mem:
        return False, "GlobalAlloc failed"
    handed_off = False
    try:
        ptr = kernel32.GlobalLock(h_mem)
        if not ptr:
            kernel32.GlobalFree(h_mem)
            return False, "GlobalLock failed"
        try:
            df = DROPFILES.from_address(ptr)
            df.pFiles = header_size
            df.pt_x = 0
            df.pt_y = 0
            df.fNC = 0
            df.fWide = 1
            ctypes.memmove(ptr + header_size, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(h_mem)

        if not user32.OpenClipboard(0):
            kernel32.GlobalFree(h_mem)
            return False, "OpenClipboard failed"
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(_CF_HDROP, h_mem):
                # Ownership stays with us on failure; free explicitly.
                kernel32.GlobalFree(h_mem)
                return False, "SetClipboardData failed"
            # On success the OS owns the handle; never free it again.
            handed_off = True
        finally:
            user32.CloseClipboard()
    except Exception as exc:
        if not handed_off:
            try:
                kernel32.GlobalFree(h_mem)
            except Exception:
                pass
        return False, f"{type(exc).__name__}: {exc}"

    return True, None


def _send_paste():
    """Send Ctrl+V via keybd_event."""
    if not _HAS_CTYPES:
        return
    user32 = ctypes.windll.user32
    user32.keybd_event(_VK_CONTROL, 0, 0, 0)
    user32.keybd_event(_VK_V, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(_VK_V, 0, _KEYEVENTF_KEYUP, 0)
    user32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)


def _win32_drag(x1, y1, x2, y2, button, steps, duration_ms):
    """Perform a native mouse-down / interpolated-move / mouse-up drag."""
    user32 = ctypes.windll.user32
    btn_down = _MOUSEEVENTF_LEFTDOWN if button == "left" else _MOUSEEVENTF_RIGHTDOWN
    btn_up = _MOUSEEVENTF_LEFTUP if button == "left" else _MOUSEEVENTF_RIGHTUP

    steps = max(2, min(200, int(steps)))
    duration_ms = max(50, min(20000, int(duration_ms)))
    step_delay = (duration_ms / 1000.0) / steps

    dx = x2 - x1
    dy = y2 - y1

    user32.SetCursorPos(int(x1), int(y1))
    time.sleep(0.08)
    user32.mouse_event(btn_down, 0, 0, 0, 0)
    time.sleep(0.05)

    for i in range(1, steps + 1):
        t = i / steps
        # Cubic ease-in-out for a natural, human-ish path.
        t_e = t * t * (3.0 - 2.0 * t)
        cx = int(x1 + dx * t_e)
        cy = int(y1 + dy * t_e)
        user32.SetCursorPos(cx, cy)
        time.sleep(step_delay)

    user32.SetCursorPos(int(x2), int(y2))
    time.sleep(0.05)
    user32.mouse_event(btn_up, 0, 0, 0, 0)


def register_routes(app, state, require_auth):
    @app.route("/drag/drop", methods=["POST"])
    @require_auth
    def route_drag_drop():
        if os.name != "nt" or not _HAS_CTYPES:
            return _windows_only()

        if state and getattr(state, "emergency_stop", False):
            return jsonify({
                "ok": False,
                "error": "Emergency stop is engaged",
                "code": "EMERGENCY_STOP",
            }), 503

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        dst = _coerce_xy(body.get("to"))
        if dst is None:
            return _missing_field("to")

        button = str(body.get("button", "left")).lower()
        if button not in ("left", "right"):
            button = "left"

        steps = body.get("steps", 30)
        duration_ms = body.get("duration_ms", 600)

        files = body.get("files") or []
        if files and not isinstance(files, list):
            return jsonify({"error": "files must be a list of paths"}), 400

        lock = getattr(state, "input_lock", None)

        # File-drop path: use CF_HDROP + Ctrl+V. Explorer, most file dialogs,
        # and browser upload zones accept "pasted" files identically to a
        # real drag-drop from Explorer.
        if files:
            resolved = []
            missing = []
            for p in files:
                sp = str(p)
                if not os.path.isabs(sp):
                    sp = os.path.abspath(sp)
                if not os.path.exists(sp):
                    missing.append(sp)
                    continue
                resolved.append(sp)
            if missing:
                return jsonify({
                    "error": "one or more files not found",
                    "missing": missing,
                }), 400
            if not resolved:
                return jsonify({"error": "no valid files supplied"}), 400

            def _do_file_drop():
                ok, err = _set_files_on_clipboard(resolved)
                if not ok:
                    return False, err
                user32 = ctypes.windll.user32
                dx, dy = dst
                user32.SetCursorPos(int(dx), int(dy))
                time.sleep(0.08)
                # Click to focus the drop zone / upload target.
                user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                time.sleep(0.12)
                _send_paste()
                return True, None

            try:
                if lock is not None:
                    with lock:
                        ok, err = _do_file_drop()
                else:
                    ok, err = _do_file_drop()
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

            if not ok:
                return jsonify({"ok": False, "error": err or "file drop failed"}), 500

            if state:
                state.last_action_time = time.time()
            _log(
                f"drag/drop files n={len(resolved)} -> ({dst[0]},{dst[1]})"
            )
            return jsonify({
                "status": "ok",
                "mode": "files",
                "count": len(resolved),
                "files": resolved,
                "to": {"x": dst[0], "y": dst[1]},
            })

        # Pointer-only drag path: requires "from".
        src = _coerce_xy(body.get("from"))
        if src is None:
            return _missing_field("from")

        try:
            if lock is not None:
                with lock:
                    _win32_drag(src[0], src[1], dst[0], dst[1],
                                button, steps, duration_ms)
            else:
                _win32_drag(src[0], src[1], dst[0], dst[1],
                            button, steps, duration_ms)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        if state:
            state.last_action_time = time.time()

        _log(
            f"drag/drop pointer ({src[0]},{src[1]})->({dst[0]},{dst[1]}) "
            f"btn={button}"
        )
        return jsonify({
            "status": "ok",
            "mode": "pointer",
            "from": {"x": src[0], "y": src[1]},
            "to": {"x": dst[0], "y": dst[1]},
            "button": button,
        })

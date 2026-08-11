"""UIAccess Helper — Option C UAC automation (experimental).

This script must be compiled into an .exe with a UIAccess manifest and placed in
C:\\Program Files\\Hermes CoAgent\\ (or another trusted location). A UIAccess process
can interact with elevated windows and the secure desktop, so it can click the UAC
Yes/No buttons even when PromptOnSecureDesktop=1.

Build steps:
  pip install pyinstaller pywin32
  pyinstaller --onefile --manifest uiaccess_manifest.xml uiaccess_helper.py
  copy dist\\uiaccess_helper.exe "C:\\Program Files\\Hermes CoAgent\\uiaccess_helper.exe"

Usage (called by routes_uac.py in the future if integrated):
  uiaccess_helper.exe --click yes
  uiaccess_helper.exe --click no
  uiaccess_helper.exe --list         (list visible UAC-related windows)
"""

import argparse
import ctypes
import json
import sys
import time


YES_LABELS = ["Yes", "Allow", "是", "はい", "Ja", "Oui", "Sí", "Si", "Да"]
NO_LABELS  = ["No", "Cancel", "否", "いいえ", "Nein", "Non", "Отмена"]
UAC_TITLES = ["User Account Control"]


def _has_uiaccess():
    """Return True if this process was granted UIAccess privilege."""
    try:
        import win32security
        import win32api
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_QUERY,
        )
        info = win32security.GetTokenInformation(token, win32security.TokenUIAccess)
        return bool(info)
    except Exception:
        return False


def _find_uac_window():
    """Return (hwnd, title) of the first UAC window found, or (None, None)."""
    try:
        import win32gui
        found = [None]

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if any(t in title for t in UAC_TITLES):
                found[0] = (hwnd, title)
            return True

        win32gui.EnumWindows(_cb, None)
        return found[0] if found[0] else (None, None)
    except ImportError:
        print(json.dumps({"error": "pywin32 not installed"}))
        sys.exit(1)


def _click_button(hwnd, labels):
    """Find a child Button matching any label and click its center."""
    try:
        import win32gui
        import win32api
        import win32con

        result = [None]

        def _child_cb(child, _):
            if result[0]:
                return True
            cls = win32gui.GetClassName(child)
            if cls in ("Button", "CCPushButton"):
                text = win32gui.GetWindowText(child)
                if any(lbl.lower() in text.lower() for lbl in labels):
                    result[0] = child
            return True

        win32gui.EnumChildWindows(hwnd, _child_cb, None)

        if not result[0]:
            return False, "button not found"

        btn = result[0]
        rect = win32gui.GetWindowRect(btn)
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        win32api.SetCursorPos((cx, cy))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        return True, {"x": cx, "y": cy}
    except Exception as exc:
        return False, str(exc)


def cmd_list(_args):
    hwnd, title = _find_uac_window()
    if hwnd:
        print(json.dumps({"found": True, "hwnd": hwnd, "title": title}))
    else:
        print(json.dumps({"found": False}))


def cmd_click(args):
    button = (args.click or "yes").strip().lower()
    labels = YES_LABELS if button == "yes" else NO_LABELS

    has_ua = _has_uiaccess()
    deadline = time.time() + float(args.timeout or 5)

    while time.time() < deadline:
        hwnd, title = _find_uac_window()
        if hwnd:
            ok, detail = _click_button(hwnd, labels)
            print(json.dumps({
                "clicked": ok,
                "button": button,
                "hwnd": hwnd,
                "title": title,
                "detail": detail,
                "uiaccess": has_ua,
            }))
            sys.exit(0 if ok else 1)
        time.sleep(0.3)

    print(json.dumps({
        "clicked": False,
        "button": button,
        "reason": "UAC window not found within timeout",
        "uiaccess": has_ua,
    }))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="UIAccess UAC helper")
    parser.add_argument("--click", metavar="yes|no", help="Click Yes or No on UAC dialog")
    parser.add_argument("--list", action="store_true", help="List UAC windows")
    parser.add_argument("--timeout", type=float, default=5.0, help="Wait timeout (seconds)")
    args = parser.parse_args()

    if args.list:
        cmd_list(args)
    elif args.click:
        cmd_click(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

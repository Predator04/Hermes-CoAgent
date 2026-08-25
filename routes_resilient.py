"""Resilient UI automation: detect and dismiss unexpected popups/dialogs.

Endpoints:
  POST /resilient/scan     - enumerate top-level windows and classify each as
                             an error/confirm/alert dialog when its title/class
                             matches a known pattern.
  POST /resilient/dismiss  - close matching popup windows via a "safe" button
                             (OK/Yes/Close) or WM_CLOSE.
  POST /resilient/guard    - convenience helper: scan, then optionally dismiss
                             before (and/or after) another automation action.
                             The caller runs the action itself between calls;
                             this route just reports what was cleared.

Backends (tried in order):
  1. pywinauto (best button detection) if installed
  2. ctypes/user32 (always available on Windows, no third-party deps)

All subprocess/PowerShell strings are pure ASCII.
"""

import re
import time

from flask import jsonify

from shared import _json_body, _log


# ---------------------------------------------------------------------------
# Known dialog patterns
# ---------------------------------------------------------------------------

# Window title fragments (case-insensitive) that indicate a generic dialog.
_TITLE_PATTERNS = [
    "error", "warning", "confirm", "alert", "attention",
    "notice", "notification", "message", "problem", "failed",
    "unable to", "cannot", "sorry", "oops",
    "are you sure", "do you want", "unsaved",
    "update available", "sign in", "activate",
    "not responding", "has stopped working", "crash",
    "microsoft store", "windows security",
]

# Window class names that identify native Win32 dialogs.
_DIALOG_CLASSES = {
    "#32770",           # standard Win32 dialog
    "MessageBox",
    "TaskDialogWindow",
    "MsoCommandBarPopup",
    "NUIDialog",        # Office dialogs
}

# Button labels considered "safe" to click to dismiss a popup.
_SAFE_LABELS = [
    "ok", "okay", "close", "dismiss", "yes", "continue",
    "got it", "acknowledge", "accept", "later", "not now",
    "skip", "no thanks",
]

# Labels a caller may explicitly opt into to answer negatively.
_NEGATIVE_LABELS = ["no", "cancel", "deny", "reject", "abort"]

_BUTTON_CLASSES = ("Button", "CCPushButton", "TButton", "WindowsForms10.BUTTON")


def _configure_user32_scalars(user32):
    """Set argtypes/restype on user32 calls so 64-bit handles aren't truncated.

    Without explicit prototypes, ctypes coerces every integer argument to a
    32-bit ``c_int``. On 64-bit Windows, HWND (and WPARAM/LPARAM) are 64-bit
    values, so a handle whose high bit is set gets truncated (or raises
    OverflowError), causing clicks/close attempts to target the wrong window.
    """
    import ctypes
    from ctypes import wintypes
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ulong),
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# ctypes / user32 window enumeration
# ---------------------------------------------------------------------------

def _enum_top_windows_ctypes():
    """Return a list of (hwnd, title, class_name, pid) for visible top-level windows."""
    windows = []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        _configure_user32_scalars(user32)

        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.restype = wintypes.BOOL

        def callback(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    tbuf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, tbuf, length + 1)
                    title = tbuf.value
                cbuf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cbuf, 256)
                cls = cbuf.value
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                windows.append((int(hwnd), title, cls, int(pid.value)))
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_proc_type(callback), 0)
    except Exception as exc:
        _log(f"[resilient] EnumWindows failed: {exc}")
    return windows


def _classify(title, class_name, extra_patterns):
    """Return the matching category label or None."""
    tl = (title or "").lower()
    cl = (class_name or "").strip()
    if cl in _DIALOG_CLASSES:
        return "dialog_class"
    for p in _TITLE_PATTERNS:
        if p in tl:
            return f"title:{p}"
    for p in extra_patterns or ():
        if p and p.lower() in tl:
            return f"custom:{p.lower()}"
    return None


def _list_child_buttons_ctypes(hwnd):
    """Return list of (child_hwnd, class, text) for buttons under hwnd."""
    buttons = []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        _configure_user32_scalars(user32)

        enum_child_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumChildWindows.argtypes = [wintypes.HWND, enum_child_type, wintypes.LPARAM]
        user32.EnumChildWindows.restype = wintypes.BOOL

        def cb(child, _lparam):
            try:
                cbuf = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(child, cbuf, 128)
                cls = cbuf.value
                if not any(cls == b or cls.startswith(b) for b in _BUTTON_CLASSES):
                    return True
                length = user32.GetWindowTextLengthW(child)
                text = ""
                if length > 0:
                    tbuf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(child, tbuf, length + 1)
                    text = tbuf.value
                buttons.append((int(child), cls, text))
            except Exception:
                pass
            return True

        user32.EnumChildWindows(hwnd, enum_child_type(cb), 0)
    except Exception:
        pass
    return buttons


def _click_button_ctypes(button_hwnd):
    """Send BM_CLICK to a button. Returns True on success."""
    try:
        import ctypes
        BM_CLICK = 0x00F5
        SMTO_ABORTIFHUNG = 0x0002
        SMTO_NORMAL = 0x0000
        result = ctypes.c_ulong()
        user32 = ctypes.windll.user32
        _configure_user32_scalars(user32)
        ret = user32.SendMessageTimeoutW(
            button_hwnd, BM_CLICK, 0, 0,
            SMTO_ABORTIFHUNG | SMTO_NORMAL, 2000, ctypes.byref(result))
        return bool(ret)
    except Exception as exc:
        _log(f"[resilient] BM_CLICK failed: {exc}")
        return False


def _post_wm_close(hwnd):
    """Post WM_CLOSE to a window and report whether it actually closed.

    ``PostMessageW`` only returns whether the message was queued, not whether
    the window closed (the app may ignore it or show a "save changes" prompt).
    Poll ``IsWindow`` briefly so callers get an honest result instead of a
    false "clicked=True".
    """
    try:
        import ctypes
        WM_CLOSE = 0x0010
        user32 = ctypes.windll.user32
        _configure_user32_scalars(user32)
        if not user32.IsWindow(hwnd):
            return False
        if not user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
            return False
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if not user32.IsWindow(hwnd):
                return True
            time.sleep(0.05)
        return False
    except Exception as exc:
        _log(f"[resilient] WM_CLOSE failed: {exc}")
        return False


def _pick_safe_button(buttons, mode):
    """Return the first matching button hwnd for the given mode, or None."""
    labels = _NEGATIVE_LABELS if mode == "negative" else _SAFE_LABELS
    normalized = [(bh, cls, (text or "").strip()) for (bh, cls, text) in buttons]
    for want in labels:
        for bh, _cls, text in normalized:
            t = text.lower().replace("&", "")
            if t == want or t.startswith(want + " ") or t == want + "...":
                return bh, text
    # Strict fallback: only match when the whole label is the target word
    # (optionally followed by trailing punctuation/ellipsis). A word-boundary
    # "contains" match would wrongly confirm destructive labels such as
    # "Yes, delete everything" or "Continue and discard changes".
    for want in labels:
        for bh, _cls, text in normalized:
            t = text.lower().replace("&", "").strip().rstrip(".\u2026! \t")
            if t == want:
                return bh, text
    return None, None


# ---------------------------------------------------------------------------
# pywinauto backend (optional, richer detection)
# ---------------------------------------------------------------------------

def _dismiss_with_pywinauto(hwnd, mode):
    """Try pywinauto to click a safe/negative button on a specific hwnd.

    Returns dict {clicked, label, backend} or {clicked: False, reason}.
    """
    try:
        from pywinauto import Application
    except Exception:
        return {"clicked": False, "reason": "pywinauto not installed"}
    try:
        app = Application(backend="uia").connect(handle=hwnd)
        dlg = app.window(handle=hwnd)
        labels = _NEGATIVE_LABELS if mode == "negative" else _SAFE_LABELS
        for want in labels:
            try:
                btn = dlg.child_window(title_re=f"(?i)^&?{re.escape(want)}$", control_type="Button")
                if btn.exists(timeout=0.5):
                    # .click() uses the UIA Invoke pattern (no synthetic mouse
                    # movement). .click_input() moves the real cursor, racing the
                    # user and failing on a locked/RDP-disconnected session.
                    btn.click()
                    return {"clicked": True, "label": want, "backend": "pywinauto_uia"}
            except Exception:
                continue
        return {"clicked": False, "reason": "no matching button via pywinauto"}
    except Exception as exc:
        return {"clicked": False, "reason": f"pywinauto error: {exc}"}


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

def _scan(extra_patterns=None, include_all=False):
    """Return the list of top-level windows, annotated with a match category."""
    out = []
    for hwnd, title, cls, pid in _enum_top_windows_ctypes():
        cat = _classify(title, cls, extra_patterns)
        if cat is None and not include_all:
            continue
        out.append({
            "hwnd": hwnd,
            "title": title,
            "class": cls,
            "pid": pid,
            "match": cat,
        })
    return out


def _dismiss_hwnd(hwnd, mode="safe", prefer_pywinauto=True):
    """Dismiss a single popup. Returns a dict describing the action."""
    if prefer_pywinauto:
        r = _dismiss_with_pywinauto(hwnd, mode)
        if r.get("clicked"):
            return r
    buttons = _list_child_buttons_ctypes(hwnd)
    if buttons:
        bh, label = _pick_safe_button(buttons, mode)
        if bh:
            ok = _click_button_ctypes(bh)
            if ok:
                return {"clicked": True, "label": label, "backend": "ctypes_bm_click"}
    ok = _post_wm_close(hwnd)
    return {"clicked": ok, "label": None, "backend": "wm_close" if ok else "none"}


def guard_run(extra_patterns=None, mode="safe", dismiss=True,
              settle_ms=250, max_iterations=5):
    """Sweep the desktop for popups and (optionally) dismiss them.

    Public helper other routes can import and call before/after actions.
    Returns a dict {swept, dismissed, remaining, iterations}.
    """
    settle_ms = min(5000, max(0, int(settle_ms)))
    max_iterations = min(20, max(1, int(max_iterations)))
    swept = []
    dismissed = []
    completed = 0
    for i in range(max_iterations):
        popups = _scan(extra_patterns=extra_patterns)
        if not popups:
            return {
                "swept": swept, "dismissed": dismissed,
                "remaining": [], "iterations": i,
            }
        completed = i + 1
        swept.extend(popups)
        if not dismiss:
            return {
                "swept": swept, "dismissed": dismissed,
                "remaining": popups, "iterations": completed,
            }
        progressed = False
        for p in popups:
            result = _dismiss_hwnd(p["hwnd"], mode=mode)
            entry = {**p, **result}
            dismissed.append(entry)
            if result.get("clicked"):
                progressed = True
        if settle_ms:
            time.sleep(settle_ms / 1000.0)
        if not progressed:
            break
    remaining = _scan(extra_patterns=extra_patterns)
    return {
        "swept": swept, "dismissed": dismissed,
        "remaining": remaining, "iterations": completed,
    }


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/resilient/scan", methods=["POST"])
    @require_auth
    def route_resilient_scan():
        """Enumerate top-level windows matching popup/dialog patterns.

        Body (all optional):
          extra_patterns : list[str] - additional title substrings to match
          include_all    : bool      - return every visible top-level window,
                                       even those that did not match a pattern
        Returns {status, popups, count, backend}.
        """
        d = _json_body() or {}
        extra = d.get("extra_patterns") or []
        include_all = bool(d.get("include_all", False))
        popups = _scan(extra_patterns=extra, include_all=include_all)
        return jsonify({
            "status": "ok",
            "popups": popups,
            "count": len(popups),
            "backend": "ctypes_user32",
        })

    @app.route("/resilient/dismiss", methods=["POST"])
    @require_auth
    def route_resilient_dismiss():
        """Dismiss matching popup windows.

        Body (all optional):
          hwnd            : int       - target a single window; otherwise all
                                        matching popups are dismissed
          extra_patterns  : list[str] - extra title substrings to include
          mode            : "safe" (default) or "negative"
          prefer_pywinauto: bool      - default True; falls back to ctypes
        Returns {status, results, count}.
        """
        d = _json_body() or {}
        mode = (d.get("mode") or "safe").strip().lower()
        if mode not in ("safe", "negative"):
            return jsonify({"error": "mode must be 'safe' or 'negative'"}), 400
        prefer_pywinauto = bool(d.get("prefer_pywinauto", True))
        extra = d.get("extra_patterns") or []

        results = []
        hwnd = d.get("hwnd")
        if hwnd is not None:
            try:
                hwnd = int(hwnd)
            except (TypeError, ValueError):
                return jsonify({"error": "hwnd must be an integer"}), 400
            # Validate the target before acting: the client-supplied hwnd must still
            # reference a window that classifies as a dialog/popup (defense against
            # dismissing arbitrary windows by handle).
            target_valid = False
            for w_hwnd, w_title, w_cls, _pid in _enum_top_windows_ctypes():
                if w_hwnd == hwnd and _classify(w_title, w_cls, extra) is not None:
                    target_valid = True
                    break
            if not target_valid:
                return jsonify({
                    "error": "hwnd does not reference a recognized dialog",
                    "hwnd": hwnd,
                }), 400
            results.append({
                "hwnd": hwnd,
                **_dismiss_hwnd(hwnd, mode=mode, prefer_pywinauto=prefer_pywinauto),
            })
        else:
            for p in _scan(extra_patterns=extra):
                results.append({
                    **p,
                    **_dismiss_hwnd(p["hwnd"], mode=mode, prefer_pywinauto=prefer_pywinauto),
                })

        return jsonify({
            "status": "ok",
            "results": results,
            "count": len(results),
        })

    @app.route("/resilient/guard", methods=["POST"])
    @require_auth
    def route_resilient_guard():
        """Sweep-and-dismiss guard: scan for popups and clear the safe ones.

        Intended to be called before and/or after another automation action so
        stale/unexpected dialogs do not block subsequent input.

        Body (all optional):
          extra_patterns : list[str]
          mode           : "safe" (default) or "negative"
          dismiss        : bool  (default True) - if False, only reports popups
          settle_ms      : int   - wait between passes (default 250)
          max_iterations : int   - passes to make (default 5)
        Returns {status, swept, dismissed, remaining, iterations}.
        """
        d = _json_body() or {}
        mode = (d.get("mode") or "safe").strip().lower()
        if mode not in ("safe", "negative"):
            return jsonify({"error": "mode must be 'safe' or 'negative'"}), 400
        try:
            settle_ms = int(d.get("settle_ms", 250))
            max_iterations = int(d.get("max_iterations", 5))
        except (TypeError, ValueError):
            return jsonify({"error": "settle_ms and max_iterations must be integers"}), 400
        report = guard_run(
            extra_patterns=d.get("extra_patterns") or [],
            mode=mode,
            dismiss=bool(d.get("dismiss", True)),
            settle_ms=settle_ms,
            max_iterations=max_iterations,
        )
        return jsonify({"status": "ok", **report})

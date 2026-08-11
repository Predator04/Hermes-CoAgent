"""
Agent utility routes: observe-act and desktop status.

  GET  /desktop/status     — One-call snapshot of desktop state (window, mouse, CPU, etc.)
  POST /agent/observe-act  — Natural language single-call action (find + click + verify)
"""
import base64
import time
from flask import jsonify, request
from shared import _json_body, _log

HAS_PIL = False
try:
    from PIL import Image  # noqa: F401
    HAS_PIL = True
except ImportError:
    pass


def _make_error(error, detail="", suggestion="", code="ERROR"):
    return {
        "ok": False,
        "error": error,
        "detail": detail,
        "suggestion": suggestion,
        "code": code,
    }


# ── Desktop introspection helpers ─────────────────────────────────────────────

def _get_active_window_title():
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd)
    except Exception:
        pass
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value
    except Exception:
        return ""


def _get_mouse_position():
    try:
        import win32api
        x, y = win32api.GetCursorPos()
        return {"x": x, "y": y}
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return {"x": pt.x, "y": pt.y}
    except Exception:
        return {"x": 0, "y": 0}


def _get_screen_resolution():
    try:
        import ctypes
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        return {"width": int(w), "height": int(h)}
    except Exception:
        return {"width": 1920, "height": 1080}


def _get_idle_time_ms():
    """System idle time via GetLastInputInfo."""
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick_count = ctypes.windll.kernel32.GetTickCount()
            return max(0, int(tick_count) - int(lii.dwTime))
    except Exception:
        pass
    return None


def _get_system_stats():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        return {
            "cpu_percent": cpu,
            "ram_percent": mem.percent,
            "ram_used_mb": round(mem.used / 1024 / 1024, 1),
            "ram_total_mb": round(mem.total / 1024 / 1024, 1),
        }
    except ImportError:
        return {"cpu_percent": None, "ram_percent": None}
    except Exception:
        return {"cpu_percent": None, "ram_percent": None}


def _list_visible_windows():
    """Return titles of visible top-level windows."""
    titles = []
    try:
        import win32gui
        def cb(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if t:
                    ctx.append(t)
        win32gui.EnumWindows(cb, titles)
    except Exception:
        pass
    return titles


def _has_modal_dialog():
    """Heuristic: check if any visible window title contains common modal keywords."""
    MODAL_KEYWORDS = ("error", "warning", "confirm", "alert", "dialog", "save", "open file",
                      "print", "font", "color", "find", "replace")
    titles = _list_visible_windows()
    low = [t.lower() for t in titles]
    return any(any(kw in t for kw in MODAL_KEYWORDS) for t in low), titles


# ── Element-finding helper ────────────────────────────────────────────────────

_STOP_WORDS = frozenset((
    "the", "a", "an", "on", "in", "at", "to", "and", "or", "of",
    "click", "press", "tap", "select", "find", "open", "close",
    "button", "link", "field", "input", "checkbox", "tab",
))


def _extract_search_terms(instruction):
    """
    Turn a natural language instruction into a ranked list of search terms.
    e.g. "click the Submit button" → ["submit button", "submit", "button"]
    """
    words = [w.strip(".,!?\"'") for w in instruction.lower().split()]
    meaningful = [w for w in words if w and w not in _STOP_WORDS]
    terms = []
    # Full meaningful phrase
    if meaningful:
        terms.append(" ".join(meaningful))
    # Last meaningful word (usually the element name)
    if len(meaningful) > 1:
        terms.append(meaningful[-1])
    # All remaining words individually (largest first)
    for w in sorted(meaningful, key=len, reverse=True):
        if w not in terms:
            terms.append(w)
    return terms


# ── Routes ────────────────────────────────────────────────────────────────────

def register_routes(app, state, require_auth):

    @app.route("/desktop/status", methods=["GET"])
    @require_auth
    def route_desktop_status():
        """
        One-call desktop health snapshot for AI agents.
        Returns: active window, mouse position, resolution, idle time,
                 CPU/RAM, visible window list, and whether a modal is open.
        """
        active_window = _get_active_window_title()
        mouse = _get_mouse_position()
        resolution = _get_screen_resolution()
        idle_ms = _get_idle_time_ms()
        sys_stats = _get_system_stats()
        has_modal, windows = _has_modal_dialog()

        return jsonify({
            "ok": True,
            "active_window": active_window,
            "mouse": mouse,
            "resolution": resolution,
            "idle_ms": idle_ms,
            "idle_seconds": round(idle_ms / 1000, 1) if idle_ms is not None else None,
            "has_modal_dialog": has_modal,
            "window_count": len(windows),
            "visible_windows": windows[:40],
            **sys_stats,
        })

    @app.route("/agent/observe-act", methods=["POST"])
    @require_auth
    def route_observe_act():
        """
        Single-call observe-act loop for AI agents.
        Accepts: {"instruction": "click the Submit button"}
        Internally: screenshot → find element (UIA/OCR) → click → screenshot → return.
        Returns before/after screenshots so the agent can verify the action worked.
        """
        d = _json_body()
        instruction = (d.get("instruction") or d.get("text") or d.get("action") or "").strip()
        if not instruction:
            return jsonify(_make_error(
                "Missing instruction",
                "Provide {\"instruction\": \"click the Submit button\"}",
                "Use a natural language description of what to do",
                "MISSING_INSTRUCTION",
            )), 400

        t0 = time.time()

        # Step 1: Before screenshot
        before_b64 = ""
        try:
            from routes_ocr import _capture_jpeg
            before_data = _capture_jpeg(force=True)
            if before_data:
                before_b64 = base64.b64encode(before_data).decode()
        except Exception as exc:
            _log(f"[observe-act] before screenshot failed: {exc}")

        # Step 2: Find element (UIA → OCR fallback, multiple search terms)
        found = None
        method_used = None
        search_term_used = None

        try:
            from routes_uia import _get_uia_engine, _find_hybrid_element
            ue = _get_uia_engine()
            for term in _extract_search_terms(instruction):
                result = _find_hybrid_element(ue, term, fallback_to_ocr=True)
                if result.get("found"):
                    found = result
                    method_used = result.get("method", "uia")
                    search_term_used = term
                    break
        except Exception as exc:
            _log(f"[observe-act] element search failed: {exc}")

        if not found:
            return jsonify({
                "ok": False,
                "instruction": instruction,
                "error": f"Could not find element matching: {instruction!r}",
                "detail": "Searched UIA accessibility tree and screen OCR with no match",
                "suggestion": (
                    "Try POST /som/annotate to see numbered elements, "
                    "or be more specific in the instruction"
                ),
                "code": "ELEMENT_NOT_FOUND",
                "before_screenshot": before_b64,
                "elapsed_ms": round((time.time() - t0) * 1000),
            }), 404

        # Step 3: Click
        center = found.get("center", {})
        cx_val = center.get("x")
        cy_val = center.get("y")
        cx = int(cx_val if cx_val is not None else (found.get("x", 0) + found.get("width", 0) // 2))
        cy = int(cy_val if cy_val is not None else (found.get("y", 0) + found.get("height", 0) // 2))

        click_ok = False
        click_error = None
        try:
            from routes_mouse import _mouse_action
            click_res = _mouse_action("click", cx, cy, "left", True, state)
            if isinstance(click_res, tuple):
                http_status = int(click_res[1]) if len(click_res) > 1 else 200
            else:
                http_status = getattr(click_res, "status_code", 200)
            click_ok = http_status < 400
            if not click_ok:
                click_error = f"Click returned HTTP {http_status}"
        except Exception as exc:
            click_error = f"{type(exc).__name__}: {exc}"
            _log(f"[observe-act] click failed: {exc}")

        # Step 4: Wait and take after screenshot
        time.sleep(0.45)
        after_b64 = ""
        try:
            after_data = _capture_jpeg(force=True)
            if after_data:
                after_b64 = base64.b64encode(after_data).decode()
        except Exception as exc:
            _log(f"[observe-act] after screenshot failed: {exc}")

        screen_changed = bool(before_b64 and after_b64 and before_b64 != after_b64)
        elapsed_ms = round((time.time() - t0) * 1000)

        return jsonify({
            "ok": click_ok,
            "instruction": instruction,
            "search_term": search_term_used,
            "method": method_used,
            "element": {
                "text": found.get("element_info", {}).get("name") or found.get("element_info", {}).get("text", ""),
                "type": found.get("element_info", {}).get("control_type", ""),
                "bbox": {
                    "x": found.get("x", 0),
                    "y": found.get("y", 0),
                    "width": found.get("width", 0),
                    "height": found.get("height", 0),
                },
            },
            "clicked_at": {"x": cx, "y": cy},
            "click_ok": click_ok,
            "click_error": click_error,
            "screen_changed": screen_changed,
            "before_screenshot": before_b64,
            "after_screenshot": after_b64,
            "elapsed_ms": elapsed_ms,
        })

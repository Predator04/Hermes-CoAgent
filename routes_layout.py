"""Window layout profile save/restore routes."""
import ctypes
import ctypes.wintypes
import json
import struct
import threading
import time

from flask import jsonify
from shared import COAGENT_DIR, _json_body, _log, _missing_field

LAYOUTS_FILE = COAGENT_DIR / "layouts.json"
_LAYOUTS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_layouts():
    try:
        if LAYOUTS_FILE.exists():
            return json.loads(LAYOUTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_layouts(layouts):
    LAYOUTS_FILE.write_text(json.dumps(layouts, indent=2, ensure_ascii=False),
                            encoding="utf-8")


# ---------------------------------------------------------------------------
# Window enumeration
# ---------------------------------------------------------------------------

def _enum_windows():
    """Return a list of dicts for every visible, titled desktop window."""
    windows = []

    def _cb(hwnd, _lparam):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True

        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

        # WINDOWPLACEMENT to capture minimized/maximized state
        placement_buf = ctypes.create_string_buffer(44)
        struct.pack_into("<I", placement_buf, 0, 44)  # cbSize
        ctypes.windll.user32.GetWindowPlacement(hwnd, placement_buf)
        show_cmd = struct.unpack_from("<I", placement_buf, 4)[0]

        windows.append({
            "hwnd": hwnd,
            "title": title[:200],
            "pid": pid.value,
            "rect": {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
            },
            "show_cmd": show_cmd,
        })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return windows


# ---------------------------------------------------------------------------
# Restore logic
# ---------------------------------------------------------------------------

def _restore_window(entry):
    """Move a window back to its saved position.  Returns (ok, error_msg)."""
    title = entry.get("title", "")
    rect = entry.get("rect", {})
    show_cmd = entry.get("show_cmd", 1)

    windows = _enum_windows()

    # Exact title match first, then prefix/contains fallback
    match = next((w for w in windows if w["title"] == title), None)
    if not match:
        title_lower = title.lower()
        match = next(
            (w for w in windows if title_lower[:40] in w["title"].lower()),
            None,
        )
    if not match:
        return False, f"No window matching '{title[:60]}'"

    hwnd = match["hwnd"]
    l = rect.get("left", 0)
    t = rect.get("top", 0)
    w = rect.get("right", 800) - l
    h = rect.get("bottom", 600) - t

    SW_RESTORE = 9
    SW_MAXIMIZE = 3
    SW_MINIMIZE = 6
    SW_SHOWNORMAL = 1

    if show_cmd == SW_MAXIMIZE:
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.04)
        ctypes.windll.user32.ShowWindow(hwnd, SW_MAXIMIZE)
    elif show_cmd == SW_MINIMIZE:
        ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
    else:
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.04)
        ctypes.windll.user32.MoveWindow(hwnd, l, t, w, h, True)

    return True, None


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/layout/list", methods=["GET"])
    @require_auth
    def route_layout_list():
        """List all saved window layout profiles."""
        with _LAYOUTS_LOCK:
            layouts = _load_layouts()
        profiles = [
            {
                "name": name,
                "saved_at": data.get("saved_at"),
                "window_count": len(data.get("windows", [])),
            }
            for name, data in layouts.items()
        ]
        return jsonify({"status": "ok", "count": len(profiles), "profiles": profiles})

    @app.route("/layout/save", methods=["POST"])
    @require_auth
    def route_layout_save():
        """Save current window positions as a named layout profile.
        Body: {"name": "my-layout"}"""
        d = _json_body()
        name = d.get("name", "").strip()
        if not name:
            return _missing_field("name")
        if len(name) > 80:
            return jsonify({"error": "name too long (max 80 chars)"}), 400

        try:
            windows = _enum_windows()
            profile = {
                "name": name,
                "saved_at": time.time(),
                "windows": windows,
            }
            with _LAYOUTS_LOCK:
                layouts = _load_layouts()
                layouts[name] = profile
                _save_layouts(layouts)
            _log(f"Layout saved: '{name}' ({len(windows)} windows)")
            return jsonify({"status": "ok", "name": name, "window_count": len(windows)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/layout/restore", methods=["POST"])
    @require_auth
    def route_layout_restore():
        """Restore windows to a saved layout profile.
        Body: {"name": "my-layout"}"""
        d = _json_body()
        name = d.get("name", "").strip()
        if not name:
            return _missing_field("name")

        with _LAYOUTS_LOCK:
            layouts = _load_layouts()

        profile = layouts.get(name)
        if not profile:
            available = list(layouts.keys())
            return jsonify({"error": f"Layout '{name}' not found",
                            "available": available}), 404

        results = []
        for entry in profile.get("windows", []):
            ok, err = _restore_window(entry)
            results.append({
                "title": entry.get("title", "")[:80],
                "restored": ok,
                "error": err,
            })
            time.sleep(0.02)

        restored = sum(1 for r in results if r["restored"])
        _log(f"Layout restored: '{name}' ({restored}/{len(results)})")
        return jsonify({
            "status": "ok",
            "name": name,
            "restored": restored,
            "total": len(results),
            "results": results,
        })

    @app.route("/layout/delete", methods=["POST"])
    @require_auth
    def route_layout_delete():
        """Delete a saved layout profile.
        Body: {"name": "my-layout"}"""
        d = _json_body()
        name = d.get("name", "").strip()
        if not name:
            return _missing_field("name")
        with _LAYOUTS_LOCK:
            layouts = _load_layouts()
            if name not in layouts:
                return jsonify({"error": f"Layout '{name}' not found",
                                "available": list(layouts.keys())}), 404
            del layouts[name]
            _save_layouts(layouts)
        _log(f"Layout deleted: '{name}'")
        return jsonify({"status": "ok", "deleted": name})

"""Wallpaper, windows, clipboard, scheduler, macro, tunnel, voice, and misc routes."""
import os, json, subprocess, time, ctypes, re, threading, webbrowser, tempfile, shutil, sys, types, urllib.parse
from pathlib import Path
from flask import jsonify, request
from shared import _json_body, _log, _missing_field, COAGENT_DIR, MACROS_DIR, SCREENSHOTS_DIR, \
    TUNNEL_LOG, SERVER_PORT, _sanitize_path, sse_response
from routes_config import backup_file

# In-memory action history (shared with main)
_action_history = []
_MAX_HISTORY = 1000
_ACTION_HISTORY_LOCK = threading.RLock()

# Macro state
_recording = False
_recorded_actions = []
_RECORDING_LOCK = threading.Lock()

# Scheduler state
SCHEDULER_FILE = COAGENT_DIR / "scheduler.json"
_SCHEDULER_LOCK = threading.Lock()

_MACRO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_TUNNEL_URL_RE = re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9._~:/?#@!$&'()*+,;=%-]*")
_TUNNEL_PUBLIC_HOSTS = (
    "trycloudflare.com",
    "ngrok-free.app",
    "ngrok.io",
    "ngrok.app",
    "ngrok.dev",
)
_TUNNEL_LOCK = threading.RLock()
_TUNNEL_STATE = {
    "process": None,
    "method": None,
    "url": None,
    "port": None,
    "started_at": None,
    "exit_code": None,
    "output": [],
}
_SEARCH_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    "env", "AppData", "Application Data", "Local Settings", "Temp",
    "Cache", "Caches", "Code Cache",
}
_SEARCH_SKIP_DIRS_LOWER = {name.lower() for name in _SEARCH_SKIP_DIRS}

def _json_safe(value):
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "get_json"):
        try:
            payload = value.get_json(silent=True)
            if payload is not None:
                return payload
        except Exception:
            pass
    return str(value)[:500]

def _record_action(action_type, data=None, result=None):
    action_type = str(action_type or "").strip().lower()
    action_data = dict(data) if isinstance(data, dict) else {"value": data}
    action = dict(action_data)
    action.setdefault("type", action_type)
    entry = {
        "time": time.time(),
        "source": "input",
        "type": action.get("type", action_type),
        "action": action,
        "data": action_data,
        "result": _json_safe(result),
    }
    with _ACTION_HISTORY_LOCK:
        _action_history.append(entry)
        del _action_history[:-_MAX_HISTORY]
    with _RECORDING_LOCK:
        if _recording:
            _recorded_actions.append(action)
            del _recorded_actions[:-_MAX_HISTORY]
    return entry

def _install_record_action_hook():
    module = sys.modules.get("coagent_features")
    if module is None:
        module = types.ModuleType("coagent_features")
        sys.modules["coagent_features"] = module
    setattr(module, "record_action", _record_action)

_install_record_action_hook()

def _tunnel_tools():
    return {
        "cloudflare": shutil.which("cloudflared") or shutil.which("cloudflared.exe"),
        "ngrok": shutil.which("ngrok") or shutil.which("ngrok.exe"),
    }

def _coerce_tunnel_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid tunnel port")
    if port < 1 or port > 65535:
        raise ValueError("Tunnel port must be between 1 and 65535")
    return port

def _extract_tunnel_url(text):
    for match in _TUNNEL_URL_RE.findall(text or ""):
        lowered = match.lower().rstrip(".,);]")
        if lowered.startswith("http://127.") or lowered.startswith("http://localhost"):
            continue
        try:
            parsed = urllib.parse.urlparse(match)
            hostname = parsed.hostname or ""
        except Exception:
            continue
        if hostname.endswith(_TUNNEL_PUBLIC_HOSTS):
            return match.rstrip(".,);]")
    return None

def _append_tunnel_output(method, text):
    line = (text or "").rstrip()
    if not line:
        return
    try:
        with TUNNEL_LOG.open("a", encoding="utf-8", errors="replace") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{method}] {line}\n")
    except Exception:
        pass
    url = _extract_tunnel_url(line)
    with _TUNNEL_LOCK:
        _TUNNEL_STATE["output"].append(line)
        del _TUNNEL_STATE["output"][:-200]
        if url:
            _TUNNEL_STATE["url"] = url

def _tunnel_reader(proc, method):
    try:
        if proc.stdout is not None:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                _append_tunnel_output(method, line)
    except Exception as e:
        _append_tunnel_output(method, f"reader error: {type(e).__name__}: {e}")
    finally:
        try:
            exit_code = proc.poll()
        except Exception:
            exit_code = None
        with _TUNNEL_LOCK:
            if _TUNNEL_STATE.get("process") is proc:
                _TUNNEL_STATE["exit_code"] = exit_code

def _tunnel_active_locked():
    proc = _TUNNEL_STATE.get("process")
    return bool(proc is not None and proc.poll() is None)

def _tunnel_status_snapshot():
    with _TUNNEL_LOCK:
        active = _tunnel_active_locked()
        started_at = _TUNNEL_STATE.get("started_at")
        uptime = int(time.time() - started_at) if active and started_at else 0
        proc = _TUNNEL_STATE.get("process")
        exit_code = None if active or proc is None else proc.poll()
        return {
            "active": active,
            "url": _TUNNEL_STATE.get("url") if active else None,
            "method": _TUNNEL_STATE.get("method") if active else None,
            "port": _TUNNEL_STATE.get("port") if active else None,
            "uptime": uptime,
            "pid": proc.pid if active and proc is not None else None,
            "exit_code": exit_code,
            "tools": {k: bool(v) for k, v in _tunnel_tools().items()},
            "recent_output": list(_TUNNEL_STATE.get("output", []))[-10:],
        }

def _stop_tunnel_locked():
    proc = _TUNNEL_STATE.get("process")
    if proc is None:
        return False
    stopped = False
    if proc.poll() is None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, text=True, timeout=8)
            else:
                proc.terminate()
                proc.wait(timeout=8)
            stopped = True
        except Exception:
            try:
                proc.kill()
                stopped = True
            except Exception:
                pass
    _TUNNEL_STATE.update({
        "process": None,
        "method": None,
        "url": None,
        "port": None,
        "started_at": None,
        "exit_code": proc.poll(),
        "output": [],
    })
    return stopped

def _build_tunnel_command(method, exe, port):
    if method == "cloudflare":
        return [exe, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    if method == "ngrok":
        return [exe, "http", str(port), "--log=stdout"]
    raise ValueError("Unsupported tunnel method")

def _macro_path(name):
    if not isinstance(name, str) or not _MACRO_NAME_RE.fullmatch(name):
        raise ValueError("Invalid macro name")
    base = MACROS_DIR.resolve()
    path = (base / f"{name}.json").resolve()
    try:
        common = os.path.commonpath([os.path.normcase(str(base)), os.path.normcase(str(path))])
    except ValueError:
        raise ValueError("Invalid macro path")
    if common != os.path.normcase(str(base)):
        raise ValueError("Invalid macro path")
    return path

def _load_scheduler():
    if SCHEDULER_FILE.exists():
        try:
            return json.loads(SCHEDULER_FILE.read_text())
        except Exception:
            return {"actions": []}
    return {"actions": []}

def _save_scheduler(data):
    backup_file(SCHEDULER_FILE)
    SCHEDULER_FILE.write_text(json.dumps(data, indent=2))

def _scheduler_busy_response():
    return jsonify({"error": "Scheduler file is busy"}), 409

def register_routes(app, state, require_auth):
    # ── Windows ─────────────────────────────────────────
    @app.route("/windows", methods=["GET"])
    @require_auth
    def route_windows():
        try:
            import pygetwindow as gw
            wins = [{"title": w.title, "visible": w.visible} for w in gw.getAllWindows() if w.title]
            return jsonify({"windows": wins, "count": len(wins)})
        except ImportError:
            wins = []
            def enum_cb(hwnd, _):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                        if buf.value:
                            wins.append({"title": buf.value, "hwnd": hwnd})
                return True
            ctypes.windll.user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_cb), 0)
            return jsonify({"windows": wins, "count": len(wins)})

    @app.route("/windows/activate", methods=["POST"])
    @require_auth
    def route_win_activate():
        d = _json_body()
        title = d.get("title", "")
        needle = title.lower()
        try:
            import pygetwindow as gw
            for w in gw.getAllWindows():
                if needle in w.title.lower():
                    w.activate()
                    return jsonify({"status": "activated", "title": w.title})
        except Exception:
            def enum_cb(hwnd, _):
                buf = ctypes.create_unicode_buffer(512)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                if needle in buf.value.lower():
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    return False  # stop
                return True
            ctypes.windll.user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_cb), 0)
        return jsonify({"status": "activated", "title": title})

    # ── Wallpaper ──────────────────────────────────────
    @app.route("/wallpaper/set", methods=["POST"])
    @require_auth
    def route_wallpaper_set():
        d = _json_body()
        try:
            img_path = _sanitize_path(d.get("path", ""))
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        if os.path.isfile(img_path):
            ctypes.windll.user32.SystemParametersInfoW(20, 0, img_path, 2)
            _log(f"Wallpaper set to {img_path}")
            return jsonify({"status": "ok", "wallpaper": os.path.basename(img_path)})
        return jsonify({"error": "File not found"}), 404

    @app.route("/wallpaper/cycle", methods=["POST"])
    @app.route("/wallpaper/random", methods=["POST"])
    @require_auth
    def route_wallpaper_random():
        d = _json_body()
        folder_req = d.get("folder", "")
        if folder_req:
            try:
                folder = _sanitize_path(folder_req)
            except ValueError as e:
                return jsonify({"error": str(e)}), 403
        else:
            folder = str(SCREENSHOTS_DIR)
        if not os.path.isdir(folder):
            return jsonify({"error": "Folder not found"}), 404
        exts = ('.jpg','.jpeg','.png','.bmp','.gif')
        files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
        if not files:
            return jsonify({"error": "No images found"}), 404
        import random
        img = random.choice(files)
        ctypes.windll.user32.SystemParametersInfoW(20, 0, img, 2)
        _log(f"Wallpaper set to {os.path.basename(img)}")
        return jsonify({"status": "ok", "wallpaper": os.path.basename(img)})

    # ── Monitors ────────────────────────────────────────
    @app.route("/monitors", methods=["GET"])
    @require_auth
    def monitors_api():
        from routes_ocr import get_monitor_list
        monitors = get_monitor_list()
        physical = [m for m in monitors if m.get("id") != 0]
        primary = next((m for m in monitors if m.get("is_primary")), monitors[0] if monitors else {})
        return jsonify({
            "width": primary.get("width", 1920),
            "height": primary.get("height", 1080),
            "count": len(physical) or len(monitors),
            "monitors": monitors,
            "primary": primary,
        })

    @app.route("/monitors/list", methods=["GET"])
    @require_auth
    def monitors_list_api():
        from routes_ocr import get_monitor_list
        monitors = get_monitor_list()
        physical = [m for m in monitors if m.get("id") != 0]
        return jsonify({"monitors": monitors, "count": len(physical) or len(monitors)})

    @app.route("/monitors/layout", methods=["POST"])
    @require_auth
    def route_monitor_layout():
        d = _json_body()
        layout = d.get("layout", "grid")
        _log(f"Monitor layout: {layout}")
        return jsonify({"status": "ok", "layout": layout})

    @app.route("/monitors/info", methods=["GET"])
    @require_auth
    def route_monitors_info():
        """Enhanced monitor list: includes DPI, scaling %, work area (excluding taskbar),
        and exact pixel boundaries queried directly from the Windows API."""
        try:
            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("rcMonitor", ctypes.wintypes.RECT),
                    ("rcWork", ctypes.wintypes.RECT),
                    ("dwFlags", ctypes.c_uint),
                    ("szDevice", ctypes.c_wchar * 32),
                ]

            import ctypes.wintypes as _wt
            MonitorEnumProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(_wt.RECT), ctypes.c_longlong,
            )
            hmonitors = []

            def _mon_cb(hmon, _hdc, _rect, _data):
                hmonitors.append(hmon)
                return True

            ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_mon_cb), 0)

            monitors = []
            MONITORINFOF_PRIMARY = 1
            for idx, hmon in enumerate(hmonitors):
                info = MONITORINFOEX()
                info.cbSize = ctypes.sizeof(MONITORINFOEX)
                ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))

                r = info.rcMonitor
                w = info.rcWork
                is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)
                width = r.right - r.left
                height = r.bottom - r.top

                dpi_x = ctypes.c_uint(96)
                dpi_y = ctypes.c_uint(96)
                try:
                    ctypes.windll.shcore.GetDpiForMonitor(
                        hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
                    )
                except Exception:
                    pass

                monitors.append({
                    "index": idx,
                    "id": idx + 1,
                    "name": info.szDevice.strip() or f"Monitor {idx + 1}",
                    "is_primary": is_primary,
                    "left": r.left,
                    "top": r.top,
                    "width": width,
                    "height": height,
                    "right": r.right,
                    "bottom": r.bottom,
                    "work_area": {
                        "left": w.left,
                        "top": w.top,
                        "width": w.right - w.left,
                        "height": w.bottom - w.top,
                    },
                    "dpi": {"x": dpi_x.value, "y": dpi_y.value},
                    "scaling_pct": round(dpi_x.value / 96.0 * 100),
                })

            primary = next((m for m in monitors if m["is_primary"]), monitors[0] if monitors else {})
            return jsonify({
                "status": "ok",
                "count": len(monitors),
                "monitors": monitors,
                "primary": primary,
            })
        except Exception as exc:
            _log(f"monitors/info failed: {exc}")
            from routes_ocr import get_monitor_list
            monitors = get_monitor_list()
            return jsonify({"status": "fallback", "count": len(monitors), "monitors": monitors})

    @app.route("/monitors/cursor", methods=["GET"])
    @require_auth
    def route_monitors_cursor():
        """Return which monitor the cursor is currently on."""
        try:
            import ctypes.wintypes as _wt

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("rcMonitor", _wt.RECT),
                    ("rcWork", _wt.RECT),
                    ("dwFlags", ctypes.c_uint),
                    ("szDevice", ctypes.c_wchar * 32),
                ]

            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            cx, cy = pt.x, pt.y

            MONITOR_DEFAULTTONEAREST = 2
            hmon = ctypes.windll.user32.MonitorFromPoint(
                ctypes.wintypes.POINT(cx, cy), MONITOR_DEFAULTTONEAREST
            )
            info = MONITORINFOEX()
            info.cbSize = ctypes.sizeof(MONITORINFOEX)
            ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))

            r = info.rcMonitor
            MONITORINFOF_PRIMARY = 1
            return jsonify({
                "status": "ok",
                "cursor": {"x": cx, "y": cy},
                "monitor": {
                    "name": info.szDevice.strip(),
                    "is_primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    "left": r.left, "top": r.top,
                    "width": r.right - r.left,
                    "height": r.bottom - r.top,
                },
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/monitors/arrange", methods=["POST"])
    @require_auth
    def route_monitors_arrange():
        """Change display arrangement via DisplaySwitch.exe.
        Body: {"mode": "extend"|"duplicate"|"internal"|"external"}"""
        d = _json_body()
        mode = d.get("mode", "extend").lower()
        mode_map = {
            "extend": "/extend",
            "duplicate": "/clone",
            "internal": "/internal",
            "external": "/external",
        }
        flag = mode_map.get(mode)
        if not flag:
            return jsonify({"error": f"Unknown mode '{mode}'",
                            "valid": list(mode_map.keys())}), 400
        try:
            subprocess.Popen(["DisplaySwitch.exe", flag])
            _log(f"Monitor arrange: {mode} ({flag})")
            return jsonify({"status": "ok", "mode": mode, "flag": flag})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/window/move-to-monitor", methods=["POST"])
    @require_auth
    def route_window_move_to_monitor():
        """Move a window to a specific monitor by monitor index.
        Body: {"title": "...", "monitor_index": 1, "maximize": false}
        Monitor index 0 = primary; 1 = second monitor, etc."""
        d = _json_body()
        title = d.get("title", "").strip()
        monitor_index = int(d.get("monitor_index", 0))
        maximize = bool(d.get("maximize", False))

        if not title:
            return _missing_field("title")

        try:
            import ctypes.wintypes as _wt

            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("rcMonitor", _wt.RECT),
                    ("rcWork", _wt.RECT),
                    ("dwFlags", ctypes.c_uint),
                    ("szDevice", ctypes.c_wchar * 32),
                ]

            MonitorEnumProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(_wt.RECT), ctypes.c_longlong,
            )
            hmonitors = []

            def _cb(hm, _hdc, _rect, _data):
                hmonitors.append(hm)
                return True

            ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)

            if monitor_index >= len(hmonitors):
                return jsonify({"error": f"monitor_index {monitor_index} out of range",
                                "monitor_count": len(hmonitors)}), 400

            hmon = hmonitors[monitor_index]
            info = MONITORINFOEX()
            info.cbSize = ctypes.sizeof(MONITORINFOEX)
            ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))
            r = info.rcWork  # use work area to avoid taskbar

            # Find target window
            windows = []
            def _wcb(hwnd, _):
                if not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                t = buf.value.strip()
                if title.lower() in t.lower():
                    windows.append(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
            )
            ctypes.windll.user32.EnumWindows(WNDENUMPROC(_wcb), 0)

            if not windows:
                return jsonify({"error": f"No visible window matching '{title}'"}), 404

            hwnd = windows[0]
            SW_RESTORE = 9
            SW_MAXIMIZE = 3
            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.05)

            if maximize:
                ctypes.windll.user32.MoveWindow(hwnd, r.left, r.top,
                                                r.right - r.left, r.bottom - r.top, True)
                ctypes.windll.user32.ShowWindow(hwnd, SW_MAXIMIZE)
            else:
                work_w = r.right - r.left
                work_h = r.bottom - r.top
                ctypes.windll.user32.MoveWindow(hwnd, r.left, r.top,
                                                min(work_w, 1280),
                                                min(work_h, 720), True)

            _log(f"Moved '{title}' to monitor {monitor_index} maximize={maximize}")
            return jsonify({"status": "ok", "hwnd": hwnd, "monitor_index": monitor_index,
                            "maximize": maximize})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ── Clipboard ──────────────────────────────────────
    @app.route("/clipboard/get", methods=["GET"])
    @require_auth
    def route_clipboard_get():
        try:
            import pyperclip
            return jsonify({"text": pyperclip.paste()})
        except Exception:
            return jsonify({"text": ""})

    @app.route("/clipboard/set", methods=["POST"])
    @require_auth
    def route_clipboard_set():
        d = _json_body()
        text = d.get("text", "")
        try:
            import pyperclip
            pyperclip.copy(text)
            return jsonify({"status": "ok", "chars": len(text)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── TTS ─────────────────────────────────────────────
    @app.route("/tts/speak", methods=["POST"])
    @require_auth
    def route_tts_speak():
        d = _json_body()
        text = d.get("text", "")
        if not text:
            return _missing_field("text")
        if len(text) > 10000:
            return jsonify({"error": "Text too long (max 10000 chars)"}), 400
        text_path = None
        ps_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as text_file:
                text_file.write(text)
                text_path = text_file.name
            with tempfile.NamedTemporaryFile("w", suffix=".ps1", encoding="utf-8", delete=False) as ps_file:
                ps_file.write('''param(
    [Parameter(Mandatory=$true)]
    [string]$TextPath
)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
$s.Speak($text)
''')
                ps_path = ps_file.name
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", ps_path, "-TextPath", text_path], timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            return jsonify({"status": "spoken", "text": text[:100]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            for path in (text_path, ps_path):
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    # ── Scheduler ──────────────────────────────────────
    @app.route("/scheduler/list", methods=["GET"])
    @require_auth
    def route_scheduler_list():
        if not _SCHEDULER_LOCK.acquire(blocking=False):
            return _scheduler_busy_response()
        try:
            return jsonify(_load_scheduler())
        finally:
            _SCHEDULER_LOCK.release()

    @app.route("/scheduler/add", methods=["POST"])
    @require_auth
    def route_scheduler_add():
        d = _json_body()
        name = d.get("name", f"action_{int(time.time())}")
        if not isinstance(name, str) or len(name) > 100:
            return jsonify({"error": "Invalid name"}), 400
        cron = d.get("cron", "* * * * *")
        if not isinstance(cron, str) or len(cron) > 200:
            return jsonify({"error": "Invalid cron expression"}), 400
        action = d.get("action", {})
        if not isinstance(action, dict):
            return jsonify({"error": "Invalid action (must be a dict)"}), 400
        if not _SCHEDULER_LOCK.acquire(blocking=False):
            return _scheduler_busy_response()
        try:
            data = _load_scheduler()
            for a in data["actions"]:
                if a["name"] == name:
                    a["cron"] = cron; a["action"] = action; a["updated"] = time.time()
                    _save_scheduler(data)
                    return jsonify({"status": "updated", "name": name})
            data["actions"].append({"name": name, "cron": cron, "action": action, "created": time.time()})
            _save_scheduler(data)
            _log(f"Scheduler: added '{name}' at {cron}")
            return jsonify({"status": "added", "name": name})
        finally:
            _SCHEDULER_LOCK.release()

    @app.route("/scheduler/remove", methods=["POST"])
    @require_auth
    def route_scheduler_remove():
        d = _json_body()
        name = d.get("name", "")
        if not _SCHEDULER_LOCK.acquire(blocking=False):
            return _scheduler_busy_response()
        try:
            data = _load_scheduler()
            data["actions"] = [a for a in data["actions"] if a["name"] != name]
            _save_scheduler(data)
            _log(f"Scheduler: removed '{name}'")
            return jsonify({"status": "removed", "name": name})
        finally:
            _SCHEDULER_LOCK.release()

    @app.route("/scheduler/run", methods=["POST"])
    @require_auth
    def route_scheduler_run():
        d = _json_body()
        name = d.get("name", "")
        if not _SCHEDULER_LOCK.acquire(blocking=False):
            return _scheduler_busy_response()
        try:
            data = _load_scheduler()
            for a in data["actions"]:
                if a["name"] == name:
                    _log(f"Scheduler: ran '{name}'")
                    return jsonify({"status": "executed", "name": name})
        finally:
            _SCHEDULER_LOCK.release()
        return jsonify({"error": f"Action '{name}' not found"}), 404

    # ── Macros ─────────────────────────────────────────
    @app.route("/macro/list", methods=["GET", "POST"])
    @require_auth
    def route_macro_list():
        macros = []
        if MACROS_DIR.exists():
            for f in sorted(MACROS_DIR.glob("*.json")):
                try:
                    macros.append({"name": f.stem, "path": str(f), "size": f.stat().st_size})
                except Exception:
                    pass
        return jsonify({"macros": macros, "count": len(macros)})

    @app.route("/macro/save", methods=["POST"])
    @require_auth
    def route_macro_save():
        d = _json_body()
        name = d.get("name", f"macro_{int(time.time())}")
        actions = d.get("actions", [])
        try:
            path = _macro_path(name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = backup_file(path)
        path.write_text(json.dumps({"name": name, "actions": actions}, indent=2), encoding="utf-8")
        _log(f"Macro saved: {name} ({len(actions)} actions)")
        return jsonify({"status": "saved", "name": name, "count": len(actions), "backup": backup_path})

    @app.route("/macro/run", methods=["POST"])
    @require_auth
    def route_macro_run():
        d = _json_body()
        name = d.get("name", "")
        try:
            path = _macro_path(name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not path.exists():
            return jsonify({"error": f"Macro '{name}' not found"}), 404
        macro = json.loads(path.read_text(encoding="utf-8"))
        actions = macro.get("actions", [])
        for a in actions:
            from routes_mouse import _execute_action_wrapper
            _execute_action_wrapper(a, state)
            time.sleep(0.05)
        return jsonify({"status": "executed", "name": name, "count": len(actions)})

    @app.route("/macro/record", methods=["POST"])
    @require_auth
    def route_macro_record():
        global _recording, _recorded_actions
        d = _json_body()
        enable = d.get("enable", True)
        with _RECORDING_LOCK:
            if enable:
                if _recording:
                    return jsonify({"error": "Recording already in progress"}), 409
                _recording = True
                _recorded_actions = []
                return jsonify({"status": "recording"})
            _recording = False
            return jsonify({"status": "stopped", "actions": list(_recorded_actions)})

    @app.route("/macro/delete", methods=["POST"])
    @require_auth
    def route_macro_delete():
        d = _json_body()
        name = d.get("name", "")
        try:
            path = _macro_path(name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if path.exists():
            backup_path = backup_file(path)
            path.unlink()
            return jsonify({"status": "deleted", "name": name, "backup": backup_path})
        return jsonify({"error": f"Macro '{name}' not found"}), 404

    @app.route("/replay", methods=["POST"])
    @require_auth
    def route_replay():
        d = _json_body()
        count = max(0, min(int(d.get("count", 5)), 100))
        from routes_mouse import _execute_action_wrapper
        with _ACTION_HISTORY_LOCK:
            actions = list(_action_history)[-count:]
        for a in actions:
            _execute_action_wrapper(a.get("action", {}), state)
            time.sleep(0.05)
        return jsonify({"status": "replayed", "count": len(actions)})

    # ── Voice ─────────────────────────────────────────
    @app.route("/voice/toggle", methods=["POST"])
    @require_auth
    def route_voice_toggle():
        d = _json_body()
        enable = d.get("enable", True)
        _log(f"Voice toggle: {enable}")
        return jsonify({"status": "ok", "voice": enable})

    # ── Tunnel ─────────────────────────────────────────
    @app.route("/tunnel/start", methods=["POST"])
    @require_auth
    def route_tunnel_start():
        d = _json_body()
        method = str(d.get("method", "cloudflare")).strip().lower()
        if method not in {"cloudflare", "ngrok"}:
            return jsonify({"error": "Unsupported tunnel method", "allowed": ["cloudflare", "ngrok"]}), 400
        try:
            port = _coerce_tunnel_port(d.get("port", SERVER_PORT))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        try:
            wait_timeout = max(1.0, min(float(d.get("timeout", 20)), 60.0))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid tunnel timeout"}), 400

        tools = _tunnel_tools()
        exe = tools.get(method)
        if not exe:
            _log(f"Tunnel start failed: {method} not found in PATH")
            return jsonify({
                "error": f"{method} not found in PATH",
                "method": method,
                "tools": {k: bool(v) for k, v in tools.items()},
            }), 404

        with _TUNNEL_LOCK:
            if _tunnel_active_locked():
                current = _tunnel_status_snapshot()
                return jsonify({"status": "already_running", **current}), 200
            _TUNNEL_STATE.update({
                "process": None,
                "method": method,
                "url": None,
                "port": port,
                "started_at": time.time(),
                "exit_code": None,
                "output": [],
            })

        cmd = _build_tunnel_command(method, exe, port)
        create_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(COAGENT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=create_flags,
            )
        except Exception as e:
            with _TUNNEL_LOCK:
                _TUNNEL_STATE.update({"process": None, "started_at": None, "exit_code": None})
            _log(f"Tunnel start failed ({method}): {type(e).__name__}: {e}")
            return jsonify({"error": str(e), "method": method}), 500

        with _TUNNEL_LOCK:
            _TUNNEL_STATE["process"] = proc
        threading.Thread(target=_tunnel_reader, args=(proc, method), daemon=True,
                         name=f"tunnel-{method}-reader").start()
        _append_tunnel_output(method, "started: " + " ".join(cmd))

        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            with _TUNNEL_LOCK:
                url = _TUNNEL_STATE.get("url")
                active = _tunnel_active_locked()
                recent = list(_TUNNEL_STATE.get("output", []))[-10:]
            if url:
                _log(f"Tunnel started: method={method} port={port} url={url}")
                return jsonify({
                    "status": "tunnel_started",
                    "active": True,
                    "method": method,
                    "port": port,
                    "url": url,
                    "pid": proc.pid,
                })
            if not active:
                exit_code = proc.poll()
                _log(f"Tunnel exited before URL: method={method} exit={exit_code}")
                return jsonify({
                    "error": "Tunnel process exited before public URL was detected",
                    "method": method,
                    "port": port,
                    "exit_code": exit_code,
                    "recent_output": recent,
                }), 502
            time.sleep(0.25)

        _log(f"Tunnel still starting: method={method} port={port} pid={proc.pid}")
        return jsonify({
            "error": "Timed out waiting for public tunnel URL",
            "status": "starting",
            "active": proc.poll() is None,
            "method": method,
            "port": port,
            "pid": proc.pid,
            "recent_output": _tunnel_status_snapshot()["recent_output"],
        }), 504

    @app.route("/tunnel/stop", methods=["POST"])
    @require_auth
    def route_tunnel_stop():
        with _TUNNEL_LOCK:
            was_active = _tunnel_active_locked()
            stopped = _stop_tunnel_locked()
        _log(f"Tunnel stop requested: was_active={was_active} stopped={stopped}")
        return jsonify({"status": "tunnel_stopped", "was_active": was_active, "stopped": stopped})

    @app.route("/tunnel/status", methods=["GET"])
    @require_auth
    def route_tunnel_status():
        return jsonify(_tunnel_status_snapshot())

    # ── Search files ───────────────────────────────────
    @app.route("/search/files", methods=["POST"])
    @require_auth
    def route_search_files():
        d = _json_body()
        pattern = d.get("pattern", "*")
        try:
            search_path = _sanitize_path(d.get("path", os.environ.get("USERPROFILE", str(Path.home()))))
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        import fnmatch
        try:
            limit = max(1, min(int(d.get("limit", 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            max_seconds = max(0.25, min(float(d.get("max_seconds", 5.0)), 30.0))
        except (TypeError, ValueError):
            max_seconds = 5.0
        try:
            max_dirs = max(1, min(int(d.get("max_dirs", 2000)), 20000))
        except (TypeError, ValueError):
            max_dirs = 2000
        results = []
        started = time.time()
        dirs_seen = 0
        stopped = None
        try:
            for root, dirs, files in os.walk(search_path):
                dirs_seen += 1
                dirs[:] = [dd for dd in dirs if dd.lower() not in _SEARCH_SKIP_DIRS_LOWER]
                if dirs_seen > max_dirs:
                    stopped = "max_dirs"
                    break
                if time.time() - started > max_seconds:
                    stopped = "max_seconds"
                    break
                try:
                    for f in files:
                        if len(results) >= limit: break
                        if fnmatch.fnmatch(f, pattern):
                            full = os.path.join(root, f)
                            try: sz = os.path.getsize(full)
                            except Exception: sz = 0
                            results.append({"path": full, "name": f, "size": sz})
                except (PermissionError, OSError): continue
                if len(results) >= limit: break
        except Exception:
            pass
        return jsonify({"matches": results, "count": len(results), "pattern": pattern,
                        "dirs_scanned": dirs_seen, "stopped": stopped})

    # ── Stats & History ────────────────────────────────
    @app.route("/stats", methods=["GET"])
    @require_auth
    def route_stats():
        uptime = time.time() - getattr(state, 'start_time', time.time())
        with _ACTION_HISTORY_LOCK:
            action_count = len(_action_history)
        state_history = getattr(state, "action_history", None)
        if state_history is not None and state_history is not _action_history:
            action_count += len(state_history)
        return jsonify({"actions": action_count, "uptime": int(uptime),
                        "macros": len(list(MACROS_DIR.glob("*.json"))) if MACROS_DIR.exists() else 0})

    @app.route("/history", methods=["GET"])
    @require_auth
    def route_history():
        limit = max(0, min(int(request.args.get("limit", 50)), 500))
        with _ACTION_HISTORY_LOCK:
            actions = list(_action_history)[-limit:]
            total = len(_action_history)
        return jsonify({"actions": actions, "count": min(limit, total)})

    @app.route("/events", methods=["GET"])
    @require_auth
    def route_events():
        return sse_response()

    @app.route("/launch/ai", methods=["POST"])
    @require_auth
    def route_launch_ai():
        d = _json_body()
        query = d.get("query", d.get("app", "")).lower()
        if not query: return _missing_field("query")
        app_map = {"chrome": "chrome.exe", "google": "chrome.exe", "browser": "chrome.exe",
                   "firefox": "firefox.exe", "edge": "msedge.exe", "notepad": "notepad.exe",
                   "calculator": "calc.exe", "cmd": "cmd.exe", "terminal": "cmd.exe",
                   "powershell": "powershell.exe", "word": "winword.exe", "excel": "excel.exe",
                   "outlook": "outlook.exe", "vscode": "code.exe", "code": "code.exe",
                   "telegram": "Telegram.exe", "discord": "Discord.exe", "explorer": "explorer.exe",
                   "settings": "ms-settings:", "task manager": "taskmgr.exe", "paint": "mspaint.exe",
                   "spotify": "Spotify.exe", "vlc": "vlc.exe", "steam": "steam.exe"}
        for key, exe in app_map.items():
            if key in query:
                try:
                    if exe.startswith("ms-"): os.startfile(exe)
                    else: subprocess.Popen([exe])
                    return jsonify({"status": "launched", "app": exe, "query": query})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
        if re.match(r'^https?://', query):
            webbrowser.open_new_tab(query)
            return jsonify({"status": "launched", "app": "browser", "url": query})
        return jsonify({"error": f"Could not find app matching '{query}'"}), 404

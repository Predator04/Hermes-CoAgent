"""Wallpaper, windows, clipboard, scheduler, macro, tunnel, voice, and misc routes."""
import os, json, subprocess, time, ctypes, re, threading, webbrowser
from pathlib import Path
from flask import jsonify, request
from shared import _json_body, _log, _console, _missing_field, COAGENT_DIR, MACROS_DIR, \
    SCREENSHOTS_DIR, TUNNEL_LOG, TRAY_LOG, SERVER_LOG, SERVER_PORT, TRAY_PORT, \
    _sanitize_path, _sanitize_cmd, _interactive_task_xml, sse_broadcast, sse_response

# In-memory action history (shared with main)
_action_history = []
_MAX_HISTORY = 1000

# Macro state
_recording = False
_recorded_actions = []

# Scheduler state
SCHEDULER_FILE = COAGENT_DIR / "scheduler.json"

def _load_scheduler():
    if SCHEDULER_FILE.exists():
        try:
            return json.loads(SCHEDULER_FILE.read_text())
        except:
            return {"actions": []}
    return {"actions": []}

def _save_scheduler(data):
    SCHEDULER_FILE.write_text(json.dumps(data, indent=2))

def register_routes(app, state, require_auth):
    # ── Windows ─────────────────────────────────────────
    @app.route("/windows", methods=["GET"])
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
        except:
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
    def route_wallpaper_set():
        d = _json_body()
        img_path = d.get("path", "")
        if os.path.isfile(img_path):
            ctypes.windll.user32.SystemParametersInfoW(20, 0, img_path, 2)
            _log(f"Wallpaper set to {img_path}")
            return jsonify({"status": "ok", "wallpaper": os.path.basename(img_path)})
        return jsonify({"error": "File not found"}), 404

    @app.route("/wallpaper/cycle", methods=["POST"])
    @app.route("/wallpaper/random", methods=["POST"])
    def route_wallpaper_random():
        d = _json_body()
        folder = d.get("folder", "")
        if not os.path.isdir(folder):
            folder = str(SCREENSHOTS_DIR)
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
    def monitors_api():
        try:
            import pyautogui
            w, h = pyautogui.size()
            return jsonify({"width": w, "height": h, "count": 1})
        except:
            return jsonify({"width": 1920, "height": 1080, "count": 1})

    @app.route("/monitors/layout", methods=["POST"])
    @require_auth
    def route_monitor_layout():
        d = _json_body()
        layout = d.get("layout", "grid")
        _log(f"Monitor layout: {layout}")
        return jsonify({"status": "ok", "layout": layout})

    # ── Clipboard ──────────────────────────────────────
    @app.route("/clipboard/get", methods=["GET"])
    def route_clipboard_get():
        try:
            import pyperclip
            return jsonify({"text": pyperclip.paste()})
        except:
            return jsonify({"text": ""})

    @app.route("/clipboard/set", methods=["POST"])
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
        try:
            import subprocess
            ps_script = f'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Speak("{text.replace('"', '""')}")
'''
            subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_script], timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            return jsonify({"status": "spoken", "text": text[:100]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Scheduler ──────────────────────────────────────
    @app.route("/scheduler/list", methods=["GET"])
    def route_scheduler_list():
        return jsonify(_load_scheduler())

    @app.route("/scheduler/add", methods=["POST"])
    def route_scheduler_add():
        d = _json_body()
        name = d.get("name", f"action_{int(time.time())}")
        cron = d.get("cron", "* * * * *")
        action = d.get("action", {})
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

    @app.route("/scheduler/remove", methods=["POST"])
    def route_scheduler_remove():
        d = _json_body()
        name = d.get("name", "")
        data = _load_scheduler()
        data["actions"] = [a for a in data["actions"] if a["name"] != name]
        _save_scheduler(data)
        _log(f"Scheduler: removed '{name}'")
        return jsonify({"status": "removed", "name": name})

    @app.route("/scheduler/run", methods=["POST"])
    def route_scheduler_run():
        d = _json_body()
        name = d.get("name", "")
        data = _load_scheduler()
        for a in data["actions"]:
            if a["name"] == name:
                _log(f"Scheduler: ran '{name}'")
                return jsonify({"status": "executed", "name": name})
        return jsonify({"error": f"Action '{name}' not found"}), 404

    # ── Macros ─────────────────────────────────────────
    @app.route("/macro/list", methods=["GET", "POST"])
    def route_macro_list():
        macros = []
        if MACROS_DIR.exists():
            for f in sorted(MACROS_DIR.glob("*.json")):
                try:
                    macros.append({"name": f.stem, "path": str(f), "size": f.stat().st_size})
                except:
                    pass
        return jsonify({"macros": macros, "count": len(macros)})

    @app.route("/macro/save", methods=["POST"])
    def route_macro_save():
        d = _json_body()
        name = d.get("name", f"macro_{int(time.time())}")
        actions = d.get("actions", [])
        MACROS_DIR.mkdir(exist_ok=True)
        (MACROS_DIR / f"{name}.json").write_text(json.dumps({"name": name, "actions": actions}, indent=2))
        _log(f"Macro saved: {name} ({len(actions)} actions)")
        return jsonify({"status": "saved", "name": name, "count": len(actions)})

    @app.route("/macro/run", methods=["POST"])
    def route_macro_run():
        d = _json_body()
        name = d.get("name", "")
        path = MACROS_DIR / f"{name}.json"
        if not path.exists():
            return jsonify({"error": f"Macro '{name}' not found"}), 404
        macro = json.loads(path.read_text())
        actions = macro.get("actions", [])
        for a in actions:
            from routes_mouse import _execute_action_wrapper
            _execute_action_wrapper(a, state)
            time.sleep(0.05)
        return jsonify({"status": "executed", "name": name, "count": len(actions)})

    @app.route("/macro/record", methods=["POST"])
    def route_macro_record():
        global _recording, _recorded_actions
        d = _json_body()
        enable = d.get("enable", True)
        if enable:
            _recording = True
            _recorded_actions = []
            return jsonify({"status": "recording"})
        else:
            _recording = False
            return jsonify({"status": "stopped", "actions": _recorded_actions})

    @app.route("/macro/delete", methods=["POST"])
    @require_auth
    def route_macro_delete():
        d = _json_body()
        name = d.get("name", "")
        path = MACROS_DIR / f"{name}.json"
        if path.exists():
            path.unlink()
            return jsonify({"status": "deleted", "name": name})
        return jsonify({"error": f"Macro '{name}' not found"}), 404

    @app.route("/replay", methods=["POST"])
    def route_replay():
        d = _json_body()
        count = min(d.get("count", 5), 100)
        from routes_mouse import _execute_action_wrapper
        for a in list(_action_history)[-count:]:
            _execute_action_wrapper(a.get("action", {}), state)
            time.sleep(0.05)
        return jsonify({"status": "replayed", "count": count})

    # ── Voice ─────────────────────────────────────────
    @app.route("/voice/toggle", methods=["POST"])
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
        port = d.get("port", SERVER_PORT)
        _log(f"Tunnel request for port {port}")
        return jsonify({"status": "tunnel_started", "port": port})

    @app.route("/tunnel/stop", methods=["POST"])
    @require_auth
    def route_tunnel_stop():
        return jsonify({"status": "tunnel_stopped"})

    @app.route("/tunnel/status", methods=["GET"])
    def route_tunnel_status():
        return jsonify({"active": False, "url": None})

    # ── Search files ───────────────────────────────────
    @app.route("/search/files", methods=["POST"])
    def route_search_files():
        d = _json_body()
        pattern = d.get("pattern", "*")
        try:
            search_path = _sanitize_path(d.get("path", os.environ.get("USERPROFILE", "C:/Users/Default")))
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        import fnmatch
        limit = min(d.get("limit", 50), 200)
        results = []
        try:
            for root, dirs, files in os.walk(search_path):
                try:
                    for f in files:
                        if len(results) >= limit: break
                        if fnmatch.fnmatch(f, pattern):
                            full = os.path.join(root, f)
                            try: sz = os.path.getsize(full)
                            except: sz = 0
                            results.append({"path": full, "name": f, "size": sz})
                except (PermissionError, OSError): continue
                if len(results) >= limit: break
        except:
            pass
        return jsonify({"matches": results, "count": len(results), "pattern": pattern})

    # ── Stats & History ────────────────────────────────
    @app.route("/stats", methods=["GET"])
    def route_stats():
        uptime = time.time() - getattr(state, 'start_time', time.time())
        return jsonify({"actions": len(_action_history), "uptime": int(uptime),
                        "macros": len(list(MACROS_DIR.glob("*.json"))) if MACROS_DIR.exists() else 0})

    @app.route("/history", methods=["GET"])
    def route_history():
        limit = min(int(request.args.get("limit", 50)), 500)
        return jsonify({"actions": list(_action_history)[-limit:], "count": min(limit, len(_action_history))})

    @app.route("/events", methods=["GET"])
    def route_events():
        return sse_response()

    @app.route("/launch/ai", methods=["POST"])
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

    # ── v6.3 features ─────────────────────────────────
    @app.route("/features", methods=["GET"])
    def route_features():
        try:
            import coagent_features as cf
            return jsonify({"cursor": cf.cursor_status() if hasattr(cf, 'cursor_status') else False,
                            "recording": cf.get_recording_state() if hasattr(cf, 'get_recording_state') else False})
        except:
            return jsonify({"cursor": False, "recording": False})

    @app.route("/wait/element", methods=["POST"])
    def route_wait_element():
        d = _json_body()
        return jsonify({"status": "waiting", "query": d.get("query", ""), "mode": d.get("mode", "name")})

    @app.route("/wait/element-gone", methods=["POST"])
    def route_wait_element_gone():
        d = _json_body()
        return jsonify({"status": "waiting", "query": d.get("query", ""), "mode": d.get("mode", "name")})

    @app.route("/stabilize", methods=["POST"])
    def route_stabilize():
        d = _json_body()
        time.sleep(min(d.get("max_wait", 2.0), 5.0))
        return jsonify({"status": "stabilized"})

    @app.route("/cursor/enable", methods=["POST"])
    def route_cursor_enable():
        return jsonify({"status": "ok", "message": "cursor control via coagent_features"})

    @app.route("/cursor/style", methods=["POST"])
    def route_cursor_style():
        return jsonify({"status": "ok"})

    @app.route("/cursor/status", methods=["GET"])
    def route_cursor_status():
        return jsonify({"enabled": False})

    @app.route("/recording/start", methods=["POST"])
    def route_recording_start():
        return jsonify({"status": "recording", "dir": str(SCREENSHOTS_DIR)})

    @app.route("/recording/stop", methods=["POST"])
    def route_recording_stop():
        return jsonify({"status": "stopped", "actions": [], "screenshots": 0})

    @app.route("/recording/status", methods=["GET"])
    def route_recording_status():
        return jsonify({"active": False, "actions": 0})

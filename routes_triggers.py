"""Event-driven automation triggers.

Register a trigger of one of three kinds; when the underlying event fires the
trigger's registered webhook URL is POSTed with a JSON payload describing what
happened.

Trigger kinds:
  fs      - filesystem changes on a path (watchdog if installed, poll fallback)
  window  - top-level window opened / closed / renamed (WinEvent via ctypes,
            poll fallback on non-Windows)
  process - a process by name starts or stops (polled via psutil if available,
            else Windows tasklist.exe, else /proc)

Endpoints:
  POST   /triggers/register  - create a trigger
  GET    /triggers/list      - list triggers
  DELETE /triggers/<id>      - remove a trigger
  POST   /triggers/remove    - remove a trigger (JSON body {id})
  POST   /triggers/fire/<id> - manually fire (test dispatch)

Windows-only and third-party imports are wrapped in try/except so this file
imports cleanly under a Linux syntax check.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import jsonify

from shared import _is_private_url, _json_body, _log


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_TRIGGERS = {}   # id -> record
_WATCHERS = {}   # id -> watcher handle (thread / observer)
_STOP_FLAGS = {} # id -> threading.Event

_ALLOWED_KINDS = ("fs", "window", "process", "idle", "lock", "unlock", "hotkey")
_FS_EVENTS = ("created", "modified", "deleted", "moved")
_WIN_EVENTS = ("opened", "closed", "renamed")
_PROC_EVENTS = ("started", "stopped")
_IDLE_EVENTS = ("idle", "active")
_LOCK_EVENTS = ("locked",)
_UNLOCK_EVENTS = ("unlocked",)
_HOTKEY_EVENTS = ("pressed",)

# RegisterHotKey modifier bits (winuser.h)
_MODIFIER_BITS = {
    "alt": 0x0001, "ctrl": 0x0002, "control": 0x0002,
    "shift": 0x0004, "win": 0x0008, "super": 0x0008, "windows": 0x0008,
}

# Common named virtual-key codes (winuser.h)
_NAMED_KEYS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21,
    "pagedown": 0x22, "pgup": 0x21, "pgdn": 0x22, "end": 0x23,
    "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "prtsc": 0x2C, "insert": 0x2D, "ins": 0x2D,
    "delete": 0x2E, "del": 0x2E,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
}

_HOTKEY_ID_COUNTER = 0


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _public(trigger_id, record):
    return {
        "id": trigger_id,
        "kind": record.get("kind"),
        "config": record.get("config"),
        "webhook_url": record.get("webhook_url"),
        "target": record.get("target"),
        "events": list(record.get("events") or []),
        "created_at": record.get("created_at"),
        "last_fired": record.get("last_fired"),
        "fire_count": record.get("fire_count", 0),
        "last_response": record.get("last_response"),
        "status": record.get("status", "unknown"),
        "error": record.get("error"),
    }


def _valid_url(url):
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
    )


# ---------------------------------------------------------------------------
# Webhook dispatch
# ---------------------------------------------------------------------------

def _dispatch(trigger_id, record, event_type, data):
    """POST the trigger event to its webhook and/or execute a local target."""
    timestamp = _now()
    target = record.get("target")
    target_info = None
    if isinstance(target, dict) and target.get("type"):
        target_info = _run_target(trigger_id, target)

    url = record.get("webhook_url")
    info = {"ok": False, "status": None, "error": None}
    if url:
        body = json.dumps(
            {
                "trigger_id": trigger_id,
                "kind": record.get("kind"),
                "event": event_type,
                "data": data,
                "timestamp": timestamp,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        secret = str(record.get("secret") or "")
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Hermes-CoAgent-Trigger/1.0",
            "X-Trigger-Signature": signature,
        }
        try:
            if _is_private_url(url):
                raise ValueError("webhook URL resolves to a blocked private address")

            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with opener.open(req, timeout=15) as resp:
                info.update({"ok": 200 <= resp.status < 300, "status": int(resp.status)})
        except urllib.error.HTTPError as exc:
            info.update({"status": int(getattr(exc, "code", 0) or 0),
                         "error": f"HTTPError: {exc}"})
        except Exception as exc:
            info["error"] = f"{type(exc).__name__}: {exc}"
    else:
        info = target_info or {"ok": False, "status": None,
                               "error": "no webhook_url or target configured"}

    with _LOCK:
        current = _TRIGGERS.get(trigger_id)
        if current:
            current["last_fired"] = timestamp
            current["fire_count"] = int(current.get("fire_count", 0)) + 1
            current["last_response"] = info
            if target_info:
                current["last_target_response"] = target_info


def _run_target(trigger_id, target):
    """Execute a local CoAgent target (recipe/workflow/agent command).

    Returns an info dict describing the outcome; never raises.
    """
    ttype = str(target.get("type") or "").strip().lower()
    if ttype not in ("recipe", "workflow", "command"):
        return {"ok": False, "status": None, "error": f"unsupported target type: {ttype}"}

    try:
        from shared import _self_port, COAGENT_DIR
    except Exception:
        return {"ok": False, "status": None, "error": "shared import failed"}

    token = ""
    try:
        token_file = COAGENT_DIR / ".token"
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
    except Exception:
        token = ""

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    port = _self_port()

    if ttype == "recipe":
        rid = str(target.get("id") or "").strip()
        if not rid:
            return {"ok": False, "status": None, "error": "recipe target requires 'id'"}
        path, payload = "/recipes/run", {"recipe_id": rid}
    elif ttype == "workflow":
        wid = str(target.get("id") or "").strip()
        if not wid:
            return {"ok": False, "status": None, "error": "workflow target requires 'id'"}
        path, payload = f"/workflows/{urllib.parse.quote(wid)}/run", {}
    else:  # command
        prompt = str(target.get("prompt") or target.get("command") or "").strip()
        if not prompt:
            return {"ok": False, "status": None, "error": "command target requires 'prompt'"}
        path, payload = "/agent/exec", {"prompt": prompt}

    info = {"ok": False, "status": None, "error": None}
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            info.update({"ok": 200 <= resp.status < 300, "status": int(resp.status)})
    except urllib.error.HTTPError as exc:
        info.update({"status": int(getattr(exc, "code", 0) or 0),
                     "error": f"HTTPError: {exc}"})
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _fire_async(trigger_id, event_type, data, bypass_filter=False):
    with _LOCK:
        record = _TRIGGERS.get(trigger_id)
        if not record:
            return
        if not bypass_filter:
            events = set(record.get("events") or [])
            if events and event_type not in events:
                return
        # snapshot for thread safety
        snapshot = dict(record)

    def _worker():
        try:
            _dispatch(trigger_id, snapshot, event_type, data)
        except Exception as exc:
            _log(f"[triggers] dispatch failed for {trigger_id}: {exc}")

    threading.Thread(target=_worker, name=f"trigger-{trigger_id}", daemon=True).start()


# ---------------------------------------------------------------------------
# Filesystem watcher
# ---------------------------------------------------------------------------

def _start_fs_watcher(trigger_id, config, stop_event):
    """Start a filesystem watcher for a trigger. Prefer watchdog, else poll."""
    path = str(config.get("path") or "")
    recursive = bool(config.get("recursive", True))
    if not path or not os.path.exists(path):
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "error"
                rec["error"] = f"path does not exist: {path}"
        return None

    # Try watchdog first
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                _fire_async(trigger_id, "created",
                            {"path": event.src_path, "is_directory": event.is_directory})

            def on_modified(self, event):
                _fire_async(trigger_id, "modified",
                            {"path": event.src_path, "is_directory": event.is_directory})

            def on_deleted(self, event):
                _fire_async(trigger_id, "deleted",
                            {"path": event.src_path, "is_directory": event.is_directory})

            def on_moved(self, event):
                _fire_async(trigger_id, "moved",
                            {"src": event.src_path, "dest": getattr(event, "dest_path", None),
                             "is_directory": event.is_directory})

        observer = Observer()
        observer.schedule(Handler(), path, recursive=recursive)
        observer.daemon = True
        observer.start()
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "active"
                rec["backend"] = "watchdog"

        def _stopper():
            stop_event.wait()
            try:
                observer.stop()
                observer.join(timeout=2)
            except Exception:
                pass

        threading.Thread(target=_stopper, name=f"fs-stop-{trigger_id}", daemon=True).start()
        return observer
    except Exception as exc:
        _log(f"[triggers] watchdog unavailable, using poll fallback: {exc}")

    # Poll fallback: scan directory tree by mtime
    interval = max(0.5, float(config.get("poll_interval", 2.0)))

    def _snapshot():
        state = {}
        try:
            if os.path.isfile(path):
                state[path] = os.path.getmtime(path)
            else:
                if recursive:
                    walker = os.walk(path)
                else:
                    walker = [next(os.walk(path), (path, [], []))]
                for root, dirs, files in walker:
                    for name in files:
                        p = os.path.join(root, name)
                        try:
                            state[p] = os.path.getmtime(p)
                        except OSError:
                            pass
        except Exception:
            pass
        return state

    def _loop():
        prev = _snapshot()
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "active"
                rec["backend"] = "poll"
        while not stop_event.is_set():
            time.sleep(interval)
            cur = _snapshot()
            for p in cur.keys() - prev.keys():
                _fire_async(trigger_id, "created", {"path": p, "is_directory": False})
            for p in prev.keys() - cur.keys():
                _fire_async(trigger_id, "deleted", {"path": p, "is_directory": False})
            for p in cur.keys() & prev.keys():
                if cur[p] != prev[p]:
                    _fire_async(trigger_id, "modified", {"path": p, "is_directory": False})
            prev = cur

    t = threading.Thread(target=_loop, name=f"fs-poll-{trigger_id}", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Window open/close watcher
# ---------------------------------------------------------------------------

def _enum_windows_snapshot():
    """Return dict of hwnd -> title for visible top-level windows."""
    out = {}
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _lp):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                out[int(hwnd)] = buf.value
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_proc(cb), 0)
    except Exception as exc:
        _log(f"[triggers] window enum failed: {exc}")
    return out


def _title_matches(title, pattern, use_regex):
    if not pattern:
        return True
    if use_regex:
        try:
            return bool(re.search(pattern, title or ""))
        except re.error:
            return False
    return pattern.lower() in (title or "").lower()


def _start_window_watcher(trigger_id, config, stop_event):
    """Start a window open/close watcher.

    Best-effort WinEvent hook via ctypes; falls back to polling every
    poll_interval seconds. The hook approach requires a message loop, so we
    default to polling which is simpler and portable across desktop sessions.
    """
    pattern = str(config.get("title_pattern") or "")
    use_regex = bool(config.get("regex", False))
    interval = max(0.5, float(config.get("poll_interval", 1.5)))

    # Attempt WinEvent hook first (best-effort; not all envs allow it)
    hook_started = False
    try:
        import ctypes
        from ctypes import wintypes

        EVENT_OBJECT_CREATE = 0x8000
        EVENT_OBJECT_DESTROY = 0x8001
        EVENT_OBJECT_NAMECHANGE = 0x800C
        WINEVENT_OUTOFCONTEXT = 0x0000
        WINEVENT_SKIPOWNPROCESS = 0x0002
        OBJID_WINDOW = 0

        user32 = ctypes.windll.user32
        WinEventProcType = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
            wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
        )

        def _proc(_h, event, hwnd, id_object, _id_child, _thread, _time):
            try:
                if id_object != OBJID_WINDOW:
                    return
                if not hwnd:
                    return
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                if not _title_matches(title, pattern, use_regex):
                    return
                if event == EVENT_OBJECT_CREATE:
                    _fire_async(trigger_id, "opened", {"hwnd": int(hwnd), "title": title})
                elif event == EVENT_OBJECT_DESTROY:
                    _fire_async(trigger_id, "closed", {"hwnd": int(hwnd), "title": title})
                elif event == EVENT_OBJECT_NAMECHANGE:
                    _fire_async(trigger_id, "renamed", {"hwnd": int(hwnd), "title": title})
            except Exception:
                pass

        callback = WinEventProcType(_proc)
        # Keep a strong reference on the record so GC does not collect it.
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec is not None:
                rec.setdefault("_hook_callback", callback)

        hook = user32.SetWinEventHook(
            EVENT_OBJECT_CREATE, EVENT_OBJECT_NAMECHANGE,
            0, callback, 0, 0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
        if hook:
            hook_started = True
            with _LOCK:
                rec = _TRIGGERS.get(trigger_id)
                if rec:
                    rec["status"] = "active"
                    rec["backend"] = "winevent"
                    rec["_hook_handle"] = int(hook)

            def _pump():
                # PeekMessage/DispatchMessage loop to service the hook, exits
                # cleanly when stop_event is set.
                try:
                    msg = wintypes.MSG()
                    PM_REMOVE = 0x0001
                    while not stop_event.is_set():
                        while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, PM_REMOVE):
                            user32.TranslateMessage(ctypes.byref(msg))
                            user32.DispatchMessageW(ctypes.byref(msg))
                        time.sleep(0.05)
                finally:
                    try:
                        user32.UnhookWinEvent(hook)
                    except Exception:
                        pass

            threading.Thread(target=_pump, name=f"win-hook-{trigger_id}", daemon=True).start()
            return callback
    except Exception as exc:
        _log(f"[triggers] SetWinEventHook unavailable, using poll fallback: {exc}")

    if hook_started:
        return None

    def _loop():
        prev = _enum_windows_snapshot()
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "active"
                rec["backend"] = "poll"
        while not stop_event.is_set():
            time.sleep(interval)
            cur = _enum_windows_snapshot()
            for hwnd in cur.keys() - prev.keys():
                title = cur[hwnd]
                if _title_matches(title, pattern, use_regex):
                    _fire_async(trigger_id, "opened", {"hwnd": hwnd, "title": title})
            for hwnd in prev.keys() - cur.keys():
                title = prev[hwnd]
                if _title_matches(title, pattern, use_regex):
                    _fire_async(trigger_id, "closed", {"hwnd": hwnd, "title": title})
            for hwnd in cur.keys() & prev.keys():
                if cur[hwnd] != prev[hwnd] and (_title_matches(cur[hwnd], pattern, use_regex)
                                                or _title_matches(prev[hwnd], pattern, use_regex)):
                    _fire_async(trigger_id, "renamed",
                                {"hwnd": hwnd, "old_title": prev[hwnd], "title": cur[hwnd]})
            prev = cur

    t = threading.Thread(target=_loop, name=f"win-poll-{trigger_id}", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Process start/stop watcher
# ---------------------------------------------------------------------------

def _list_processes():
    """Return dict of pid -> name. Prefer psutil, else Windows tasklist, else /proc."""
    procs = {}
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name"]):
            try:
                info = p.info
                procs[int(info["pid"])] = str(info.get("name") or "")
            except Exception:
                continue
        return procs
    except Exception:
        pass

    # Windows tasklist fallback
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 0:
            import csv
            import io as _io
            reader = csv.reader(_io.StringIO(result.stdout))
            for row in reader:
                if len(row) < 2:
                    continue
                name = row[0].strip('"')
                try:
                    pid = int(row[1].strip('"'))
                except ValueError:
                    continue
                procs[pid] = name
            return procs
    except Exception:
        pass

    # /proc fallback (Linux dev/CI)
    try:
        proc_root = "/proc"
        if os.path.isdir(proc_root):
            for entry in os.listdir(proc_root):
                if not entry.isdigit():
                    continue
                try:
                    with open(os.path.join(proc_root, entry, "comm"), "r") as fh:
                        procs[int(entry)] = fh.read().strip()
                except OSError:
                    continue
    except Exception:
        pass
    return procs


def _proc_matches(name, pattern, use_regex):
    if not pattern:
        return False
    if use_regex:
        try:
            return bool(re.search(pattern, name or ""))
        except re.error:
            return False
    a = (name or "").lower()
    b = pattern.lower()
    return a == b or a == b + ".exe" or b in a


def _start_process_watcher(trigger_id, config, stop_event):
    pattern = str(config.get("name") or config.get("pattern") or "")
    use_regex = bool(config.get("regex", False))
    interval = max(0.5, float(config.get("poll_interval", 2.0)))
    if not pattern:
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "error"
                rec["error"] = "process trigger requires 'name'"
        return None

    def _loop():
        prev = {pid: n for pid, n in _list_processes().items()
                if _proc_matches(n, pattern, use_regex)}
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "active"
                rec["backend"] = "poll"
        while not stop_event.is_set():
            time.sleep(interval)
            cur = {pid: n for pid, n in _list_processes().items()
                   if _proc_matches(n, pattern, use_regex)}
            for pid in cur.keys() - prev.keys():
                _fire_async(trigger_id, "started", {"pid": pid, "name": cur[pid]})
            for pid in prev.keys() - cur.keys():
                _fire_async(trigger_id, "stopped", {"pid": pid, "name": prev[pid]})
            prev = cur

    t = threading.Thread(target=_loop, name=f"proc-{trigger_id}", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Presence watchers (idle / lock / unlock)
# ---------------------------------------------------------------------------

def _get_idle_ms():
    """System idle time in milliseconds via GetLastInputInfo (Windows)."""
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick = ctypes.windll.kernel32.GetTickCount()
            # 32-bit GetTickCount wraps after ~49.7 days uptime; modular
            # subtraction keeps the idle reading correct across the wrap.
            return int(tick - lii.dwTime) & 0xFFFFFFFF
    except Exception:
        pass
    return 0


def _is_workstation_locked():
    """True when the interactive desktop is locked (OpenInputDesktop fails)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # DESKTOP_SWITCHDESKTOP access; OpenInputDesktop returns NULL when the
        # secure/locked desktop owns the input, which is how lock is detected.
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)
        if hdesk:
            user32.CloseDesktop(hdesk)
            return False
        return True
    except Exception:
        return False


def _start_idle_watcher(trigger_id, config, stop_event):
    threshold = max(1.0, float(config.get("threshold_seconds", 300) or 300))
    interval = max(0.5, float(config.get("poll_interval", 1.0) or 1.0))
    fire_active = bool(config.get("fire_on_active", False))

    def _loop():
        was_idle = False
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "active"
                rec["backend"] = "poll"
        while not stop_event.is_set():
            time.sleep(interval)
            idle_ms = _get_idle_ms()
            is_idle = idle_ms >= threshold * 1000
            if is_idle and not was_idle:
                was_idle = True
                _fire_async(trigger_id, "idle",
                            {"idle_ms": idle_ms, "threshold_seconds": threshold})
            elif not is_idle and was_idle:
                was_idle = False
                if fire_active:
                    _fire_async(trigger_id, "active", {"idle_ms": idle_ms})

    t = threading.Thread(target=_loop, name=f"idle-{trigger_id}", daemon=True)
    t.start()
    return t


def _start_lock_watcher(trigger_id, config, stop_event):
    interval = max(0.5, float(config.get("poll_interval", 1.0) or 1.0))

    def _loop():
        was_locked = _is_workstation_locked()
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "active"
                rec["backend"] = "poll"
        while not stop_event.is_set():
            time.sleep(interval)
            locked = _is_workstation_locked()
            if locked and not was_locked:
                _fire_async(trigger_id, "locked", {"locked": True})
            was_locked = locked

    t = threading.Thread(target=_loop, name=f"lock-{trigger_id}", daemon=True)
    t.start()
    return t


def _start_unlock_watcher(trigger_id, config, stop_event):
    interval = max(0.5, float(config.get("poll_interval", 1.0) or 1.0))

    def _loop():
        was_locked = _is_workstation_locked()
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "active"
                rec["backend"] = "poll"
        while not stop_event.is_set():
            time.sleep(interval)
            locked = _is_workstation_locked()
            if (not locked) and was_locked:
                _fire_async(trigger_id, "unlocked", {"locked": False})
            was_locked = locked

    t = threading.Thread(target=_loop, name=f"unlock-{trigger_id}", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Hotkey watcher (system-wide keyboard shortcut)
# ---------------------------------------------------------------------------

def _next_hotkey_id():
    global _HOTKEY_ID_COUNTER
    with _LOCK:
        _HOTKEY_ID_COUNTER = (_HOTKEY_ID_COUNTER + 1) % 0xBFFF
        if _HOTKEY_ID_COUNTER == 0:
            _HOTKEY_ID_COUNTER = 1
        return _HOTKEY_ID_COUNTER


def _parse_hotkey(config):
    """Return (vk, modifier_mask) for a hotkey config, or raise ValueError."""
    key = str(config.get("key") or "").strip().lower()
    if not key:
        raise ValueError("hotkey trigger requires config.key")

    mods = config.get("modifiers") or []
    if isinstance(mods, str):
        mods = [mods]
    modifier_mask = 0
    for m in mods:
        m = str(m).strip().lower()
        if m not in _MODIFIER_BITS:
            raise ValueError(f"unknown modifier: {m}")
        modifier_mask |= _MODIFIER_BITS[m]

    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper()) if key.isalpha() else ord(key)
    elif key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if not 1 <= n <= 24:
            raise ValueError(f"function key out of range: {key}")
        vk = 0x70 + n - 1
    else:
        vk = _NAMED_KEYS.get(key)
    if vk is None:
        raise ValueError(f"unsupported key: {key}")
    return vk, modifier_mask


def _start_hotkey_watcher(trigger_id, config, stop_event):
    try:
        vk, mods = _parse_hotkey(config)
    except ValueError as exc:
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec:
                rec["status"] = "error"
                rec["error"] = str(exc)
        return None

    hotkey_id = _next_hotkey_id()

    def _pump():
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        WM_HOTKEY = 0x0312
        registered = bool(user32.RegisterHotKey(None, hotkey_id, mods, vk))
        with _LOCK:
            rec = _TRIGGERS.get(trigger_id)
            if rec is not None:
                if registered:
                    rec["status"] = "active"
                    rec["backend"] = "registerhotkey"
                    rec["hotkey_id"] = hotkey_id
                else:
                    rec["status"] = "error"
                    rec["error"] = "RegisterHotKey failed — combo may already be in use"

        if not registered:
            return

        msg = wintypes.MSG()
        PM_REMOVE = 0x0001
        try:
            while not stop_event.is_set():
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    if msg.message == WM_HOTKEY and int(msg.wParam) == hotkey_id:
                        _fire_async(trigger_id, "pressed",
                                    {"key": config.get("key"),
                                     "modifiers": config.get("modifiers")})
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.05)
        finally:
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass

    t = threading.Thread(target=_pump, name=f"hotkey-{trigger_id}", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Register / stop
# ---------------------------------------------------------------------------

def _start_watcher(trigger_id, record):
    kind = record.get("kind")
    stop = threading.Event()
    _STOP_FLAGS[trigger_id] = stop
    config = record.get("config") or {}
    if kind == "fs":
        handle = _start_fs_watcher(trigger_id, config, stop)
    elif kind == "window":
        handle = _start_window_watcher(trigger_id, config, stop)
    elif kind == "process":
        handle = _start_process_watcher(trigger_id, config, stop)
    elif kind == "idle":
        handle = _start_idle_watcher(trigger_id, config, stop)
    elif kind == "lock":
        handle = _start_lock_watcher(trigger_id, config, stop)
    elif kind == "unlock":
        handle = _start_unlock_watcher(trigger_id, config, stop)
    elif kind == "hotkey":
        handle = _start_hotkey_watcher(trigger_id, config, stop)
    else:
        stop.set()
        return
    _WATCHERS[trigger_id] = handle


def _stop_watcher(trigger_id):
    stop = _STOP_FLAGS.pop(trigger_id, None)
    if stop:
        stop.set()
    handle = _WATCHERS.pop(trigger_id, None)
    if handle is not None:
        try:
            if hasattr(handle, "stop"):
                handle.stop()
            if hasattr(handle, "join"):
                handle.join(timeout=2)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

_MAX_TRIGGERS = 200


def register_routes(app, state, require_auth):

    @app.route("/triggers/register", methods=["POST"])
    @require_auth
    def route_triggers_register():
        """Register an event-driven trigger.

        Body:
          kind         "fs" | "window" | "process" | "idle" | "lock" | "unlock"
                       | "hotkey"   (required)
          webhook_url  http(s) URL to POST on fire (required unless hotkey target)
          target       {type: recipe|workflow|command, ...} — hotkey only, optional
          events       list of event names to filter (optional; kind-defaults)
          config: kind-specific
            fs:      {path (required), recursive=true, poll_interval=2.0}
            window:  {title_pattern="", regex=false, poll_interval=1.5}
            process: {name (required), regex=false, poll_interval=2.0}
            idle:    {threshold_seconds=300, poll_interval=1.0,
                      fire_on_active=false}
            lock:    {poll_interval=1.0}
            unlock:  {poll_interval=1.0}
            hotkey:  {key="r", modifiers=["ctrl","alt"]}  (key: a-z, 0-9,
                      f1-f24, or named key; modifiers: alt/ctrl/shift/win)
        """
        body = _json_body() or {}
        kind = (body.get("kind") or "").strip().lower()
        if kind not in _ALLOWED_KINDS:
            return jsonify({"error": f"kind must be one of {list(_ALLOWED_KINDS)}"}), 400

        target = body.get("target") if isinstance(body.get("target"), dict) else None
        url = str(body.get("webhook_url") or "").strip()
        if not url and not (kind == "hotkey" and target):
            return jsonify({"error": "webhook_url is required (or target for hotkey)"}), 400
        if url:
            if not _valid_url(url):
                return jsonify({"error": "webhook_url must be an http(s) URL"}), 400
            if _is_private_url(url):
                return jsonify({"error": "webhook_url resolves to a blocked private address"}), 400

        config = body.get("config") if isinstance(body.get("config"), dict) else {}
        events = body.get("events") if isinstance(body.get("events"), list) else []
        events = [str(e).strip() for e in events if str(e).strip()]

        if kind == "fs" and not config.get("path"):
            return jsonify({"error": "fs trigger requires config.path"}), 400
        if kind == "process" and not (config.get("name") or config.get("pattern")):
            return jsonify({"error": "process trigger requires config.name"}), 400
        if kind == "hotkey":
            try:
                _parse_hotkey(config)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        default_events = {
            "fs": _FS_EVENTS, "window": _WIN_EVENTS, "process": _PROC_EVENTS,
            "idle": _IDLE_EVENTS, "lock": _LOCK_EVENTS, "unlock": _UNLOCK_EVENTS,
            "hotkey": _HOTKEY_EVENTS,
        }[kind]
        if not events:
            events = list(default_events)
        else:
            unknown = [e for e in events if e not in default_events]
            if unknown:
                return jsonify({"error": "unsupported event(s)",
                                "unsupported": unknown,
                                "allowed": list(default_events)}), 400

        trigger_id = secrets.token_urlsafe(12)
        record = {
            "kind": kind,
            "config": config,
            "webhook_url": url,
            "target": target,
            "events": events,
            "secret": secrets.token_urlsafe(32),
            "created_at": _now(),
            "last_fired": None,
            "fire_count": 0,
            "last_response": None,
            "status": "starting",
            "error": None,
        }
        with _LOCK:
            if len(_TRIGGERS) >= _MAX_TRIGGERS:
                return jsonify({"error": "trigger limit reached",
                                "max": _MAX_TRIGGERS}), 429
            _TRIGGERS[trigger_id] = record
        try:
            _start_watcher(trigger_id, record)
        except Exception as exc:
            with _LOCK:
                _TRIGGERS.pop(trigger_id, None)
            _stop_watcher(trigger_id)
            return jsonify({"error": "failed to start trigger watcher",
                            "detail": f"{type(exc).__name__}: {exc}"}), 500

        response = _public(trigger_id, record)
        response["secret"] = record["secret"]  # one-time reveal
        return jsonify(response), 201

    @app.route("/triggers/list", methods=["GET"])
    @require_auth
    def route_triggers_list():
        with _LOCK:
            triggers = [_public(tid, rec) for tid, rec in sorted(_TRIGGERS.items())]
        return jsonify({"triggers": triggers, "count": len(triggers)})

    @app.route("/triggers/<trigger_id>", methods=["DELETE"])
    @require_auth
    def route_triggers_delete(trigger_id):
        with _LOCK:
            removed = _TRIGGERS.pop(trigger_id, None)
        if not removed:
            return jsonify({"error": "trigger not found", "id": trigger_id}), 404
        _stop_watcher(trigger_id)
        return jsonify({"status": "deleted", "id": trigger_id})

    @app.route("/triggers/remove", methods=["POST"])
    @require_auth
    def route_triggers_remove():
        body = _json_body() or {}
        trigger_id = str(body.get("id") or "").strip()
        if not trigger_id:
            return jsonify({"error": "id is required"}), 400
        with _LOCK:
            removed = _TRIGGERS.pop(trigger_id, None)
        if not removed:
            return jsonify({"error": "trigger not found", "id": trigger_id}), 404
        _stop_watcher(trigger_id)
        return jsonify({"status": "deleted", "id": trigger_id})

    @app.route("/triggers/fire/<trigger_id>", methods=["POST"])
    @require_auth
    def route_triggers_fire(trigger_id):
        """Manually fire a trigger (test dispatch)."""
        with _LOCK:
            record = _TRIGGERS.get(trigger_id)
        if not record:
            return jsonify({"error": "trigger not found", "id": trigger_id}), 404
        body = _json_body() or {}
        event = str(body.get("event") or "test").strip() or "test"
        data = body.get("data") if isinstance(body.get("data"), (dict, list)) else {"manual": True}
        _fire_async(trigger_id, event, data, bypass_filter=True)
        return jsonify({"status": "queued", "id": trigger_id, "event": event})

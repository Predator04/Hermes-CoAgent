"""Process listing, control, and resource routes."""
import csv, io, json, os, shlex, subprocess, time
from flask import jsonify
from shared import _json_body, _sanitize_path
from routes_governance import get_governor

try:
    import psutil
    HAS_PSUTIL = True
    # Establish a baseline so proc.cpu_percent() returns real values on first call.
    try:
        psutil.cpu_percent(interval=None)
        for _p in psutil.process_iter():
            try:
                _p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
except ImportError:
    psutil = None
    HAS_PSUTIL = False


_WINDOW_TITLES_CACHE = {"ts": 0.0, "value": {}}
_WINDOW_TITLES_TTL = 2.0


def _window_titles_by_pid():
    now = time.monotonic()
    cached = _WINDOW_TITLES_CACHE.get("value") or {}
    if cached and (now - _WINDOW_TITLES_CACHE["ts"]) < _WINDOW_TITLES_TTL:
        return cached
    titles = {}
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title and pid.value not in titles:
                    titles[int(pid.value)] = title
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_proc_type(callback), 0)
    except Exception:
        pass
    _WINDOW_TITLES_CACHE["value"] = titles
    _WINDOW_TITLES_CACHE["ts"] = now
    return titles


def _process_list_psutil(limit=None):
    titles = _window_titles_by_pid()
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info
            memory = info.get("memory_info")
            try:
                cpu = float(proc.cpu_percent(interval=None))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                cpu = 0.0
            rows.append({
                "name": info.get("name") or "",
                "pid": int(info.get("pid") or proc.pid),
                "cpu_percent": cpu,
                "memory_mb": round((memory.rss if memory else 0) / (1024 * 1024), 2),
                "window_title": titles.get(proc.pid, ""),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(key=lambda p: p.get("memory_mb", 0), reverse=True)
    return rows[:limit] if limit else rows


def _process_list_wmic(limit=None):
    try:
        r = subprocess.run(
            ["wmic", "process", "get", "ProcessId,Name,WorkingSetSize", "/format:csv"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            rows = []
            reader = csv.DictReader(io.StringIO(r.stdout.strip()))
            for row in reader:
                if not row.get("ProcessId") or not row.get("Name"):
                    continue
                try:
                    memory_mb = round(int(row.get("WorkingSetSize") or 0) / (1024 * 1024), 2)
                except ValueError:
                    memory_mb = 0.0
                rows.append({
                    "name": row.get("Name") or "",
                    "pid": int(row.get("ProcessId")),
                    "cpu_percent": None,
                    "memory_mb": memory_mb,
                    "window_title": "",
                })
            rows.sort(key=lambda p: p.get("memory_mb", 0), reverse=True)
            return rows[:limit] if limit else rows
    except Exception:
        pass
    return _process_list_powershell(limit)


def _process_list_powershell(limit=None):
    script = (
        "Get-Process | Select-Object Id,ProcessName,WorkingSet64,CPU,MainWindowTitle "
        "| ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    if r.returncode != 0 or not r.stdout.strip():
        return rows
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return rows
    if data is None:
        return rows
    if isinstance(data, dict):
        data = [data]
    for item in data:
        rows.append({
            "name": (item.get("ProcessName") or "") + ".exe",
            "pid": int(item.get("Id") or 0),
            "cpu_percent": None,
            "memory_mb": round(int(item.get("WorkingSet64") or 0) / (1024 * 1024), 2),
            "window_title": item.get("MainWindowTitle") or "",
        })
    rows.sort(key=lambda p: p.get("memory_mb", 0), reverse=True)
    return rows[:limit] if limit else rows


def _confirm_present(data):
    confirm = data.get("confirm")
    return confirm is True or str(confirm).lower() in {"true", "yes", "confirm", "kill"}


def _parse_command(data):
    command = data.get("command")
    if command:
        if isinstance(command, list):
            args = [str(part) for part in command if str(part)]
        else:
            args = shlex.split(str(command), posix=False)
    else:
        exe = data.get("path") or data.get("exe") or data.get("name")
        if not exe:
            raise ValueError("Missing command or path")
        extra = data.get("args", [])
        if isinstance(extra, str):
            extra_args = shlex.split(extra, posix=False)
        elif isinstance(extra, list):
            extra_args = [str(part) for part in extra]
        else:
            raise ValueError("args must be a string or list")
        args = [str(exe)] + extra_args
    if not args:
        raise ValueError("Command is empty")
    return args


def _kill_with_psutil(data):
    targets = []
    current_pid = os.getpid()
    if data.get("pid") is not None:
        targets.append(psutil.Process(int(data["pid"])))
    elif data.get("name"):
        wanted = str(data["name"]).lower()
        # Guard against killing Python processes by name
        wanted_base = wanted[:-4] if wanted.endswith(".exe") else wanted
        if wanted_base in {"python", "pythonw", "python3", "python3w"}:
            raise ValueError("Use pid when killing Python processes")
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                pname_base = pname[:-4] if pname.endswith(".exe") else pname
                if pname == wanted or pname_base == wanted_base:
                    targets.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    else:
        raise ValueError("Missing pid or name")

    killed = []
    for proc in targets:
        if proc.pid == current_pid:
            continue
        try:
            name = proc.name()
            proc.kill()
            killed.append({"pid": proc.pid, "name": name})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return killed


def _kill_fallback(data):
    if data.get("pid") is not None:
        pid = int(data["pid"])
        if pid == os.getpid():
            return []
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip() or "taskkill failed")
        return [{"pid": pid, "name": ""}]
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("Missing pid or name")
    base_name = name.lower()
    if base_name.endswith(".exe"):
        base_name = base_name[:-4]
    if base_name in {"python", "pythonw", "python3", "python3w"}:
        raise ValueError("Use pid when killing Python processes")
    if any(c in name for c in ("*", "?", "/", "\\")):
        raise ValueError("Process name contains invalid characters")
    r = subprocess.run(["taskkill", "/IM", name, "/F"],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "taskkill failed")
    return [{"pid": None, "name": name}]


def _set_priority_psutil(pid, priority):
    priority_key = str(priority).lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "idle": "IDLE_PRIORITY_CLASS",
        "below_normal": "BELOW_NORMAL_PRIORITY_CLASS",
        "normal": "NORMAL_PRIORITY_CLASS",
        "above_normal": "ABOVE_NORMAL_PRIORITY_CLASS",
        "high": "HIGH_PRIORITY_CLASS",
        "realtime": "REALTIME_PRIORITY_CLASS",
    }
    if priority_key not in mapping:
        raise ValueError("Invalid priority")
    priority_class = getattr(psutil, mapping[priority_key], None)
    if priority_class is None:
        raise ValueError("Process priority classes are only supported on Windows")
    proc = psutil.Process(int(pid))
    proc.nice(priority_class)
    return priority_key


def _set_priority_fallback(pid, priority):
    priority_key = str(priority).lower().replace(" ", "").replace("-", "")
    mapping = {
        "idle": "Idle",
        "belownormal": "BelowNormal",
        "normal": "Normal",
        "abovenormal": "AboveNormal",
        "high": "High",
        "realtime": "RealTime",
    }
    if priority_key not in mapping:
        raise ValueError("Invalid priority")
    script = f"$p = Get-Process -Id {int(pid)}; $p.PriorityClass = '{mapping[priority_key]}'"
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "priority update failed")
    return mapping[priority_key]


def _resources_psutil():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    return {
        "psutil": True,
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory": {
            "total_mb": round(mem.total / (1024 * 1024), 2),
            "available_mb": round(mem.available / (1024 * 1024), 2),
            "used_percent": mem.percent,
        },
        "disk": {
            "total_mb": round(disk.total / (1024 * 1024), 2),
            "free_mb": round(disk.free / (1024 * 1024), 2),
            "used_percent": disk.percent,
        },
        "process_count": len(psutil.pids()),
        "boot_time": int(psutil.boot_time()),
        "timestamp": int(time.time()),
    }


def _resources_fallback():
    script = (
        "$os = Get-CimInstance Win32_OperatingSystem; "
        "$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1; "
        "$disk = Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\"; "
        "[pscustomobject]@{"
        "CpuLoad=$cpu.LoadPercentage;"
        "TotalMemKb=$os.TotalVisibleMemorySize;"
        "FreeMemKb=$os.FreePhysicalMemory;"
        "DiskSize=$disk.Size;"
        "DiskFree=$disk.FreeSpace;"
        "ProcessCount=(Get-Process).Count"
        "} | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return {"psutil": False, "error": str(e) or "resource query failed"}
    if r.returncode != 0 or not r.stdout.strip():
        return {"psutil": False, "error": (r.stderr or r.stdout).strip() or "resource query failed"}
    try:
        data = json.loads(r.stdout)
    except ValueError as e:
        return {"psutil": False, "error": f"resource query returned non-JSON: {e}"}
    total_mem = int(data.get("TotalMemKb") or 0) * 1024
    free_mem = int(data.get("FreeMemKb") or 0) * 1024
    disk_size = int(data.get("DiskSize") or 0)
    disk_free = int(data.get("DiskFree") or 0)
    return {
        "psutil": False,
        "cpu_percent": float(data.get("CpuLoad") or 0),
        "memory": {
            "total_mb": round(total_mem / (1024 * 1024), 2),
            "available_mb": round(free_mem / (1024 * 1024), 2),
            "used_percent": round((1 - free_mem / total_mem) * 100, 2) if total_mem else 0,
        },
        "disk": {
            "total_mb": round(disk_size / (1024 * 1024), 2),
            "free_mb": round(disk_free / (1024 * 1024), 2),
            "used_percent": round((1 - disk_free / disk_size) * 100, 2) if disk_size else 0,
        },
        "process_count": int(data.get("ProcessCount") or 0),
        "timestamp": int(time.time()),
    }


def register_routes(app, state, require_auth):
    @app.route("/process/list", methods=["GET"])
    @require_auth
    def route_process_list():
        try:
            from flask import request
            limit = request.args.get("limit")
            limit = min(max(int(limit), 1), 1000) if limit else None
            processes = _process_list_psutil(limit) if HAS_PSUTIL else _process_list_wmic(limit)
            return jsonify({"processes": processes, "count": len(processes), "psutil": HAS_PSUTIL})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/process/kill", methods=["POST"])
    @require_auth
    def route_process_kill():
        data = _json_body()
        if "confirm" not in data or not _confirm_present(data):
            return jsonify({"error": "confirm field required"}), 400
        try:
            killed = _kill_with_psutil(data) if HAS_PSUTIL else _kill_fallback(data)
            return jsonify({"status": "ok", "killed": killed, "count": len(killed)})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/process/start", methods=["POST"])
    @require_auth
    def route_process_start():
        data = _json_body()
        try:
            args = _parse_command(data)
            cwd = _sanitize_path(data["cwd"]) if data.get("cwd") else None
            gov = get_governor()
            app_name = args[0] if args else ""
            allowed, reason = gov.check_app(app_name)
            if not allowed:
                gov.record_block("process_start", app_name, reason)
                return jsonify({"error": reason}), 403
            allowed, reason = gov.check_budget("process_start")
            if not allowed:
                gov.record_block("process_start", app_name, reason)
                return jsonify({"error": reason}), 429
            proc = subprocess.Popen(args, cwd=cwd, shell=False)
            return jsonify({"status": "started", "pid": proc.pid, "command": args})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/process/priority", methods=["POST"])
    @require_auth
    def route_process_priority():
        data = _json_body()
        if data.get("pid") is None:
            return jsonify({"error": "Missing pid"}), 400
        if not data.get("priority"):
            return jsonify({"error": "Missing priority"}), 400
        try:
            priority = (_set_priority_psutil(data["pid"], data["priority"])
                        if HAS_PSUTIL else _set_priority_fallback(data["pid"], data["priority"]))
            return jsonify({"status": "ok", "pid": int(data["pid"]), "priority": priority})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/process/resources", methods=["GET"])
    @require_auth
    def route_process_resources():
        try:
            return jsonify(_resources_psutil() if HAS_PSUTIL else _resources_fallback())
        except Exception as e:
            return jsonify({"error": str(e), "psutil": HAS_PSUTIL}), 500

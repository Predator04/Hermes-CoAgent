"""
Hermes CoAgent v8.0 - Windows system tray icon.

This file is intentionally self-contained so it can run as a Python script or
as a PyInstaller one-file EXE.
"""

from __future__ import annotations

import atexit
import argparse
import ctypes
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


APP_NAME = "Hermes CoAgent"

def _load_version() -> str:
    """Read version from VERSION file (single source of truth)."""
    vf = Path(__file__).resolve().parent / "VERSION"
    if vf.is_file():
        return vf.read_text(encoding="utf-8").strip()
    return "0.0.0"

VERSION = _load_version()
DEFAULT_PORT = 9123
PID_FILE_NAME = "coagent.pid"
HEALTH_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 4
AUTO_RESTART_FAILURES = 2
AUTO_RESTART_COOLDOWN_SECONDS = 90
TOOLTIP_DASH = "\u2014"

pystray = None
Image = None
ImageDraw = None
ImageFont = None
_TRAY_MUTEX_HANDLE = None


def _creationflags() -> int:
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _mutex_suffix() -> str:
    username = os.environ.get("USERNAME") or getpass.getuser() or "user"
    return "".join(ch if ch.isalnum() else "_" for ch in username)


def _acquire_tray_mutex() -> bool:
    global _TRAY_MUTEX_HANDLE
    if not hasattr(ctypes, "WinDLL"):
        return True

    from ctypes import wintypes

    ERROR_ALREADY_EXISTS = 183
    mutex_name = f"Global\\HermesCoAgentTray_{_mutex_suffix()}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, mutex_name)
    last_error = ctypes.get_last_error()
    if not handle:
        return False  # creation failed — treat as instance conflict
    if last_error == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False

    _TRAY_MUTEX_HANDLE = handle
    return True


def _release_tray_mutex() -> None:
    global _TRAY_MUTEX_HANDLE
    handle = _TRAY_MUTEX_HANDLE
    if not handle or not hasattr(ctypes, "WinDLL"):
        return

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    try:
        kernel32.ReleaseMutex(handle)
    except Exception as e:
        print(f"[tray] ReleaseMutex failed: {e}", file=sys.stderr)
    try:
        kernel32.CloseHandle(handle)
    except Exception as e:
        print(f"[tray] CloseHandle failed: {e}", file=sys.stderr)
    _TRAY_MUTEX_HANDLE = None


def _other_tray_process_running() -> bool:
    current_pid = os.getpid()
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$currentPid = {current_pid}
$match = Get-CimInstance Win32_Process | Where-Object {{
    $_.ProcessId -ne $currentPid -and (
        $_.Name -eq 'CoAgentTray.exe' -or
        (($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -match 'tray_icon\\.py')
    )
}} | Select-Object -First 1
if ($match) {{ '1' }}
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=5,
            creationflags=_creationflags(),
            check=False,
        )
        return result.stdout.strip() == "1"
    except Exception:
        return False


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _app_dir() -> Path:
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _run_quiet(cmd: list[str], cwd: Optional[Path] = None, env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=_creationflags(),
        timeout=60,
        check=False,
    )


def _process_alive(process_id: int) -> bool:
    try:
        process_id = int(process_id)
    except (TypeError, ValueError):
        return False
    if process_id <= 0:
        return False

    if hasattr(ctypes, "WinDLL"):
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def _find_python(prefer_windowed: bool = True) -> Optional[str]:
    names = ["pythonw.exe", "python.exe"] if prefer_windowed else ["python.exe", "pythonw.exe"]
    candidates: list[Path] = []

    if not _is_frozen():
        current = Path(sys.executable).resolve()
        if current.exists():
            candidates.append(current.with_name(names[0]))
            candidates.append(current.with_name(names[1]))

    for base in (getattr(sys, "base_prefix", ""), getattr(sys, "prefix", "")):
        if base:
            for name in names:
                candidates.append(Path(base) / name)

    local_app = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    for name in names:
        if local_app:
            candidates.extend([
                Path(local_app) / "Programs" / "Python" / "Python313" / name,
                Path(local_app) / "Programs" / "Python" / "Python312" / name,
                Path(local_app) / "Microsoft" / "WindowsApps" / name,
            ])
        candidates.extend([
            Path(program_files) / "Python313" / name,
            Path(program_files) / "Python312" / name,
            Path(r"C:\Python313") / name,
            Path(r"C:\Python312") / name,
        ])

    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except OSError:
            resolved = str(candidate)
        key = resolved.lower()
        if key in seen:
            continue
        seen.add(key)
        if Path(resolved).exists():
            return resolved
    return None


def _install_dependencies(packages: list[str]) -> None:
    if not packages:
        return
    python = sys.executable if not _is_frozen() else _find_python(prefer_windowed=False)
    if not python:
        raise RuntimeError("Python was not found for dependency bootstrap")
    cmd = [python, "-m", "pip", "install", *packages, "-q"]
    result = _run_quiet(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Dependency install failed: {' '.join(packages)}")


def _ensure_tray_dependencies() -> None:
    global pystray, Image, ImageDraw, ImageFont

    missing: list[str] = []
    try:
        import pystray as pystray_module
    except ImportError:
        pystray_module = None
        missing.append("pystray")

    try:
        from PIL import Image as image_module
        from PIL import ImageDraw as image_draw_module
        from PIL import ImageFont as image_font_module
    except ImportError:
        image_module = image_draw_module = image_font_module = None
        missing.append("pillow")

    if missing:
        _install_dependencies(missing)
        import pystray as pystray_module
        from PIL import Image as image_module
        from PIL import ImageDraw as image_draw_module
        from PIL import ImageFont as image_font_module

    pystray = pystray_module
    Image = image_module
    ImageDraw = image_draw_module
    ImageFont = image_font_module


def _unique_existing(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists():
            out.append(resolved)
    return out


def _coagent_candidates(explicit: Optional[str] = None) -> list[Path]:
    app_dir = _app_dir()
    cwd = Path.cwd()
    desktop = Path.home() / "Desktop"
    raw: list[Path] = []
    if explicit:
        raw.append(Path(explicit))
    env_dir = os.environ.get("HERMES_COAGENT_DIR", "")
    if env_dir:
        raw.append(Path(env_dir))
    raw.extend([
        cwd,
        app_dir,
        app_dir.parent,
        desktop / "Hermes CoAgent",
        app_dir / "Hermes CoAgent",
        app_dir.parent / "Hermes CoAgent",
    ])
    return _unique_existing(raw)


def _find_coagent_dir(explicit: Optional[str] = None) -> Path:
    candidates = _coagent_candidates(explicit)
    for candidate in candidates:
        if (candidate / "hermes_coagent.py").exists():
            return candidate
    return candidates[0] if candidates else Path.cwd()


def _read_token_file(coagent_dir: Path) -> str:
    # Only search paths that are anchored to the running install — do NOT
    # hardcode machine-specific paths like ~/Desktop/Hermes CoAgent/.token,
    # which caused the tray on one machine to pick up a stale token from
    # an unrelated Desktop copy while the server (running from a different
    # install dir) had a freshly generated one. Server and tray must always
    # agree on the same COAGENT_DIR/.token.
    candidates = _unique_existing([
        coagent_dir / ".token",
        _app_dir() / ".token",
        _app_dir().parent / ".token",
        Path.cwd() / ".token",
    ])
    for token_path in candidates:
        try:
            token = token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError:
            continue
    return ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hermes CoAgent tray icon")
    parser.add_argument("positional", nargs="*", help="Optional port and token")
    parser.add_argument("--port", type=int, default=None, help="CoAgent server port")
    parser.add_argument("--token", default="", help="Bearer token")
    parser.add_argument("--coagent-dir", default="", help="Hermes CoAgent project directory")
    parser.add_argument("--no-auto-restart", action="store_true", help="Disable automatic server restart after failed pings")
    return parser.parse_args()


def _coerce_port(value: object, default: int = DEFAULT_PORT) -> int:
    try:
        port = int(str(value))
    except (TypeError, ValueError):
        return default
    if 1 <= port <= 65535:
        return port
    return default


def _config_from_args() -> tuple[int, str, Path, bool]:
    args = _parse_args()
    port = _coerce_port(args.port, DEFAULT_PORT) if args.port is not None else DEFAULT_PORT
    port_was_set = args.port is not None
    token = (args.token or os.environ.get("HERMES_COAGENT_TOKEN", "") or "").strip()

    for raw in args.positional:
        value = str(raw).strip()
        if not value:
            continue
        if not port_was_set and value.isdigit():
            port = _coerce_port(value, DEFAULT_PORT)
            port_was_set = True
            continue
        if not token:
            if value.lower().startswith("bearer "):
                value = value[7:].strip()
            # Backward compatibility: old launchers passed a legacy tray relay
            # port as the second positional argument. Treat small numeric values
            # as relay ports, not bearer tokens.
            if value.isdigit() and 1 <= int(value) <= 65535:
                continue
            token = value

    coagent_dir = _find_coagent_dir(args.coagent_dir or None)
    if not token:
        token = _read_token_file(coagent_dir)
    return port, token, coagent_dir, not args.no_auto_restart


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass
class TrayState:
    port: int
    token: str
    coagent_dir: Path
    auto_restart: bool = True
    tray_started_at: float = field(default_factory=time.monotonic)
    healthy: Optional[bool] = None
    server_uptime: int = 0
    consecutive_failures: int = 0
    last_error: str = ""
    last_restart_at: float = 0.0
    shutting_down: bool = False
    icon: object = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def current_token(self) -> str:
        # Always re-check disk when we don't have a token in memory yet:
        # on a fresh install the server may not have written .token until
        # after tray startup, so the initial config read comes up empty.
        # We also re-read whenever the current in-memory token no longer
        # matches disk (server regenerated it via /auth/token POST).
        disk_token = _read_token_file(self.coagent_dir)
        if disk_token and disk_token != self.token:
            self.token = disk_token
        elif not self.token and disk_token:
            self.token = disk_token
        return self.token

    def log(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
        try:
            log_path = self.coagent_dir / "tray_icon.log"
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass


def _dashboard_url(state: TrayState) -> str:
    base = f"http://localhost:{state.port}/"
    handoff_url = _dashboard_handoff_url(state, base)
    if handoff_url:
        return handoff_url
    return base


def _dashboard_handoff_url(state: TrayState, base: str) -> str:
    token = state.current_token()
    if not token:
        return ""
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{state.port}/auth/dashboard-handoff",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=PING_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        code = str(payload.get("code") or "").strip()
        if not code:
            return ""
        return base + "?handoff=" + urllib.parse.quote(code)
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        state.log(f"dashboard handoff failed: {type(exc).__name__}: {exc}")
        return ""


def _headers(state: TrayState) -> dict[str, str]:
    token = state.current_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _ping(state: TrayState) -> tuple[bool, int, str]:
    url = f"http://127.0.0.1:{state.port}/ping"
    try:
        request = urllib.request.Request(url, headers=_headers(state))
        with urllib.request.urlopen(request, timeout=PING_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
            status = str(payload.get("status", "")).lower()
            uptime = int(payload.get("uptime") or 0)
            if 200 <= getattr(response, "status", 200) < 300 and status == "pong":
                return True, uptime, "pong"
            return False, uptime, f"unexpected ping payload: {payload!r}"
    except Exception as exc:
        return False, 0, f"{type(exc).__name__}: {exc}"


def _read_server_pid(state: TrayState) -> Optional[int]:
    pid_file = state.coagent_dir / PID_FILE_NAME
    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
        return int(raw)
    except (OSError, ValueError):
        return None


def _server_already_running(state: TrayState) -> tuple[bool, str]:
    ok, uptime, error = _ping(state)
    if ok:
        with state.lock:
            state.healthy = True
            state.server_uptime = uptime
            state.consecutive_failures = 0
            state.last_error = ""
        return True, f"already running at port {state.port}"

    pid = _read_server_pid(state)
    if pid and _process_alive(pid):
        return True, f"already running from PID file (PID {pid}); ping check was {error}"

    return False, ""


def _create_icon_image(healthy: Optional[bool]):
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(108, 49, 180, 255))
    draw.ellipse([4, 4, size - 4, size - 4], outline=(185, 140, 255, 255), width=2)

    try:
        font = ImageFont.truetype("arialbd.ttf", 39)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "C", font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2 - bbox[0]
    y = (size - text_height) // 2 - bbox[1] - 1
    draw.text((x, y), "C", fill=(255, 255, 255, 255), font=font)

    dot_color = (34, 197, 94, 255) if healthy else (239, 68, 68, 255)
    if healthy is None:
        dot_color = (245, 158, 11, 255)
    draw.ellipse([43, 43, 61, 61], fill=(0, 0, 0, 190))
    draw.ellipse([46, 46, 59, 59], fill=dot_color)
    return image


def _tooltip(state: TrayState) -> str:
    with state.lock:
        healthy = state.healthy
        server_uptime = state.server_uptime
        tray_uptime = int(time.monotonic() - state.tray_started_at)
        last_error = state.last_error

    if healthy:
        base = f"{APP_NAME} v{VERSION} {TOOLTIP_DASH} Running {_format_duration(server_uptime or tray_uptime)}"
    elif healthy is None:
        base = f"{APP_NAME} v{VERSION} {TOOLTIP_DASH} Checking {_format_duration(tray_uptime)}"
    elif last_error:
        base = f"{APP_NAME} v{VERSION} {TOOLTIP_DASH} Down: {last_error}"
    else:
        base = f"{APP_NAME} v{VERSION} {TOOLTIP_DASH} Down"
    # Append background task status (quick check, don't block on failures)
    try:
        bg_line = _bg_tooltip_line(state)
    except Exception:
        bg_line = ""
    return base + bg_line


def _notify(icon, message: str, title: str = APP_NAME) -> None:
    try:
        icon.notify(message, title)
    except Exception:
        pass


def _refresh_icon(icon, state: TrayState) -> None:
    with state.lock:
        healthy = state.healthy
    try:
        icon.icon = _create_icon_image(healthy)
        icon.title = _tooltip(state)
        icon.update_menu()
    except Exception as exc:
        state.log(f"tray refresh failed: {type(exc).__name__}: {exc}")


def _open_dashboard(icon, item, state: TrayState) -> None:
    webbrowser.open(_dashboard_url(state))


def _open_url(url: str) -> None:
    webbrowser.open(url)


def _check_health(icon, item, state: TrayState) -> None:
    ok, uptime, error = _ping(state)
    with state.lock:
        state.healthy = ok
        state.server_uptime = uptime
        state.consecutive_failures = 0 if ok else state.consecutive_failures + 1
        state.last_error = "" if ok else error
    _refresh_icon(icon, state)
    if ok:
        _notify(icon, f"Running, uptime {_format_duration(uptime)}")
    else:
        _notify(icon, error)


def _kill_server_processes(state: TrayState) -> None:
    escaped_dir = str(state.coagent_dir).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$root = '{escaped_dir}'
$targets = Get-CimInstance Win32_Process | Where-Object {{
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
    ($_.CommandLine -match 'hermes_coagent\\.py') -and
    ($_.CommandLine -like "*$root*")
}}
foreach ($proc in $targets) {{
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}}
"""
    result = _run_quiet([
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ], cwd=state.coagent_dir)
    if result.returncode != 0:
        state.log(f"server process cleanup exited {result.returncode}")


def _server_launch_log_path(state: TrayState) -> Path:
    return state.coagent_dir / "logs" / "server_launch.log"


def _read_launch_log_tail(state: TrayState, max_lines: int = 15) -> str:
    """Return last ``max_lines`` non-empty lines of the launch log, or ""."""
    log_path = _server_launch_log_path(state)
    try:
        if not log_path.is_file():
            return ""
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _start_server_process(state: TrayState, open_existing: bool = False) -> str:
    running, reason = _server_already_running(state)
    if running:
        state.log(f"server start skipped: {reason}")
        if open_existing:
            webbrowser.open(_dashboard_url(state))
        return "already_running"

    server_script = state.coagent_dir / "hermes_coagent.py"
    if not server_script.exists():
        raise FileNotFoundError(f"Missing {server_script}")

    python = _find_python(prefer_windowed=True)
    if not python:
        raise FileNotFoundError("pythonw.exe or python.exe was not found")

    args = [python, str(server_script), "--secure", "--allow-external"]
    if state.port != DEFAULT_PORT:
        args.extend(["--port", str(state.port)])

    env = os.environ.copy()
    token = state.current_token()
    if token:
        env["HERMES_COAGENT_TOKEN"] = token

    # Redirect stdout/stderr to a log file so startup tracebacks aren't lost.
    # The global hidden-window Popen patch in shared.py keeps this windowless.
    log_path = _server_launch_log_path(state)
    log_handle = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "a", encoding="utf-8", errors="replace")
        log_handle.write(
            f"\n===== launch {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n"
        )
        log_handle.flush()
        stdout_target = log_handle
        stderr_target = subprocess.STDOUT
    except Exception as exc:
        state.log(f"server launch log unavailable: {exc}")
        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL

    try:
        subprocess.Popen(
            args,
            cwd=str(state.coagent_dir),
            env=env,
            stdout=stdout_target,
            stderr=stderr_target,
            stdin=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
    finally:
        # Popen dup'd the fd; we can close our handle in this process.
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass
    return "launched"


def _restart_server(state: TrayState, icon=None, automatic: bool = False) -> None:
    with state.lock:
        now = time.monotonic()
        if automatic and now - state.last_restart_at < AUTO_RESTART_COOLDOWN_SECONDS:
            return
        state.last_restart_at = now

    label = "automatic restart" if automatic else "manual restart"
    state.log(f"{label} requested")
    try:
        if automatic:
            healthy, _, _ = _ping(state)
            if healthy:
                state.log(f"{label} skipped: server already healthy")
                return
        _kill_server_processes(state)
        time.sleep(1.5)
        result = _start_server_process(state, open_existing=not automatic)
        state.log(f"{label} server start result: {result}")
        if icon is not None:
            if result == "already_running":
                _notify(icon, "Already running; opening dashboard")
            else:
                _notify(icon, "Restart requested")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        state.log(f"{label} failed: {error}")
        if icon is not None:
            _notify(icon, error)


def _restart_server_menu(icon, item, state: TrayState) -> None:
    threading.Thread(target=_restart_server, args=(state, icon, False), daemon=True).start()


def _start_or_open_server(state: TrayState, icon=None) -> None:
    try:
        result = _start_server_process(state, open_existing=True)
        if icon is not None:
            if result == "already_running":
                _notify(icon, "Already running; opening dashboard")
            else:
                _notify(icon, "Server launch requested")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        state.log(f"start/open server failed: {error}")
        if icon is not None:
            _notify(icon, error)


def _start_or_open_server_menu(icon, item, state: TrayState) -> None:
    threading.Thread(target=_start_or_open_server, args=(state, icon), daemon=True).start()


def _exit(icon, item, state: TrayState) -> None:
    with state.lock:
        state.shutting_down = True
    icon.stop()


# ── Background task tray integration ───────────────────────────────────

def _bg_api(state: TrayState, path: str) -> Optional[dict]:
    """Call a /background/* endpoint on the CoAgent server."""
    try:
        token = state.current_token()
        port = state.port or DEFAULT_PORT
        if not token:
            return None
        url = f"http://127.0.0.1:{port}{path}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _check_background_status(icon, item, state: TrayState) -> None:
    """Show current background task status as a notification."""
    data = _bg_api(state, "/background/status")
    if not data:
        _notify(icon, "CoAgent not reachable")
        return
    if data.get("active"):
        _notify(icon,
            f"🫥 Running: {data.get('task', '?')}\n"
            f"Actions: {data.get('actions', '?')} | Elapsed: {data.get('elapsed_seconds', 0)}s\n"
            f"Last: {data.get('last_action', '?')}"
        )
    else:
        _notify(icon, "🫥 No background task running — co-pilot idle")


def _stop_background(icon, item, state: TrayState) -> None:
    """Emergency stop any running background task."""
    data = _bg_api(state, "/background/stop")
    if data and data.get("success"):
        _notify(icon, "🫥 Background task stopped")
    else:
        _notify(icon, "Failed to stop background task")


def _bg_tooltip_line(state: TrayState) -> str:
    """Get a tooltip line showing background task status."""
    data = _bg_api(state, "/background/status")
    if data and data.get("active"):
        return f"\n🫥 {data.get('task', '?')} ({data.get('actions', '?')} actions)"
    return ""


def _copy_token(icon, item, state: TrayState) -> None:
    try:
        import pyperclip
        token = state.current_token()
        if token:
            pyperclip.copy(token)
            _notify(icon, "Token copied to clipboard")
        else:
            _notify(icon, "No token found")
    except Exception as e:
        _notify(icon, f"Copy failed: {e}")


def _show_token(icon, item, state: TrayState) -> None:
    try:
        token = state.current_token()
        if token:
            preview = token[:8] + "..." + token[-8:]
            ctypes.windll.user32.MessageBoxW(0, token, f"Auth Token ({preview})", 0x40)
        else:
            _notify(icon, "No token found")
    except Exception as e:
        _notify(icon, f"Error: {e}")


def _start_tunnel_menu(icon, item, state: TrayState) -> None:
    threading.Thread(target=_start_tunnel, args=(state, icon), daemon=True).start()


def _start_tunnel(state: TrayState, icon=None) -> None:
    port = state.port or DEFAULT_PORT
    token = state.current_token()

    # First check if server is running
    server_ok = False
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ping", headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                server_ok = True
    except Exception:
        pass

    # If not running, auto-start it
    if not server_ok:
        if icon:
            _notify(icon, "Server not running — starting it first...")
        state.log("tunnel: server not running, auto-starting")
        _kill_server_processes(state)
        time.sleep(1)
        try:
            result = _start_server_process(state, open_existing=False)
        except FileNotFoundError as exc:
            state.log(f"tunnel: auto-start failed: {exc}")
            if icon:
                _notify(icon, f"Server failed to start: {exc}")
            return
        except Exception as exc:
            state.log(f"tunnel: auto-start failed: {type(exc).__name__}: {exc}")
            if icon:
                _notify(icon, f"Server failed to start: {type(exc).__name__}: {exc}")
            return
        state.log(f"tunnel: auto-start result: {result}")

        # Wait for server to come up
        for _ in range(30):
            time.sleep(1)
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/ping", headers={"Authorization": f"Bearer {token}"} if token else {})
                with urllib.request.urlopen(req, timeout=1) as resp:
                    if resp.status == 200:
                        server_ok = True
                        break
            except Exception:
                pass

        if not server_ok:
            tail = _read_launch_log_tail(state)
            if icon:
                if tail:
                    _notify(icon, f"Server failed to start:\n{tail}")
                else:
                    _notify(icon, "Server failed to start — tunnel cannot be created")
            return

    # Start the tunnel
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tunnel/start",
            data=json.dumps({"method": "ngrok", "port": port}).encode(),
            headers={**headers, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if icon:
            url = result.get("url", "")
            if url:
                _notify(icon, f"Tunnel: {url}")
                try:
                    import pyperclip
                    pyperclip.copy(url)
                except Exception:
                    pass
            else:
                _notify(icon, "Tunnel started (check /tunnel/status for URL)")
    except urllib.error.HTTPError as e:
        # Server returned a structured JSON error (e.g. 404 ngrok not found,
        # 502 tunnel exited, 504 timeout) — surface its actual message instead
        # of a generic "Tunnel failed: HTTP Error 404".
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8", errors="replace") or "{}")
            err_msg = body.get("error") or body.get("message") or ""
            recent = body.get("recent_output") or []
            if err_msg:
                detail = err_msg
            if recent:
                tail = recent[-1] if isinstance(recent, list) else str(recent)
                detail = f"{detail} — {tail}" if detail else str(tail)
        except Exception:
            pass
        if icon:
            _notify(icon, f"Tunnel failed ({e.code}): {detail or e.reason}")
    except Exception as e:
        if icon:
            _notify(icon, f"Tunnel failed: {e}")


def _copy_tunnel_url(icon, item, state: TrayState) -> None:
    try:
        import pyperclip
        port = state.port or DEFAULT_PORT
        token = state.current_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(f"http://127.0.0.1:{port}/tunnel/status", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = json.loads(resp.read())
        url = status.get("url", "")
        if url:
            pyperclip.copy(url)
            _notify(icon, "Tunnel URL copied")
        else:
            _notify(icon, "No active tunnel")
    except Exception as e:
        _notify(icon, f"Error: {e}")


def _health_loop(icon, state: TrayState) -> None:
    update_ticks = 0
    UPDATE_CHECK_INTERVAL = 240  # Check for updates every 240 health checks (≈2 hours at 30s intervals)

    while True:
        with state.lock:
            if state.shutting_down:
                return
            previous = state.healthy

        ok, uptime, error = _ping(state)
        should_restart = False
        with state.lock:
            state.healthy = ok
            state.server_uptime = uptime
            if ok:
                state.consecutive_failures = 0
                state.last_error = ""
            else:
                state.consecutive_failures += 1
                state.last_error = error
                should_restart = state.auto_restart and state.consecutive_failures >= AUTO_RESTART_FAILURES

        _refresh_icon(icon, state)
        if previous is True and not ok:
            _notify(icon, "Server health check failed; tray will retry")
            state.log(f"health failed: {error}")
        elif previous is False and ok:
            _notify(icon, f"Server is running, uptime {_format_duration(uptime)}")
            state.log("health recovered")

        if should_restart:
            _restart_server(state, icon=None, automatic=True)

        # Auto-update check (every ~2 hours)
        update_ticks += 1
        if ok and update_ticks >= UPDATE_CHECK_INTERVAL:
            update_ticks = 0
            try:
                _check_and_auto_update(state, icon)
            except Exception:
                pass

        for _ in range(HEALTH_INTERVAL_SECONDS):
            time.sleep(1)
            with state.lock:
                if state.shutting_down:
                    return


# ── Auto-update ───────────────────────────────────────────────────────────

GITHUB_API_RELEASES = "https://api.github.com/repos/Predator04/Hermes-CoAgent/releases/latest"


def _fetch_latest_version(state: TrayState) -> Optional[str]:
    """Get the latest version tag from GitHub releases."""
    try:
        # The local CoAgent auth token must never be sent to third-party hosts.
        # GitHub's public releases API requires no Authorization header.
        headers = {"Accept": "application/vnd.github+json"}
        req = urllib.request.Request(GITHUB_API_RELEASES, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("tag_name", "").lstrip("v")
    except Exception:
        return None


def _version_key(v: str):
    """Parse a version string into a tuple of ints for numeric comparison."""
    nums = []
    for part in re.split(r"[^0-9]+", (v or "").strip()):
        if part:
            nums.append(int(part))
    return tuple(nums)


def _is_newer_version(a: str, b: str) -> bool:
    """Return True if version ``a`` is strictly newer than ``b``."""
    return _version_key(a) > _version_key(b)


def _check_and_auto_update(state: TrayState, icon=None) -> None:
    """Check GitHub for newer version. If found, auto git pull + restart."""
    latest = _fetch_latest_version(state)
    if not latest:
        return

    current = _load_version()
    if not _is_newer_version(latest, current):
        return  # Already up to date (or remote is older/equal)

    state.log(f"auto-update: v{current} → v{latest} available")

    # Try git pull
    coagent_dir = state.coagent_dir or _find_coagent_dir()
    if not coagent_dir or not (Path(coagent_dir) / ".git").exists():
        if icon:
            _notify(icon, f"Update v{latest} available but not a git install — re-run installer")
        return

    if icon:
        _notify(icon, f"Updating v{current} → v{latest}...")

    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=str(coagent_dir),
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_creationflags(),
        )
        if result.returncode != 0:
            state.log(f"auto-update: git pull failed: {result.stderr.strip()}")
            return

        # Check if anything was pulled
        if "Already up to date" in result.stdout:
            return

        state.log(f"auto-update: pulled successfully: {result.stdout.strip()[:200]}")
        new_version = _load_version()
        if new_version != current:
            state.log(f"auto-update: updated v{current} → v{new_version}")
            _notify(icon, f"Updated to v{new_version} — restarting...")
            time.sleep(1)
            _restart_server(state, icon=None, automatic=True)
    except Exception as e:
        state.log(f"auto-update: error: {e}")


def _check_updates_menu(icon, item, state: TrayState) -> None:
    """Manual 'Check for Updates' menu item."""
    current = _load_version()
    latest = _fetch_latest_version(state)
    if not latest:
        _notify(icon, "Could not check for updates")
        return
    if latest == current:
        _notify(icon, f"Up to date (v{current})")
    else:
        _notify(icon, f"Update available: v{current} → v{latest}. Auto-updating...")
        _check_and_auto_update(state, icon)


def main() -> int:
    port, token, coagent_dir, auto_restart = _config_from_args()
    state = TrayState(port=port, token=token, coagent_dir=coagent_dir, auto_restart=auto_restart)

    if _other_tray_process_running() or not _acquire_tray_mutex():
        running, reason = _server_already_running(state)
        state.log(f"tray launch skipped: existing tray detected; server_running={running}; {reason}")
        if running:
            webbrowser.open(_dashboard_url(state))
        return 0

    atexit.register(_release_tray_mutex)
    _ensure_tray_dependencies()
    state.log(f"tray starting on port {port}; coagent_dir={coagent_dir}; frozen={_is_frozen()}")

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", lambda icon, item: _open_dashboard(icon, item, state), default=True),
        pystray.MenuItem("Settings", lambda icon, item: _open_url(f"http://127.0.0.1:{state.port or DEFAULT_PORT}/dashboard2#settings")),
        pystray.MenuItem("Check Health", lambda icon, item: _check_health(icon, item, state)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🫥 Background Status", lambda icon, item: _check_background_status(icon, item, state)),
        pystray.MenuItem("🛑 Stop Background", lambda icon, item: _stop_background(icon, item, state)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Copy Token", lambda icon, item: _copy_token(icon, item, state)),
        pystray.MenuItem("Show Token", lambda icon, item: _show_token(icon, item, state)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start Tunnel (ngrok)", lambda icon, item: _start_tunnel_menu(icon, item, state)),
        pystray.MenuItem("Copy Tunnel URL", lambda icon, item: _copy_tunnel_url(icon, item, state)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Check for Updates", lambda icon, item: _check_updates_menu(icon, item, state)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start/Open Server", lambda icon, item: _start_or_open_server_menu(icon, item, state)),
        pystray.MenuItem("Restart Server", lambda icon, item: _restart_server_menu(icon, item, state)),
        pystray.MenuItem("Exit", lambda icon, item: _exit(icon, item, state)),
    )
    icon = pystray.Icon(
        "hermes_coagent",
        _create_icon_image(None),
        f"{APP_NAME} v{VERSION} {TOOLTIP_DASH} Checking",
        menu=menu,
    )
    state.icon = icon

    threading.Thread(target=_health_loop, args=(icon, state), name="coagent-health", daemon=True).start()
    icon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

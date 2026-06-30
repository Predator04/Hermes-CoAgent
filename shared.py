"""Shared utilities for CoAgent route modules."""

import atexit, getpass, ipaddress, json, os, queue, shlex, socket, subprocess, sys, threading, tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape
import ctypes

from flask import Response, jsonify, request

COAGENT_DIR = Path(__file__).parent.resolve()
VERSION = "8.19"
BUILD = "2026-06-27"
AGENT_NAME = "Hermes CoAgent"
MACROS_DIR = COAGENT_DIR / "macros"
SCREENSHOTS_DIR = COAGENT_DIR / "screenshots"
TUNNEL_LOG = COAGENT_DIR / "tunnel.log"
TRAY_LOG = COAGENT_DIR / "tray_icon.log"
SERVER_LOG = COAGENT_DIR / "coagent_server.log"
PID_FILE = COAGENT_DIR / "coagent.pid"
SERVER_PORT = 9123
TRAY_PORT = 9124
SERVER_DIR = COAGENT_DIR
PYTHON = sys.executable

_BLOCKED_IP_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)
_BLOCKED_IP_ADDRESSES = {ipaddress.ip_address("100.100.100.200")}


def _configured_safe_roots():
    roots = [COAGENT_DIR.resolve()]
    raw_roots = os.environ.get("COAGENT_SAFE_ALLOWED_ROOTS", "").strip()
    if raw_roots:
        for raw_root in raw_roots.split(os.pathsep):
            raw_root = raw_root.strip()
            if not raw_root:
                continue
            try:
                roots.append(Path(raw_root).expanduser().resolve())
            except OSError:
                print(f"[WARN] Ignoring invalid safe root: {raw_root}", file=sys.stderr)
    return roots


SAFE_ALLOWED_ROOTS = _configured_safe_roots()


def _is_private_ip(value):
    try:
        ip = ipaddress.ip_address(str(value))
    except ValueError:
        return True
    if ip in _BLOCKED_IP_ADDRESSES:
        return True
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return True
    return any(ip in network for network in _BLOCKED_IP_NETWORKS)


def _is_private_url(url):
    try:
        parsed = urllib.parse.urlparse(str(url))
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            return True
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except Exception:
        return True
    if not addresses:
        return True
    for address in addresses:
        if _is_private_ip(address[4][0]):
            return True
    return False

DANGEROUS_CMD_CHARS = set(';&|`$(){}[]\n\r')

_sse_clients = []
_sse_lock = threading.Lock()

HOST_IP = "127.0.0.1"
_HOST_IP_LOADED = False
_HOST_IP_LOCK = threading.Lock()

_LOCK_STATE = {
    "pid_file": False,
    "mutex_handle": None,
    "mutex_name": None,
}
_LOCK_STATE_LOCK = threading.RLock()


def _coagent_mutex_name():
    username = os.environ.get("USERNAME") or getpass.getuser() or "user"
    safe_username = "".join(ch if ch.isalnum() else "_" for ch in username)
    return f"Global\\HermesCoAgent_{safe_username}"


def _kernel32():
    if not hasattr(ctypes, "WinDLL"):
        return None
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _is_windows_process_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    kernel32 = _kernel32()
    if kernel32 is None:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _read_pid_file():
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        return int(raw)
    except (OSError, ValueError):
        return None


def is_coagent_server_running(port=SERVER_PORT, timeout=1.5):
    """Return True only when /ping identifies a Hermes CoAgent server."""
    try:
        url = f"http://127.0.0.1:{int(port)}/ping"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        agent = str(payload.get("agent", ""))
        status = str(payload.get("status", "")).lower()
        return status == "pong" and ("CoAgent" in agent or "Hermes" in agent)
    except Exception:
        return False


def _can_bind_port(port, host="127.0.0.1"):
    try:
        probe_host = host or "127.0.0.1"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((probe_host, int(port)))
        return True
    except OSError:
        return False


def _acquire_named_mutex():
    kernel32 = _kernel32()
    if kernel32 is None:
        return True

    from ctypes import wintypes

    ERROR_ALREADY_EXISTS = 183
    mutex_name = _coagent_mutex_name()
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, mutex_name)
    last_error = ctypes.get_last_error()
    if not handle:
        raise OSError(last_error, f"CreateMutexW failed for {mutex_name}")
    if last_error == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        _console("CoAgent already running")
        return False

    _LOCK_STATE["mutex_handle"] = handle
    _LOCK_STATE["mutex_name"] = mutex_name
    return True


def _write_pid_file():
    PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
    _LOCK_STATE["pid_file"] = True


def _prepare_pid_file(port):
    existing_pid = _read_pid_file()
    if existing_pid is None:
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except OSError:
                pass
        return True

    if existing_pid == os.getpid():
        return True

    if _is_windows_process_alive(existing_pid):
        if is_coagent_server_running(port):
            _console(f"CoAgent already running on port {port}")
            return False
        _console(f"[WARN] Replacing stale CoAgent PID file for live nonresponsive PID {existing_pid}")
    else:
        _console(f"[INFO] Removing stale CoAgent PID file for PID {existing_pid}")

    try:
        PID_FILE.unlink()
    except OSError:
        pass
    return True


def release_single_instance_lock():
    with _LOCK_STATE_LOCK:
        if _LOCK_STATE.get("pid_file"):
            current_pid = _read_pid_file()
            if current_pid == os.getpid():
                try:
                    PID_FILE.unlink()
                except OSError:
                    pass
            _LOCK_STATE["pid_file"] = False

        handle = _LOCK_STATE.get("mutex_handle")
        if handle:
            kernel32 = _kernel32()
            if kernel32 is not None:
                from ctypes import wintypes

                kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
                kernel32.ReleaseMutex.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                try:
                    kernel32.ReleaseMutex(handle)
                except Exception:
                    pass
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
            _LOCK_STATE["mutex_handle"] = None
            _LOCK_STATE["mutex_name"] = None


def acquire_single_instance_lock(port=SERVER_PORT, bind_host="127.0.0.1"):
    """Acquire PID, port, and Windows mutex locks for the CoAgent server."""
    with _LOCK_STATE_LOCK:
        if _LOCK_STATE.get("pid_file") or _LOCK_STATE.get("mutex_handle"):
            return True

        if not _acquire_named_mutex():
            return False

        if not _prepare_pid_file(port):
            release_single_instance_lock()
            return False

        if is_coagent_server_running(port):
            _console(f"CoAgent already running on port {port}")
            release_single_instance_lock()
            return False

        if not _can_bind_port(port, bind_host):
            if is_coagent_server_running(port):
                _console(f"CoAgent already running on port {port}")
                release_single_instance_lock()
                return False
            _console(f"[WARN] Port {port} is in use but /ping did not identify CoAgent; continuing")

        _write_pid_file()
        atexit.register(release_single_instance_lock)
        _console(f"[LOCK] Single-instance lock acquired: pid={os.getpid()}, mutex={_LOCK_STATE.get('mutex_name') or 'none'}")
        return True

def get_host_ip():
    """Return the WSL host IP, resolving lazily to avoid import-time PowerShell work."""
    global HOST_IP, _HOST_IP_LOADED
    if _HOST_IP_LOADED:
        return HOST_IP
    with _HOST_IP_LOCK:
        if _HOST_IP_LOADED:
            return HOST_IP
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "(Get-NetIPAddress -InterfaceAlias 'vEthernet (WSL)' -AddressFamily IPv4).IPAddress"],
                capture_output=True, text=True, timeout=2
            )
            if r.stdout.strip():
                HOST_IP = r.stdout.strip().splitlines()[0]
        except Exception:
            pass
        _HOST_IP_LOADED = True
        return HOST_IP


def _console(msg=""):
    text = str(msg) + "\n"
    stream = getattr(sys, "stderr", None)
    if stream is not None:
        try:
            stream.write(text)
            stream.flush()
        except Exception:
            pass
    try:
        if SERVER_LOG.exists() and SERVER_LOG.stat().st_size > 5 * 1024 * 1024:
            oldest = SERVER_LOG.with_suffix(".log.5")
            if oldest.exists():
                oldest.unlink()
            for i in range(4, 0, -1):
                old = SERVER_LOG.with_suffix(f".log.{i}")
                if old.exists():
                    old.rename(SERVER_LOG.with_suffix(f".log.{i+1}"))
            SERVER_LOG.rename(SERVER_LOG.with_suffix(".log.1"))
        with SERVER_LOG.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _log(msg):
    _console(msg)


_JSON_BODY_SENTINEL = object()


def _json_body(data=_JSON_BODY_SENTINEL, status=200):
    if data is not _JSON_BODY_SENTINEL:
        return jsonify(data), status
    try:
        return request.get_json(force=True, silent=True) or {}
    except Exception:
        return {}


def _ensure_interactive_session():
    try:
        from ctypes import wintypes
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return True
    except Exception:
        _console("WARNING: No desktop access (cursor=(0,0)). Launch from Windows desktop.")
        return False


def _sanitize_path(requested_path):
    if not requested_path:
        raise ValueError("Path is required")
    resolved = Path(requested_path).expanduser().resolve()
    for root in SAFE_ALLOWED_ROOTS:
        try:
            common = os.path.commonpath([os.path.normcase(str(resolved)), os.path.normcase(str(root))])
        except ValueError:
            continue
        if common == os.path.normcase(str(root)):
            return str(resolved)
    raise ValueError(f"Path traversal blocked: {requested_path} -> {resolved}")


def _sanitize_cmd(cmd_str):
    for d in DANGEROUS_CMD_CHARS:
        if d in cmd_str:
            raise ValueError(f"Command blocked: contains character {repr(d)}")
    args = shlex.split(cmd_str, posix=False)
    if not args:
        raise ValueError("Command is empty")
    return args


def _missing_field(payload_or_name, field=None):
    if field is not None:
        payload = payload_or_name if isinstance(payload_or_name, dict) else {}
        if field in payload and payload.get(field) not in (None, ""):
            return None
        name = field
    else:
        name = payload_or_name
    return jsonify({"error": f"Missing required field: {name}"}), 400


def _result_response(result, default_error_status=400):
    if isinstance(result, tuple) and len(result) == 2:
        payload, status = result
        return jsonify(payload), status
    status = default_error_status if isinstance(result, dict) and result.get("error") else 200
    return jsonify(result), status


def _wrap_registered_blueprint_routes(app, blueprint_name, require_auth):
    """Apply auth to already-registered Flask blueprint view functions."""
    endpoint_prefix = f"{blueprint_name}."
    for endpoint, view_func in list(app.view_functions.items()):
        if not endpoint.startswith(endpoint_prefix):
            continue
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        app.view_functions[endpoint] = wrapped


def _interactive_task_xml(command, arguments, author="CoAgent", execution_limit="PT0S", working_dir=None):
    command_xml = _xml_escape(str(command))
    arguments_xml = _xml_escape(str(arguments))
    author_xml = _xml_escape(str(author))
    execution_limit_xml = _xml_escape(str(execution_limit))
    working_dir_xml = (
        f"      <WorkingDirectory>{_xml_escape(str(working_dir))}</WorkingDirectory>\n"
        if working_dir else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        f'  <RegistrationInfo><Author>{author_xml}</Author></RegistrationInfo>\n'
        '  <Triggers />\n'
        '  <Principals>\n'
        '    <Principal id="Author">\n'
        '      <RunLevel>HighestAvailable</RunLevel>\n'
        '    </Principal>\n'
        '  </Principals>\n'
        '  <Settings>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        f'    <ExecutionTimeLimit>{execution_limit_xml}</ExecutionTimeLimit>\n'
        '    <AllowStartOnRemoteDesktops>true</AllowStartOnRemoteDesktops>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '  </Settings>\n'
        '  <Actions Context="Author">\n'
        '    <InteractiveContext>Author</InteractiveContext>\n'
        '    <Exec>\n'
        f'      <Command>{command_xml}</Command>\n'
        f'      <Arguments>{arguments_xml}</Arguments>\n'
        f'{working_dir_xml}'
        '    </Exec>\n'
        '  </Actions>\n'
        '</Task>'
    )


def sse_broadcast(event_type, data):
    msg = sse_pack(event_type, data)
    with _sse_lock:
        clients = list(_sse_clients)
    dead = []
    for q in clients:
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    if dead:
        with _sse_lock:
            for q in dead:
                if q in _sse_clients:
                    _sse_clients.remove(q)


def sse_response():
    def gen():
        q = queue.Queue()
        with _sse_lock:
            _sse_clients.append(q)
        try:
            yield sse_pack("status", {"running": True})
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)
    return sse_stream_response(gen())


def _json_frame(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _sse_response(events):
    return sse_stream_response(events)


def sse_pack(event_type, data=None, event_id=None, retry=None):
    """Format one Server-Sent Events frame."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event_type:
        lines.append(f"event: {event_type}")
    if retry is not None:
        lines.append(f"retry: {int(retry)}")
    payload = json.dumps(data if data is not None else {}, ensure_ascii=False)
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def sse_stream_response(generator, headers=None):
    stream_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if headers:
        stream_headers.update(headers)
    return Response(generator, mimetype="text/event-stream", headers=stream_headers)

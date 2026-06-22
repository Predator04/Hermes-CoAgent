"""Shared utilities for CoAgent route modules."""

import json, os, queue, shlex, subprocess, sys, threading
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape
import ctypes

from flask import Response, jsonify, request

COAGENT_DIR = Path(__file__).parent.resolve()
VERSION = "7.8"
BUILD = "2026-06-22"
AGENT_NAME = "Hermes CoAgent"
MACROS_DIR = COAGENT_DIR / "macros"
SCREENSHOTS_DIR = COAGENT_DIR / "screenshots"
TUNNEL_LOG = COAGENT_DIR / "tunnel.log"
TRAY_LOG = COAGENT_DIR / "tray_icon.log"
SERVER_LOG = COAGENT_DIR / "coagent_server.log"
SERVER_PORT = 9123
TRAY_PORT = 9124
SERVER_DIR = COAGENT_DIR
PYTHON = sys.executable

SAFE_ALLOWED_ROOTS = [
    Path(os.environ.get("USERPROFILE", "C:/Users/Default")).resolve(),
    Path(os.environ.get("TEMP", "C:/Windows/Temp")).resolve(),
    COAGENT_DIR.resolve(),
]

DANGEROUS_CMD_CHARS = set(';&|`$(){}[]\n\r')

_sse_clients = []
_sse_lock = threading.Lock()

HOST_IP = "172.21.192.1"
_HOST_IP_LOADED = False
_HOST_IP_LOCK = threading.Lock()

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
        except:
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
    except:
        pass


def _log(msg):
    _console(msg)


def _json_body():
    try:
        return request.get_json(force=True, silent=True) or {}
    except:
        return {}


def _ensure_interactive_session():
    try:
        from ctypes import wintypes
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return True
    except:
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


def _missing_field(name):
    return jsonify({"error": f"Missing required field: {name}"}), 400


def _result_response(result, default_error_status=400):
    if isinstance(result, tuple) and len(result) == 2:
        payload, status = result
        return jsonify(payload), status
    status = default_error_status if isinstance(result, dict) and result.get("error") else 200
    return jsonify(result), status


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
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


def sse_response():
    def gen():
        q = queue.Queue()
        with _sse_lock:
            _sse_clients.append(q)
        try:
            yield f"event: status\ndata: {json.dumps({'running': True})}\n\n"
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
    return Response(gen(), mimetype="text/event-stream")

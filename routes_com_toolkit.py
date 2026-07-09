"""API/COM Toolkit — Native OS access bypassing the UI entirely.

Gives the LLM direct access to PowerShell, WMI, COM objects, and the Windows Registry.
For any task that doesn't need a visible UI (changing wallpaper, querying processes, 
reading registry, configuring Windows), this is 100x faster than clicking around.
"""
import base64
import io
import json
import logging
import re
import subprocess
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

_LOGGER = logging.getLogger(__name__)
com_bp = Blueprint("com_toolkit", __name__)

_COM_STATE = {
    "total_calls": 0,
    "powershell_calls": 0,
    "wmi_calls": 0,
    "registry_calls": 0,
    "com_calls": 0,
    "last_error": None,
}
_COM_LOCK = threading.Lock()


def _debug_failure(context, exc):
    _LOGGER.debug("com_toolkit %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _ps_execute(script, timeout=30):
    """Execute a PowerShell script and return stdout + stderr."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()[:500],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"PowerShell timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _registry_read(key, value_name=""):
    """Read a Windows registry value via PowerShell."""
    script = f"""
    try {{
        $val = Get-ItemProperty -Path "{key}" -Name "{value_name}" -ErrorAction Stop
        $val | ConvertTo-Json -Compress
    }} catch {{
        Write-Error $_.Exception.Message
    }}
    """
    result = _ps_execute(script)
    if result["ok"] and result["stdout"]:
        try:
            return {"ok": True, "data": json.loads(result["stdout"])}
        except (json.JSONDecodeError, ValueError):
            return {"ok": True, "data": {"raw": result["stdout"]}}
    return result


def _wmi_query(query, namespace="root/cimv2"):
    """Execute a WMI query and return results."""
    script = f"""
    $results = Get-CimInstance -Query "{query}" -Namespace "{namespace}" -ErrorAction Stop
    $results | ConvertTo-Json -Depth 3 -Compress
    """
    result = _ps_execute(script)
    if result["ok"] and result["stdout"]:
        try:
            data = json.loads(result["stdout"])
            return {"ok": True, "count": len(data) if isinstance(data, list) else 1, "data": data}
        except (json.JSONDecodeError, ValueError):
            return {"ok": True, "data": {"raw": result["stdout"]}}
    return result


def _com_create_object(prog_id, method=None, args=None):
    """Create a COM object and optionally call a method."""
    args_json = json.dumps(args or [])
    method_call = f".{method}({','.join(args or [])})" if method else ""
    script = f"""
    try {{
        $obj = New-Object -ComObject "{prog_id}" -ErrorAction Stop
        $result = $obj{method_call}
        if ($result -ne $null) {{
            $result | ConvertTo-Json -Depth 3 -Compress
        }} else {{
            "null"
        }}
    }} catch {{
        Write-Error $_.Exception.Message
    }}
    """
    result = _ps_execute(script)
    if result["ok"] and result["stdout"] and result["stdout"] != "null":
        try:
            return {"ok": True, "data": json.loads(result["stdout"])}
        except (json.JSONDecodeError, ValueError):
            return {"ok": True, "data": {"raw": result["stdout"]}}
    return result


@com_bp.route("/com/powershell", methods=["POST"])
def _com_powershell():
    body = request.get_json(force=True, silent=True) or {}
    script = body.get("script", "")
    timeout = int(body.get("timeout", 30))
    if not script:
        return jsonify({"ok": False, "error": "missing 'script'"}), 400

    result = _ps_execute(script, timeout=timeout)
    with _COM_LOCK:
        _COM_STATE["total_calls"] += 1
        _COM_STATE["powershell_calls"] += 1
        if not result["ok"]:
            _COM_STATE["last_error"] = result.get("stderr", result.get("error", ""))
    return jsonify({"ok": result["ok"], "result": result})


@com_bp.route("/com/wmi", methods=["POST"])
def _com_wmi():
    body = request.get_json(force=True, silent=True) or {}
    query = body.get("query", "")
    namespace = body.get("namespace", "root/cimv2")
    if not query:
        return jsonify({"ok": False, "error": "missing 'query'"}), 400

    result = _wmi_query(query, namespace)
    with _COM_LOCK:
        _COM_STATE["total_calls"] += 1
        _COM_STATE["wmi_calls"] += 1
        if not result["ok"]:
            _COM_STATE["last_error"] = result.get("error", "")
    return jsonify({"ok": result["ok"], "query": query, "result": result})


@com_bp.route("/com/registry", methods=["POST"])
def _com_registry():
    body = request.get_json(force=True, silent=True) or {}
    key = body.get("key", "")
    value_name = body.get("value_name", "")
    if not key:
        return jsonify({"ok": False, "error": "missing 'key'"}), 400

    result = _registry_read(key, value_name)
    with _COM_LOCK:
        _COM_STATE["total_calls"] += 1
        _COM_STATE["registry_calls"] += 1
    return jsonify({"ok": result["ok"], "key": key, "result": result})


@com_bp.route("/com/com-object", methods=["POST"])
def _com_com_object():
    body = request.get_json(force=True, silent=True) or {}
    prog_id = body.get("prog_id", "")
    method = body.get("method")
    args = body.get("args", [])
    if not prog_id:
        return jsonify({"ok": False, "error": "missing 'prog_id'"}), 400

    result = _com_create_object(prog_id, method, args)
    with _COM_LOCK:
        _COM_STATE["total_calls"] += 1
        _COM_STATE["com_calls"] += 1
    return jsonify({"ok": result["ok"], "prog_id": prog_id, "method": method, "result": result})


@com_bp.route("/com/system", methods=["POST"])
def _com_system():
    """High-level system actions: wallpaper, volume, power, etc."""
    body = request.get_json(force=True, silent=True) or {}
    action = body.get("action", "")
    value = body.get("value")

    if action == "wallpaper":
        script = f"""
        Add-Type -TypeDefinition @"
        using System.Runtime.InteropServices;
        public class Wallpaper {{
            [DllImport("user32.dll", CharSet=CharSet.Auto)]
            public static extern int SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni);
        }}
"@
        [Wallpaper]::SystemParametersInfo(20, 0, "{value}", 2)
        """
        result = _ps_execute(script)

    elif action == "volume":
        level = min(100, max(0, int(value or 50)))
        script = f"""
        $obj = New-Object -ComObject WScript.Shell
        for($i=0; $i -lt {level}; $i+=2){{$obj.SendKeys([char]175)}}
        """
        result = _ps_execute(script)

    elif action == "processes":
        result = _wmi_query("SELECT Name, ProcessId, WorkingSetSize, CPU FROM Win32_PerfFormattedData_PerfProc_Process WHERE Name != '_Total'")

    elif action == "services":
        result = _wmi_query("SELECT Name, DisplayName, State, StartMode FROM Win32_Service WHERE State='Running'")

    elif action == "disks":
        result = _wmi_query("SELECT DeviceID, Size, FreeSpace, DriveType FROM Win32_LogicalDisk")

    elif action == "network":
        result = _wmi_query("SELECT Description, MACAddress, IPAddress, DHCPEnabled, Speed FROM Win32_NetworkAdapter WHERE NetEnabled=True")

    else:
        return jsonify({"ok": False, "error": f"unknown action '{action}'"}), 400

    with _COM_LOCK:
        _COM_STATE["total_calls"] += 1
    return jsonify({"ok": result["ok"], "action": action, "result": result})


@com_bp.route("/com/status", methods=["GET"])
def _com_status():
    with _COM_LOCK:
        return jsonify({"ok": True, **_COM_STATE})


def register_routes(app, state, require_auth):
    app.register_blueprint(com_bp)
    _LOGGER.info("COM Toolkit routes registered")

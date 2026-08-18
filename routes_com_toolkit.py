"""API/COM Toolkit — Native OS access bypassing the UI entirely.

Gives the LLM direct access to PowerShell, WMI, COM objects, and the Windows Registry.
For any task that doesn't need a visible UI (changing wallpaper, querying processes, 
reading registry, configuring Windows), this is 100x faster than clicking around.
"""
import json
import logging
import re
import subprocess
import threading

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

# PowerShell-safe string escaping: prevent injection via double-quote/backtick/dollar
def _ps_escape(value):
    """Escape a string for safe interpolation into a PowerShell double-quoted string."""
    if not isinstance(value, str):
        value = str(value)
    # Escape backtick first (PowerShell escape char), then $ (variable expansion), then "
    return value.replace("`", "``").replace("$", "`$").replace('"', '`"')

# Regex for values that must be identifiers/paths (no injection chars allowed at all)
_SAFE_PATH_RE = r"^[A-Za-z0-9_\\:\\.\\- ]+$"

# COM method names must be plain PowerShell identifiers — anything else could
# be injected as arbitrary code via string interpolation.
_METHOD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def _ps_validate(value, label="value"):
    """Validate a value is safe for PowerShell interpolation. Raises ValueError if unsafe."""
    import re
    if not re.match(_SAFE_PATH_RE, str(value)):
        raise ValueError(f"Unsafe character in {label}: {repr(value)}")
    return str(value)


def _debug_failure(context, exc):
    _LOGGER.debug("com_toolkit %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _ps_execute(script, timeout=30):
    """Execute a PowerShell script and return stdout + stderr."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout, errors="replace",
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
    safe_key = _ps_escape(key)
    safe_val = _ps_escape(value_name)
    script = f"""
    try {{
        $val = Get-ItemProperty -Path "{safe_key}" -Name "{safe_val}" -ErrorAction Stop
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
    safe_query = _ps_escape(query)
    safe_ns = _ps_escape(namespace)
    script = f"""
    $results = Get-CimInstance -Query "{safe_query}" -Namespace "{safe_ns}" -ErrorAction Stop
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
    if method is not None and (not isinstance(method, str) or not _METHOD_RE.match(method)):
        return {"ok": False, "error": "method must be a valid identifier"}
    if not isinstance(prog_id, str) or not prog_id:
        return {"ok": False, "error": "prog_id must be a non-empty string"}
    safe_prog_id = _ps_escape(prog_id)
    # Escape each arg and wrap in double quotes so args are always passed as
    # string literals — never evaluated as PowerShell expressions.
    if not isinstance(args, (list, tuple)):
        args = [] if args is None else [args]
    safe_args = [f'"{_ps_escape(str(a))}"' for a in args]
    method_call = f".{method}({','.join(safe_args)})" if method else ""
    script = f"""
    try {{
        $obj = New-Object -ComObject "{safe_prog_id}" -ErrorAction Stop
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
    try:
        timeout = max(1, min(int(body.get("timeout", 30)), 120))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "timeout must be a number 1-120"}), 400
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
        if not value:
            return jsonify({"ok": False, "error": "wallpaper requires 'value' (image path)"}), 400
        safe_value = _ps_escape(str(value))
        script = f"""
        Add-Type -TypeDefinition @"
        using System.Runtime.InteropServices;
        public class Wallpaper {{
            [DllImport("user32.dll", CharSet=CharSet.Auto)]
            public static extern int SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni);
        }}
"@
        [Wallpaper]::SystemParametersInfo(20, 0, "{safe_value}", 2)
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
    from shared import _wrap_registered_blueprint_routes
    _wrap_registered_blueprint_routes(app, com_bp.name, require_auth)
    _LOGGER.info("COM Toolkit routes registered")

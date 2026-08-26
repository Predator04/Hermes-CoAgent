"""Environment variable management routes -- persistent User/System vars with a
proper WM_SETTINGCHANGE broadcast.

Gives agents a first-class, one-call way to self-configure: persist API keys,
add a directory to PATH, set proxy vars, or flip feature flags -- and have the
change propagate to already-running processes without a reboot.

    GET  /env/list          -- enumerate user + system env vars (scope-attributed)
    GET  /env/get?name=KEY  -- read a variable (process, then user, then system)
    POST /env/set           -- {name, value, scope: "user"|"system"}
    POST /env/delete        -- {name, scope}
    POST /env/broadcast     -- re-broadcast WM_SETTINGCHANGE to refresh the session

Uses [Environment]::SetEnvironmentVariable rather than setx.exe: it persists to
the registry, does NOT truncate values over 1024 chars, and (for User/Machine
targets) broadcasts WM_SETTINGCHANGE automatically. System-scope writes require
elevation; CoAgent runs elevated.
"""

import json
import os
import subprocess

from flask import jsonify, request

from shared import _json_body, _log


_SCOPE_MAP = {"user": "User", "system": "Machine"}


def _ps(script, timeout=60, env=None):
    """Run a PowerShell command and return (stdout, stderr, returncode)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout, env=full_env,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "PowerShell command timed out", -1
    except FileNotFoundError:
        return "", "powershell.exe not found (not on Windows?)", -1


def _ps_json(script, timeout=60, env=None):
    """Run PowerShell, parse JSON stdout; fall back to a raw-text dict."""
    stdout, stderr, code = _ps(script, timeout=timeout, env=env)
    if stdout:
        try:
            parsed = json.loads(stdout)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed, stderr, code
    return {"raw": stdout or stderr}, stderr, code


_LIST_SCRIPT = r"""
$u = [Environment]::GetEnvironmentVariables('User')
$m = [Environment]::GetEnvironmentVariables('Machine')
$rows = @()
foreach ($k in $u.Keys) { $rows += [ordered]@{ scope='user'; name=[string]$k; value=[string]$u[$k] } }
foreach ($k in $m.Keys) { $rows += [ordered]@{ scope='system'; name=[string]$k; value=[string]$m[$k] } }
[ordered]@{ count=$rows.Count; variables=$rows } | ConvertTo-Json -Compress
"""

_GET_SCRIPT = r"""
$name = $env:COAGENT_ENV_NAME
$scope = 'process'
$v = [Environment]::GetEnvironmentVariable($name, 'Process')
if ($null -eq $v) { $v = [Environment]::GetEnvironmentVariable($name, 'User'); $scope = 'user' }
if ($null -eq $v) { $v = [Environment]::GetEnvironmentVariable($name, 'Machine'); $scope = 'system' }
[ordered]@{ name=$name; value=$v; scope=$scope; exists=($null -ne $v) } | ConvertTo-Json -Compress
"""

_SET_SCRIPT = r"""
$name = $env:COAGENT_ENV_NAME
$value = $env:COAGENT_ENV_VALUE
$scope = $env:COAGENT_ENV_SCOPE
[Environment]::SetEnvironmentVariable($name, $value, $scope)
[ordered]@{ name=$name; scope=$scope.ToLower(); set=$true } | ConvertTo-Json -Compress
"""

_DELETE_SCRIPT = r"""
$name = $env:COAGENT_ENV_NAME
$scope = $env:COAGENT_ENV_SCOPE
[Environment]::SetEnvironmentVariable($name, $null, $scope)
[ordered]@{ name=$name; scope=$scope.ToLower(); deleted=$true } | ConvertTo-Json -Compress
"""

_BROADCAST_SCRIPT = r"""
Add-Type -Namespace CoAgEnv -Name Native -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
$HWND_BROADCAST = [IntPtr]0xffff
$WM_SETTINGCHANGE = 0x1A
$r = [UIntPtr]::Zero
[CoAgEnv.Native]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$r) | Out-Null
[ordered]@{ broadcast=$true; message='WM_SETTINGCHANGE' } | ConvertTo-Json -Compress
"""


def register_routes(app, state, require_auth):
    @app.route("/env/list", methods=["GET"])
    @require_auth
    def route_env_list():
        result, stderr, code = _ps_json(_LIST_SCRIPT, timeout=30)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/env/get", methods=["GET"])
    @require_auth
    def route_env_get():
        name = (request.args.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        result, stderr, code = _ps_json(_GET_SCRIPT, timeout=30, env={"COAGENT_ENV_NAME": name})
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/env/set", methods=["POST"])
    @require_auth
    def route_env_set():
        data = _json_body() or {}
        name = str(data.get("name") or "").strip()
        scope = str(data.get("scope") or "user").lower()
        if not name:
            return jsonify({"error": "name is required"}), 400
        if "=" in name or "\x00" in name:
            return jsonify({"error": "invalid environment variable name"}), 400
        if scope not in _SCOPE_MAP:
            return jsonify({"error": "scope must be 'user' or 'system'"}), 400
        value = "" if data.get("value") is None else str(data.get("value"))
        result, stderr, code = _ps_json(_SET_SCRIPT, timeout=30, env={
            "COAGENT_ENV_NAME": name,
            "COAGENT_ENV_VALUE": value,
            "COAGENT_ENV_SCOPE": _SCOPE_MAP[scope],
        })
        if code != 0 and "raw" in result:
            hint = " (system scope requires elevation)" if scope == "system" else ""
            return jsonify({"error": (stderr or result["raw"]) + hint}), 500
        _log(f"env: set {scope} {name}")
        return jsonify(result)

    @app.route("/env/delete", methods=["POST"])
    @require_auth
    def route_env_delete():
        data = _json_body() or {}
        name = str(data.get("name") or "").strip()
        scope = str(data.get("scope") or "user").lower()
        if not name:
            return jsonify({"error": "name is required"}), 400
        if scope not in _SCOPE_MAP:
            return jsonify({"error": "scope must be 'user' or 'system'"}), 400
        result, stderr, code = _ps_json(_DELETE_SCRIPT, timeout=30, env={
            "COAGENT_ENV_NAME": name,
            "COAGENT_ENV_SCOPE": _SCOPE_MAP[scope],
        })
        if code != 0 and "raw" in result:
            hint = " (system scope requires elevation)" if scope == "system" else ""
            return jsonify({"error": (stderr or result["raw"]) + hint}), 500
        _log(f"env: delete {scope} {name}")
        return jsonify(result)

    @app.route("/env/broadcast", methods=["POST"])
    @require_auth
    def route_env_broadcast():
        result, stderr, code = _ps_json(_BROADCAST_SCRIPT, timeout=30)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

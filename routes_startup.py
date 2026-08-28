"""Startup program management routes -- enumerate and control auto-start
entries across Startup folders and Run/RunOnce registry keys.

    GET  /startup/list       -- all auto-start entries, source-attributed with
                                enabled/disabled state (Task Manager view)
    POST /startup/add        -- {source, name, command, arguments?}
    POST /startup/remove     -- {source, name}
    POST /startup/disable    -- {source, name}
    POST /startup/enable     -- {source, name}

Sources:
    run_hkcu      -- HKCU Run key (per-user)
    run_hklm      -- HKLM Run key (all-users)
    startup_user  -- per-user Startup folder (Start Menu\\Programs\\Startup)
    startup_all   -- all-user Startup folder (ProgramData)

Disable/enable mirrors Task Manager: it writes the StartupApproved registry
flag (byte0 = 0x02 enabled / 0x03 disabled) so the entry stays installed but is
skipped at logon. Remove deletes the Run value or the Startup-folder file.
"""

import json
import os
import subprocess

from flask import jsonify

from shared import _json_body, _log


# Registry path + StartupApproved path for each supported source.
_SOURCES = {
    "run_hkcu": {
        "kind": "run",
        "reg": r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
        "approve": r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
    },
    "run_hklm": {
        "kind": "run",
        "reg": r"HKLM:\Software\Microsoft\Windows\CurrentVersion\Run",
        "approve": r"HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
    },
    "startup_user": {
        "kind": "folder",
        "approve": r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder",
    },
    "startup_all": {
        "kind": "folder",
        "approve": r"HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder",
    },
}


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
function Get-Disabled([string]$approveKey, [string]$name) {
  if (Test-Path $approveKey) {
    $v = (Get-ItemProperty -Path $approveKey -Name $name -ErrorAction SilentlyContinue).$name
    if ($null -ne $v) {
      $b = if ($v -is [byte[]]) { $v[0] } else { 0 }
      return (($b -band 3) -eq 3)
    }
  }
  return $false
}

$results = @()
$regKeys = @(
  @{ path='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run';     src='run_hkcu';   approve='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' },
  @{ path='HKLM:\Software\Microsoft\Windows\CurrentVersion\Run';     src='run_hklm';   approve='HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' },
  @{ path='HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'; src='runonce_hkcu'; approve='' },
  @{ path='HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce'; src='runonce_hklm'; approve='' }
)
foreach ($k in $regKeys) {
  if (Test-Path $k.path) {
    $props = Get-ItemProperty $k.path
    foreach ($p in $props.PSObject.Properties) {
      if ($p.Name -notlike 'PS*') {
        $d = if ($k.approve) { Get-Disabled $k.approve $p.Name } else { $false }
        $results += [ordered]@{ source=$k.src; name=$p.Name; command=[string]$p.Value; disabled=$d }
      }
    }
  }
}

$folders = @(
  @{ path="$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup";   src='startup_user'; approve='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder' },
  @{ path="$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup"; src='startup_all'; approve='HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder' }
)
$sh = New-Object -ComObject WScript.Shell
foreach ($f in $folders) {
  if (Test-Path $f.path) {
    Get-ChildItem $f.path -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'desktop.ini' } | ForEach-Object {
      $target = $_.FullName
      $args = ''
      if ($_.Extension -eq '.lnk') {
        try {
          $lnk = $sh.CreateShortcut($_.FullName)
          if ($lnk.TargetPath) { $target = $lnk.TargetPath }
          if ($lnk.Arguments) { $args = $lnk.Arguments }
        } catch { }
      }
      $d = Get-Disabled $f.approve $_.Name
      $results += [ordered]@{ source=$f.src; name=$_.Name; command=$target; arguments=$args; disabled=$d }
    }
  }
}

[ordered]@{ count=$results.Count; entries=$results } | ConvertTo-Json -Compress
"""

# Folder resolution: user Startup folder vs all-user (ProgramData) Startup folder.
_FOLDER_EXPR = r"""if ($env:COAGENT_STARTUP_SOURCE -eq 'startup_all') { "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup" } else { "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup" }"""

_ADD_RUN_SCRIPT = r"""
$key = $env:COAGENT_STARTUP_KEY
$name = $env:COAGENT_STARTUP_NAME
$value = $env:COAGENT_STARTUP_COMMAND
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
Set-ItemProperty -Path $key -Name $name -Value $value
[ordered]@{ source=$env:COAGENT_STARTUP_SOURCE; name=$name; command=$value; added=$true } | ConvertTo-Json -Compress
"""

_ADD_FOLDER_SCRIPT = r"""
$folder = """ + _FOLDER_EXPR + r"""
$name = $env:COAGENT_STARTUP_NAME
$command = $env:COAGENT_STARTUP_COMMAND
$arguments = $env:COAGENT_STARTUP_ARGUMENTS
if ($name -notmatch '\.[^\\]+$') { $name = $name + '.lnk' }
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $folder $name))
$lnk.TargetPath = $command
if ($arguments) { $lnk.Arguments = $arguments }
$lnk.Save()
[ordered]@{ source=$env:COAGENT_STARTUP_SOURCE; name=$name; command=$command; added=$true } | ConvertTo-Json -Compress
"""

_REMOVE_RUN_SCRIPT = r"""
$key = $env:COAGENT_STARTUP_KEY
$approve = $env:COAGENT_STARTUP_APPROVE
$name = $env:COAGENT_STARTUP_NAME
Remove-ItemProperty -Path $key -Name $name -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $approve -Name $name -ErrorAction SilentlyContinue
[ordered]@{ source=$env:COAGENT_STARTUP_SOURCE; name=$name; removed=$true } | ConvertTo-Json -Compress
"""

_REMOVE_FOLDER_SCRIPT = r"""
$folder = """ + _FOLDER_EXPR + r"""
$approve = $env:COAGENT_STARTUP_APPROVE
$name = $env:COAGENT_STARTUP_NAME
if ($name -notmatch '\.[^\\]+$') { $name = $name + '.lnk' }
$path = Join-Path $folder $name
if (Test-Path $path) { Remove-Item $path -Force }
Remove-ItemProperty -Path $approve -Name $name -ErrorAction SilentlyContinue
[ordered]@{ source=$env:COAGENT_STARTUP_SOURCE; name=$name; removed=$true } | ConvertTo-Json -Compress
"""

_SET_APPROVED_SCRIPT = r"""
$key = $env:COAGENT_STARTUP_APPROVE
$name = $env:COAGENT_STARTUP_NAME
$flag = [int]$env:COAGENT_STARTUP_FLAG
if ($env:COAGENT_STARTUP_IS_FOLDER -eq '1' -and $name -notmatch '\.[^\\]+$') { $name = $name + '.lnk' }
$bytes = New-Object byte[] 12
$bytes[0] = [byte]$flag
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
Set-ItemProperty -Path $key -Name $name -Value $bytes -Type Binary
[ordered]@{ name=$name; flag=$flag; done=$true } | ConvertTo-Json -Compress
"""


def _source_kind(source):
    return _SOURCES[source]["kind"]


def _validate_name(name):
    """Reject startup-entry names that could escape their target folder or
    inject registry subkeys/control characters. Returns an error string or None."""
    if len(name) > 255:
        return "name too long (max 255)"
    if ".." in name or any(ch in name for ch in ("\\", "/", ":", "\x00")):
        return "name contains invalid characters"
    if any(ord(ch) < 32 for ch in name):
        return "name contains control characters"
    return None


def register_routes(app, state, require_auth):
    @app.route("/startup/list", methods=["GET"])
    @require_auth
    def route_startup_list():
        result, stderr, code = _ps_json(_LIST_SCRIPT, timeout=60)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/startup/add", methods=["POST"])
    @require_auth
    def route_startup_add():
        data = _json_body() or {}
        source = str(data.get("source") or "run_hkcu").lower()
        name = str(data.get("name") or "").strip()
        command = str(data.get("command") or "").strip()
        if source not in _SOURCES:
            return jsonify({"error": "source must be run_hkcu, run_hklm, startup_user, or startup_all"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        err = _validate_name(name)
        if err:
            return jsonify({"error": err}), 400
        if not command:
            return jsonify({"error": "command is required"}), 400
        kind = _source_kind(source)
        if kind == "run":
            result, stderr, code = _ps_json(_ADD_RUN_SCRIPT, timeout=60, env={
                "COAGENT_STARTUP_SOURCE": source,
                "COAGENT_STARTUP_KEY": _SOURCES[source]["reg"],
                "COAGENT_STARTUP_NAME": name,
                "COAGENT_STARTUP_COMMAND": command,
            })
        else:
            result, stderr, code = _ps_json(_ADD_FOLDER_SCRIPT, timeout=60, env={
                "COAGENT_STARTUP_SOURCE": source,
                "COAGENT_STARTUP_NAME": name,
                "COAGENT_STARTUP_COMMAND": command,
                "COAGENT_STARTUP_ARGUMENTS": str(data.get("arguments") or ""),
            })
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        _log(f"startup: add {source} {name}")
        return jsonify(result)

    @app.route("/startup/remove", methods=["POST"])
    @require_auth
    def route_startup_remove():
        data = _json_body() or {}
        source = str(data.get("source") or "").lower()
        name = str(data.get("name") or "").strip()
        if source not in _SOURCES:
            return jsonify({"error": "source must be run_hkcu, run_hklm, startup_user, or startup_all"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        err = _validate_name(name)
        if err:
            return jsonify({"error": err}), 400
        kind = _source_kind(source)
        if kind == "run":
            result, stderr, code = _ps_json(_REMOVE_RUN_SCRIPT, timeout=60, env={
                "COAGENT_STARTUP_SOURCE": source,
                "COAGENT_STARTUP_KEY": _SOURCES[source]["reg"],
                "COAGENT_STARTUP_APPROVE": _SOURCES[source]["approve"],
                "COAGENT_STARTUP_NAME": name,
            })
        else:
            result, stderr, code = _ps_json(_REMOVE_FOLDER_SCRIPT, timeout=60, env={
                "COAGENT_STARTUP_SOURCE": source,
                "COAGENT_STARTUP_APPROVE": _SOURCES[source]["approve"],
                "COAGENT_STARTUP_NAME": name,
            })
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        _log(f"startup: remove {source} {name}")
        return jsonify(result)

    def _set_approved(source, name, flag):
        kind = _source_kind(source)
        return _ps_json(_SET_APPROVED_SCRIPT, timeout=60, env={
            "COAGENT_STARTUP_APPROVE": _SOURCES[source]["approve"],
            "COAGENT_STARTUP_NAME": name,
            "COAGENT_STARTUP_FLAG": str(flag),
            "COAGENT_STARTUP_IS_FOLDER": "1" if kind == "folder" else "0",
        })

    @app.route("/startup/disable", methods=["POST"])
    @require_auth
    def route_startup_disable():
        data = _json_body() or {}
        source = str(data.get("source") or "").lower()
        name = str(data.get("name") or "").strip()
        if source not in _SOURCES:
            return jsonify({"error": "source must be run_hkcu, run_hklm, startup_user, or startup_all"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        err = _validate_name(name)
        if err:
            return jsonify({"error": err}), 400
        result, stderr, code = _set_approved(source, name, 3)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        _log(f"startup: disable {source} {name}")
        return jsonify(result)

    @app.route("/startup/enable", methods=["POST"])
    @require_auth
    def route_startup_enable():
        data = _json_body() or {}
        source = str(data.get("source") or "").lower()
        name = str(data.get("name") or "").strip()
        if source not in _SOURCES:
            return jsonify({"error": "source must be run_hkcu, run_hklm, startup_user, or startup_all"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        err = _validate_name(name)
        if err:
            return jsonify({"error": err}), 400
        result, stderr, code = _set_approved(source, name, 2)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        _log(f"startup: enable {source} {name}")
        return jsonify(result)

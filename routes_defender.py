"""Windows Defender management routes -- inspect AV posture and manage
exclusions so agents can self-heal when Defender quarantines their own tooling.

    GET  /defender/status              -- protection state, real-time protection,
                                          definitions version/age, last scans
    GET  /defender/threats             -- recent threat detections and actions
    GET  /defender/exclusions/list     -- path/process/extension/IP exclusions
    POST /defender/exclusions/add      -- {type: path|process|extension, value}
    POST /defender/exclusions/remove   -- {type: path|process|extension, value}
    POST /defender/scan                -- {type: quick|full}

All commands go through the Defender PowerShell module (Get-MpComputerStatus,
Get-MpThreatDetection, Add/Remove-MpPreference, Start-MpScan) and require
elevation; CoAgent runs elevated. Gated behind the existing auth + governance
layer, so this is a controlled, auditable surface -- not a disable-switch.
"""

import json
import os
import subprocess

from flask import jsonify

from shared import _json_body, _log


_EXCL_TYPES = ("path", "process", "extension")


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


_STATUS_SCRIPT = r"""
try {
  $s = Get-MpComputerStatus -ErrorAction Stop
  [ordered]@{
    realtime_protection = [bool]$s.RealTimeProtectionEnabled
    antivirus_enabled = [bool]$s.AntivirusEnabled
    signature_version = $s.AntivirusSignatureVersion
    signature_age_days = $s.AntivirusSignatureAge
    signature_last_updated = $s.AntivirusSignatureLastUpdated
    quick_scan_end = $s.QuickScanEndTime
    full_scan_end = $s.FullScanEndTime
    service_enabled = [bool]$s.AMServiceEnabled
    behavior_monitor = [bool]$s.BehaviorMonitorEnabled
    on_access_protection = [bool]$s.OnAccessProtectionEnabled
    tamper_protection = [bool]$s.IsTamperProtected
    nis_enabled = [bool]$s.NISEnabled
  } | ConvertTo-Json -Compress
} catch {
  [ordered]@{ error=$_.Exception.Message } | ConvertTo-Json -Compress
}
"""

_THREATS_SCRIPT = r"""
$t = Get-MpThreatDetection -ErrorAction SilentlyContinue | Select-Object -First 50
$rows = @($t | ForEach-Object {
  [ordered]@{
    id = $_.ThreatID
    name = $_.ThreatName
    severity = $_.SeverityName
    action = $_.ActionTaken
    detected = $_.InitialDetectionTime
    resources = @($_.Resources)
  }
})
[ordered]@{ count=$rows.Count; threats=$rows } | ConvertTo-Json -Compress
"""

_EXCL_LIST_SCRIPT = r"""
$p = Get-MpPreference -ErrorAction SilentlyContinue
$paths = @(); $procs = @(); $exts = @(); $ips = @()
if ($null -ne $p.ExclusionPath) { $paths = @($p.ExclusionPath) }
if ($null -ne $p.ExclusionProcess) { $procs = @($p.ExclusionProcess) }
if ($null -ne $p.ExclusionExtension) { $exts = @($p.ExclusionExtension) }
if ($null -ne $p.ExclusionIpAddress) { $ips = @($p.ExclusionIpAddress) }
[ordered]@{ paths=$paths; processes=$procs; extensions=$exts; ips=$ips } | ConvertTo-Json -Compress
"""

_EXCL_ADD_SCRIPT = r"""
$type = $env:COAGENT_DEF_TYPE
$value = $env:COAGENT_DEF_VALUE
try {
  switch ($type) {
    'path'      { Add-MpPreference -ExclusionPath $value -ErrorAction Stop }
    'process'   { Add-MpPreference -ExclusionProcess $value -ErrorAction Stop }
    'extension' { Add-MpPreference -ExclusionExtension $value -ErrorAction Stop }
  }
  [ordered]@{ type=$type; value=$value; added=$true } | ConvertTo-Json -Compress
} catch {
  [ordered]@{ type=$type; value=$value; added=$false; error=$_.Exception.Message } | ConvertTo-Json -Compress
}
"""

_EXCL_REMOVE_SCRIPT = r"""
$type = $env:COAGENT_DEF_TYPE
$value = $env:COAGENT_DEF_VALUE
try {
  switch ($type) {
    'path'      { Remove-MpPreference -ExclusionPath $value -ErrorAction Stop }
    'process'   { Remove-MpPreference -ExclusionProcess $value -ErrorAction Stop }
    'extension' { Remove-MpPreference -ExclusionExtension $value -ErrorAction Stop }
  }
  [ordered]@{ type=$type; value=$value; removed=$true } | ConvertTo-Json -Compress
} catch {
  [ordered]@{ type=$type; value=$value; removed=$false; error=$_.Exception.Message } | ConvertTo-Json -Compress
}
"""

_SCAN_QUICK_SCRIPT = r"""
try {
  Start-MpScan -ScanType QuickScan -ErrorAction Stop | Out-Null
  [ordered]@{ scan_type='quick'; completed=$true; error=$null } | ConvertTo-Json -Compress
} catch {
  [ordered]@{ scan_type='quick'; completed=$false; error=$_.Exception.Message } | ConvertTo-Json -Compress
}
"""

_SCAN_FULL_SCRIPT = r"""
Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-NonInteractive','-Command','Start-MpScan -ScanType FullScan' -WindowStyle Hidden
[ordered]@{ scan_type='full'; started=$true; note='Full scan running in background; poll /defender/status' } | ConvertTo-Json -Compress
"""


def register_routes(app, state, require_auth):
    @app.route("/defender/status", methods=["GET"])
    @require_auth
    def route_defender_status():
        result, stderr, code = _ps_json(_STATUS_SCRIPT, timeout=60)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/defender/threats", methods=["GET"])
    @require_auth
    def route_defender_threats():
        result, stderr, code = _ps_json(_THREATS_SCRIPT, timeout=60)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/defender/exclusions/list", methods=["GET"])
    @require_auth
    def route_defender_exclusions_list():
        result, stderr, code = _ps_json(_EXCL_LIST_SCRIPT, timeout=60)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/defender/exclusions/add", methods=["POST"])
    @require_auth
    def route_defender_exclusions_add():
        data = _json_body() or {}
        etype = str(data.get("type") or "path").lower()
        value = str(data.get("value") or "").strip()
        if etype not in _EXCL_TYPES:
            return jsonify({"error": "type must be 'path', 'process', or 'extension'"}), 400
        if not value:
            return jsonify({"error": "value is required"}), 400
        result, stderr, code = _ps_json(_EXCL_ADD_SCRIPT, timeout=60, env={
            "COAGENT_DEF_TYPE": etype,
            "COAGENT_DEF_VALUE": value,
        })
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        if result.get("added") is False:
            return jsonify({"error": result.get("error") or "failed to add exclusion"}), 500
        _log(f"defender: add {etype} exclusion {value}")
        return jsonify(result)

    @app.route("/defender/exclusions/remove", methods=["POST"])
    @require_auth
    def route_defender_exclusions_remove():
        data = _json_body() or {}
        etype = str(data.get("type") or "path").lower()
        value = str(data.get("value") or "").strip()
        if etype not in _EXCL_TYPES:
            return jsonify({"error": "type must be 'path', 'process', or 'extension'"}), 400
        if not value:
            return jsonify({"error": "value is required"}), 400
        result, stderr, code = _ps_json(_EXCL_REMOVE_SCRIPT, timeout=60, env={
            "COAGENT_DEF_TYPE": etype,
            "COAGENT_DEF_VALUE": value,
        })
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        if result.get("removed") is False:
            return jsonify({"error": result.get("error") or "failed to remove exclusion"}), 500
        _log(f"defender: remove {etype} exclusion {value}")
        return jsonify(result)

    @app.route("/defender/scan", methods=["POST"])
    @require_auth
    def route_defender_scan():
        data = _json_body() or {}
        scan_type = str(data.get("type") or "quick").lower()
        if scan_type == "full":
            result, stderr, code = _ps_json(_SCAN_FULL_SCRIPT, timeout=30)
        elif scan_type == "quick":
            result, stderr, code = _ps_json(_SCAN_QUICK_SCRIPT, timeout=600)
        else:
            return jsonify({"error": "type must be 'quick' or 'full'"}), 400
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        _log(f"defender: scan {scan_type}")
        return jsonify(result)

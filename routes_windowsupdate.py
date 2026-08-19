"""Windows Update management routes — detect/defer surprise reboots.

Gives CoAgent visibility and control over Windows Update so a forced reboot
cannot silently kill long-running automation:

    GET  /windowsupdate/status          — last check/install, pause state, reboot flag
    GET  /windowsupdate/pending-reboot  — registry/CBS/DISM pending-reboot detection
    POST /windowsupdate/pause           — pause updates for N days (registry)
    POST /windowsupdate/resume          — resume updates
    GET  /windowsupdate/list            — available updates (wuapi COM)
    POST /windowsupdate/check           — online update search (wuapi COM)

All registry keys live under HKLM and require elevation; CoAgent runs elevated.
"""

import json
import subprocess

from flask import jsonify

from shared import _json_body, _log


def _ps(script, timeout=60):
    """Run a PowerShell command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "PowerShell command timed out", -1
    except FileNotFoundError:
        return "", "powershell.exe not found (not on Windows?)", -1


def _ps_json(script, timeout=60):
    """Run PowerShell, try to parse JSON output; fall back to raw text."""
    stdout, stderr, code = _ps(script, timeout=timeout)
    if stdout:
        try:
            return json.loads(stdout), stderr, code
        except (ValueError, TypeError):
            pass
    return {"raw": stdout or stderr}, stderr, code


_PENDING_REBOOT_SCRIPT = r"""
$r = [ordered]@{ reboot_required = $false; reasons = @() }
$k = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
if (Test-Path $k) { $r.reboot_required = $true; $r.reasons += 'WindowsUpdate RebootRequired key present' }
$cbs = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
if ((Get-ItemProperty -Path $cbs -Name RebootPending -ErrorAction SilentlyContinue).RebootPending -eq 1) {
  $r.reboot_required = $true; $r.reasons += 'CBS RebootPending = 1'
}
$cbs2 = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootRequired'
if (Test-Path $cbs2) { $r.reboot_required = $true; $r.reasons += 'CBS RebootRequired key present' }
$sm = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
$pfr = (Get-ItemProperty -Path $sm -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
if ($pfr) {
  $n = if ($pfr -is [array]) { $pfr.Count } else { 1 }
  if ($n -gt 0) { $r.reboot_required = $true; $r.reasons += "PendingFileRenameOperations has $n entries" }
}
$upd = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\PostRebootReporting'
if (Test-Path $upd) { $r.reboot_required = $true; $r.reasons += 'WindowsUpdate PostRebootReporting key present' }
$r | ConvertTo-Json -Compress
"""

_STATUS_SCRIPT = r"""
$r = [ordered]@{}
$detect = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\Results\Detect' -ErrorAction SilentlyContinue
$install = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\Results\Install' -ErrorAction SilentlyContinue
$r.last_check = if ($detect.LastSuccessTime) { $detect.LastSuccessTime } else { $null }
$r.last_install = if ($install.LastSuccessTime) { $install.LastSuccessTime } else { $null }
$ux = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
$r.pause_expiry = (Get-ItemProperty -Path $ux -Name PauseUpdatesExpiryTime -ErrorAction SilentlyContinue).PauseUpdatesExpiryTime
$r.paused = [bool]$r.pause_expiry
$r | ConvertTo-Json -Compress
"""


def _pause_script(days):
    days = max(1, min(int(days), 365))
    d = str(days)
    return r"""
$days = """ + d + r"""
$start = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$end = (Get-Date).AddDays($days).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$p = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
New-Item -Path $p -Force | Out-Null
Set-ItemProperty -Path $p -Name PauseUpdatesExpiryTime -Value $end
Set-ItemProperty -Path $p -Name PauseFeatureUpdatesStartTime -Value $start
Set-ItemProperty -Path $p -Name PauseFeatureUpdatesEndTime -Value $end
Set-ItemProperty -Path $p -Name PauseQualityUpdatesStartTime -Value $start
Set-ItemProperty -Path $p -Name PauseQualityUpdatesEndTime -Value $end
[ordered]@{ paused = $true; days = $days; pause_expiry = $end } | ConvertTo-Json -Compress
"""


_RESUME_SCRIPT = r"""
$p = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
foreach ($n in @('PauseUpdatesExpiryTime','PauseFeatureUpdatesStartTime','PauseFeatureUpdatesEndTime','PauseQualityUpdatesStartTime','PauseQualityUpdatesEndTime')) {
  Remove-ItemProperty -Path $p -Name $n -ErrorAction SilentlyContinue
}
[ordered]@{ paused = $false } | ConvertTo-Json -Compress
"""


def _search_script(online):
    online_flag = "$true" if online else "$false"
    return r"""
$s = New-Object -ComObject Microsoft.Update.Session
$searcher = $s.CreateUpdateSearcher()
$searcher.Online = """ + online_flag + r"""
$res = $searcher.Search('IsInstalled=0 and IsHidden=0')
$updates = @($res.Updates | ForEach-Object {
  [ordered]@{
    title = $_.Title
    kb = ($_.KBArticleIDs -join ',')
    downloaded = $_.IsDownloaded
    mandatory = $_.IsMandatory
  }
})
[ordered]@{ count = $updates.Count; updates = $updates } | ConvertTo-Json -Compress
"""


def register_routes(app, state, require_auth):
    @app.route("/windowsupdate/status", methods=["GET"])
    @require_auth
    def route_wu_status():
        status, stderr, code = _ps_json(_STATUS_SCRIPT, timeout=30)
        reboot, _, _ = _ps_json(_PENDING_REBOOT_SCRIPT, timeout=30)
        status["reboot_required"] = reboot.get("reboot_required", False)
        status["reboot_reasons"] = reboot.get("reasons", [])
        return jsonify(status)

    @app.route("/windowsupdate/pending-reboot", methods=["GET"])
    @require_auth
    def route_wu_pending_reboot():
        result, stderr, code = _ps_json(_PENDING_REBOOT_SCRIPT, timeout=30)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/windowsupdate/pause", methods=["POST"])
    @require_auth
    def route_wu_pause():
        data = _json_body() or {}
        try:
            days = int(data.get("days", 7))
        except (TypeError, ValueError):
            return jsonify({"error": "days must be an integer"}), 400
        result, stderr, code = _ps_json(_pause_script(days), timeout=30)
        _log(f"windowsupdate: pause {days}d -> {result}")
        return jsonify(result)

    @app.route("/windowsupdate/resume", methods=["POST"])
    @require_auth
    def route_wu_resume():
        result, stderr, code = _ps_json(_RESUME_SCRIPT, timeout=30)
        _log(f"windowsupdate: resume -> {result}")
        return jsonify(result)

    @app.route("/windowsupdate/list", methods=["GET"])
    @require_auth
    def route_wu_list():
        result, stderr, code = _ps_json(_search_script(online=False), timeout=120)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

    @app.route("/windowsupdate/check", methods=["POST"])
    @require_auth
    def route_wu_check():
        result, stderr, code = _ps_json(_search_script(online=True), timeout=180)
        if code != 0 and "raw" in result:
            return jsonify({"error": stderr or result["raw"]}), 500
        return jsonify(result)

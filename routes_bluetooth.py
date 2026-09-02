"""Bluetooth device management — issue #1130.

Extends /system/bluetooth (adapter toggle) with real device management:
discover, list paired, pair / connect / disconnect / unpair by name or MAC.

Endpoints:
    GET  /system/bluetooth/devices    — list Bluetooth PnP devices (name, status)
    POST /system/bluetooth/discover   — scan for nearby devices (name/MAC/signal/paired)
    POST /system/bluetooth/pair       — pair a device {mac or name}
    POST /system/bluetooth/unpair     — remove a paired device
    POST /system/bluetooth/connect    — enable/attach a device (PnP + pair if needed)
    POST /system/bluetooth/disconnect — disable/detach a device

Implementation: Windows.Devices.Enumeration / Bluetooth WinRT via PowerShell
(the documented Windows approach for Bluetooth pairing). Stdlib only.
"""

import json as _json
import re
import subprocess
import traceback

from flask import jsonify

from shared import _json_body, _log, _missing_field

_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")

# PowerShell preamble: load WinRT types + a generic IAsyncOperation<->Task bridge.
_PS_PREAMBLE = r"""
$ErrorActionPreference = 'Stop'
[Windows.Devices.Bluetooth.BluetoothDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Enumeration.DeviceInformation, Windows.Devices.Enumeration, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Enumeration.DeviceInformationPairing, Windows.Devices.Enumeration, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Enumeration.DevicePairingResult, Windows.Devices.Enumeration, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Enumeration.DeviceUnpairingResult, Windows.Devices.Enumeration, ContentType = WindowsRuntime] | Out-Null
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}
function DeviceNameOf($d) {
  if ($null -eq $d) { return '' }
  try { return [string]$d.Name } catch { return '' }
}
function DeviceIdOf($d) {
  if ($null -eq $d) { return '' }
  try { return [string]$d.Id } catch { return '' }
}
function DeviceMacOf($d) {
  $id = DeviceIdOf $d
  $m = [regex]::Match($id, '(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}')
  if ($m.Success) { return $m.Value.ToUpper() } else { return '' }
}
"""


def _ps(script, timeout=40):
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


def _match_clause(mac, name):
    """Build a PowerShell Where-Object predicate matching a device by MAC or name."""
    clauses = []
    if mac:
        m = mac.replace("-", ":").strip()
        if _MAC_RE.search(m):
            clauses.append(f"(DeviceMacOf $_) -eq '{m.upper()}'")
    if name:
        clauses.append(f"(DeviceNameOf $_) -like '*{name}*'")
    if not clauses:
        return None
    return " -or ".join(f"({c})" for c in clauses)


def _run_ps(body, timeout=40):
    out, err, rc = _ps(_PS_PREAMBLE + "\n" + body, timeout=timeout)
    if rc != 0:
        return {"ok": False, "error": (err or out or f"PowerShell exited {rc}").strip()}
    return {"ok": True, "output": out}


def register_routes(app, state, require_auth):

    @app.route("/system/bluetooth/devices", methods=["GET"])
    @require_auth
    def route_bt_devices():
        out, err, rc = _ps(
            "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
            "Select-Object Status, FriendlyName, InstanceId, Class | ConvertTo-Json -Compress",
            timeout=20,
        )
        if rc != 0:
            return jsonify({"error": err or "failed to enumerate Bluetooth devices"}), 502
        try:
            devices = _json.loads(out) if out else []
            if isinstance(devices, dict):
                devices = [devices]
        except Exception:
            devices = []
        return jsonify({"status": "ok", "count": len(devices), "devices": devices})

    @app.route("/system/bluetooth/discover", methods=["POST"])
    @require_auth
    def route_bt_discover():
        body = r"""
$selector = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($false)
$devices = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($selector)) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Enumeration.DeviceInformation]])
$result = @()
foreach ($d in $devices) {
  $mac = DeviceMacOf $d
  $props = $d.Properties
  $sig = ''
  try { if ($props.ContainsKey('System.Devices.Aep.SignalStrength')) { $sig = $props['System.Devices.Aep.SignalStrength'] } } catch {}
  $paired = $false
  try { $paired = $d.Pairing.IsPaired } catch {}
  $result += [PSCustomObject]@{ name = (DeviceNameOf $d); mac = $mac; signal = $sig; paired = $paired; id = (DeviceIdOf $d) }
}
$result | ConvertTo-Json -Compress
"""
        res = _run_ps(body, timeout=40)
        if not res["ok"]:
            return jsonify(res), 502
        try:
            found = _json.loads(res["output"]) if res["output"] else []
            if isinstance(found, dict):
                found = [found]
        except Exception:
            found = []
        return jsonify({"status": "ok", "count": len(found), "devices": found})

    @app.route("/system/bluetooth/pair", methods=["POST"])
    @require_auth
    def route_bt_pair():
        d = _json_body()
        mac = (d.get("mac") or "").strip()
        name = (d.get("name") or "").strip()
        if not mac and not name:
            return _missing_field("mac or name")
        clause = _match_clause(mac, name)
        if not clause:
            return jsonify({"error": "invalid mac or name"}), 400
        body = r"""
$selector = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($false)
$devices = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($selector)) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Enumeration.DeviceInformation]])
$target = $devices | Where-Object { __CLAUSE__ } | Select-Object -First 1
if ($null -eq $target) {
  $pairedSelector = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($true)
  $paired = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($pairedSelector)) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Enumeration.DeviceInformation]])
  $already = $paired | Where-Object { __CLAUSE__ } | Select-Object -First 1
  if ($null -ne $already) { 'ALREADY_PAIRED' } else { 'NOT_FOUND' }
} else {
  $result = Await ($target.Pairing.PairAsync()) ([Windows.Devices.Enumeration.DevicePairingResult])
  'PAIRED:' + $result.Status.ToString()
}
""".replace("__CLAUSE__", clause)
        res = _run_ps(body, timeout=60)
        if not res["ok"]:
            return jsonify(res), 502
        out = (res["output"] or "").strip()
        if out.startswith("PAIRED:"):
            status = out.split(":", 1)[1]
            success = status in ("Paired", "AlreadyPaired")
            return jsonify({"status": "ok" if success else "failed", "pairing_status": status})
        if out == "ALREADY_PAIRED":
            return jsonify({"status": "ok", "pairing_status": "AlreadyPaired"})
        if out == "NOT_FOUND":
            return jsonify({"error": "device not found in range"}), 404
        return jsonify({"status": "failed", "detail": out}), 502

    @app.route("/system/bluetooth/unpair", methods=["POST"])
    @require_auth
    def route_bt_unpair():
        d = _json_body()
        mac = (d.get("mac") or "").strip()
        name = (d.get("name") or "").strip()
        if not mac and not name:
            return _missing_field("mac or name")
        clause = _match_clause(mac, name)
        if not clause:
            return jsonify({"error": "invalid mac or name"}), 400
        body = r"""
$selector = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($true)
$devices = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($selector)) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Enumeration.DeviceInformation]])
$target = $devices | Where-Object { __CLAUSE__ } | Select-Object -First 1
if ($null -eq $target) { 'NOT_FOUND' } else {
  $result = Await ($target.Pairing.UnpairAsync()) ([Windows.Devices.Enumeration.DeviceUnpairingResult])
  'UNPAIRED:' + $result.Status.ToString()
}
""".replace("__CLAUSE__", clause)
        res = _run_ps(body, timeout=60)
        if not res["ok"]:
            return jsonify(res), 502
        out = (res["output"] or "").strip()
        if out.startswith("UNPAIRED:"):
            status = out.split(":", 1)[1]
            return jsonify({"status": "ok" if status == "Unpaired" else "failed", "unpair_status": status})
        if out == "NOT_FOUND":
            return jsonify({"error": "paired device not found"}), 404
        return jsonify({"status": "failed", "detail": out}), 502

    def _pnpmatch_clause(mac, name):
        """Build a Where-Object predicate against Get-PnpDevice rows."""
        conds = []
        if name:
            conds.append(f"$_.FriendlyName -like '*{name}*'")
        if mac:
            m = mac.replace("-", ":").upper()
            conds.append(f"$_.InstanceId -like '*{m}*'")
        return " -or ".join(conds)

    @app.route("/system/bluetooth/connect", methods=["POST"])
    @require_auth
    def route_bt_connect():
        d = _json_body()
        mac = (d.get("mac") or "").strip()
        name = (d.get("name") or "").strip()
        if not mac and not name:
            return _missing_field("mac or name")
        cond = _pnpmatch_clause(mac, name)
        out, err, rc = _ps(
            f"$dev = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
            f"Where-Object {{ {cond} }} | Select-Object -First 1; "
            f"if ($dev) {{ Enable-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false | Out-Null; 'ENABLED' }} else {{ 'NOT_FOUND' }}",
            timeout=30,
        )
        if rc != 0:
            return jsonify({"error": err or "connect failed"}), 502
        out = (out or "").strip()
        if out == "ENABLED":
            return jsonify({"status": "ok", "connected": True})
        if out == "NOT_FOUND":
            return jsonify({"error": "device not found"}), 404
        return jsonify({"status": "failed", "detail": out}), 502

    @app.route("/system/bluetooth/disconnect", methods=["POST"])
    @require_auth
    def route_bt_disconnect():
        d = _json_body()
        mac = (d.get("mac") or "").strip()
        name = (d.get("name") or "").strip()
        if not mac and not name:
            return _missing_field("mac or name")
        cond = _pnpmatch_clause(mac, name)
        out, err, rc = _ps(
            f"$dev = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
            f"Where-Object {{ {cond} }} | Select-Object -First 1; "
            f"if ($dev) {{ Disable-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false | Out-Null; 'DISABLED' }} else {{ 'NOT_FOUND' }}",
            timeout=30,
        )
        if rc != 0:
            return jsonify({"error": err or "disconnect failed"}), 502
        out = (out or "").strip()
        if out == "DISABLED":
            return jsonify({"status": "ok", "connected": False})
        if out == "NOT_FOUND":
            return jsonify({"error": "device not found"}), 404
        return jsonify({"status": "failed", "detail": out}), 502

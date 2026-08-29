"""USB device management routes.

Endpoints:
  GET/POST /usb/list     - enumerate present USB devices (PnP + volumes)
  POST     /usb/eject    - safely eject a removable USB volume by drive letter
  GET/POST /usb/monitor  - report attach/detach deltas since the last snapshot

Uses PowerShell Get-PnpDevice / Get-CimInstance Win32_USBHub with pure-ASCII
argument strings. On non-Windows hosts the endpoints return HTTP 501 rather
than failing at import time so the Linux syntax-check CI stays green.
"""

import json as _json
import os
import re
import shutil
import subprocess
import threading
import time

from flask import jsonify

from shared import _json_body, _log, _missing_field


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Drive letters only: single A-Z, optionally followed by a colon.
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:?$")
# PnP instance IDs are ASCII with backslash separators, e.g. USB\VID_1234&PID_5678\SN.
_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-\\&{}]{1,512}$")

# Shared state for /usb/monitor snapshot diffing.
_MONITOR_LOCK = threading.Lock()
_MONITOR_STATE = {"snapshot": None, "ts": 0.0}


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_powershell():
    return (
        shutil.which("powershell")
        or shutil.which("powershell.exe")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )


def _run_ps(script, timeout=20):
    """Run a PowerShell script and return (stdout, stderr, returncode)."""
    ps = _find_powershell()
    if not ps or not os.path.isfile(ps):
        return "", "powershell.exe not found", -1
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", -1
    except FileNotFoundError as exc:
        return "", str(exc), -1
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), -1


def _parse_json_output(text):
    """PowerShell ConvertTo-Json emits an object or array. Normalize to list."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = _json.loads(text)
    except ValueError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


# ASCII-only. Matches PnP devices whose class or bus is USB-related.
_LIST_DEVICES_PS = (
    "Get-PnpDevice -PresentOnly | "
    "Where-Object { "
    "$_.Class -in @('USB','USBDevice','WPD','DiskDrive') "
    "-or $_.InstanceId -like 'USB\\*' "
    "-or $_.InstanceId -like 'USBSTOR\\*' "
    "} | "
    "Select-Object InstanceId,FriendlyName,Class,Status,Manufacturer,Service | "
    "ConvertTo-Json -Depth 3 -Compress"
)

_LIST_HUBS_PS = (
    "Get-CimInstance -ClassName Win32_USBHub -ErrorAction SilentlyContinue | "
    "Select-Object DeviceID,Name,Description,Status | "
    "ConvertTo-Json -Depth 3 -Compress"
)

_LIST_VOLUMES_PS = (
    "Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType=2' "
    "-ErrorAction SilentlyContinue | "
    "Select-Object DeviceID,VolumeName,FileSystem,Size,FreeSpace,ProviderName | "
    "ConvertTo-Json -Depth 3 -Compress"
)


def _normalize_devices(entries):
    """Extract stable (id, label) tuples used for snapshot diffing."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        instance_id = entry.get("InstanceId") or entry.get("DeviceID") or ""
        label = (
            entry.get("FriendlyName")
            or entry.get("Name")
            or entry.get("Description")
            or entry.get("VolumeName")
            or ""
        )
        if instance_id:
            out.append({
                "id": str(instance_id),
                "label": str(label),
                "status": str(entry.get("Status") or ""),
                "class": str(entry.get("Class") or ""),
            })
    return out


def _collect_snapshot():
    """Return (snapshot_list, error_or_none)."""
    out, err, rc = _run_ps(_LIST_DEVICES_PS, timeout=25)
    if rc != 0:
        return [], err.strip() or f"Get-PnpDevice failed (rc={rc})"
    text = (out or "").strip()
    # Distinguish "parse failed" from "zero devices". ConvertTo-Json emits
    # "null" (or empty output) when nothing matches -- a legitimate empty
    # snapshot. Non-JSON output is a collection error and must not be
    # mistaken for an empty device list (which would cause the next monitor
    # poll to report every real device as detached and all devices as
    # freshly attached).
    if not text:
        return [], None
    try:
        data = _json.loads(text)
    except ValueError:
        return [], "Get-PnpDevice returned non-JSON output"
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = [data]
    else:
        entries = []
    devices = _normalize_devices(entries)
    return devices, None


def _normalize_drive_letter(raw):
    """Return 'X:' for a valid drive letter or None otherwise."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not _DRIVE_LETTER_RE.fullmatch(value):
        return None
    letter = value[0].upper()
    return f"{letter}:"


def _eject_drive_ps(drive):
    """Build a PowerShell script to eject the given 'X:' drive via Shell COM."""
    # 17 == ssfDRIVES (My Computer namespace). InvokeVerb('Eject') triggers the
    # safe-remove flow. All literals ASCII per project rules.
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$shell = New-Object -ComObject Shell.Application; "
        f"$item = $shell.Namespace(17).ParseName('{drive}'); "
        "if ($null -eq $item) { Write-Error 'drive not found'; exit 2 } "
        "$item.InvokeVerb('Eject'); "
        "Write-Output 'ejected'"
    )


def _drive_removable(drive):
    """Return (removable: bool, error: str|None) for a 'X:' drive letter.

    `drive` is already validated to a single 'X:' letter. DriveType 2 ==
    removable; anything else (fixed disk, network, CD-ROM, the system drive)
    is rejected so /usb/eject cannot target non-removable volumes.
    """
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        f"$d = Get-CimInstance -ClassName Win32_LogicalDisk -Filter \"DeviceID='{drive}'\" | Select-Object -First 1; "
        "if ($null -eq $d) { Write-Output 'NOT_FOUND'; exit 2 } "
        "if ($d.DriveType -ne 2) { Write-Output 'NOT_REMOVABLE'; exit 3 } "
        "Write-Output 'REMOVABLE'"
    )
    out, err, rc = _run_ps(script, timeout=15)
    result = (out or "").strip().upper()
    if rc == 0 and result == "REMOVABLE":
        return True, None
    if result == "NOT_FOUND":
        return False, "drive not found"
    if result == "NOT_REMOVABLE":
        return False, "drive is not removable"
    return False, (err or "drive check failed").strip() or f"drive check failed (rc={rc})"


def register_routes(app, state, require_auth):
    ps_exe = _find_powershell()
    ps_available = bool(ps_exe and os.path.isfile(ps_exe))

    @app.route("/usb/list", methods=["GET", "POST"])
    @require_auth
    def route_usb_list():
        if os.name != "nt" or not ps_available:
            return _windows_only()
        body = _json_body()
        include_hubs = True
        include_volumes = True
        if isinstance(body, dict):
            include_hubs = bool(body.get("include_hubs", True))
            include_volumes = bool(body.get("include_volumes", True))

        out, err, rc = _run_ps(_LIST_DEVICES_PS, timeout=25)
        if rc != 0:
            return jsonify({
                "error": err.strip() or "Get-PnpDevice failed",
                "returncode": rc,
            }), 500
        devices = _parse_json_output(out)

        hubs = []
        hubs_error = None
        if include_hubs:
            h_out, _h_err, h_rc = _run_ps(_LIST_HUBS_PS, timeout=20)
            if h_rc == 0:
                hubs = _parse_json_output(h_out)
            else:
                hubs_error = (_h_err or "hubs query failed").strip() or f"hubs query failed (rc={h_rc})"

        volumes = []
        volumes_error = None
        if include_volumes:
            v_out, _v_err, v_rc = _run_ps(_LIST_VOLUMES_PS, timeout=20)
            if v_rc == 0:
                volumes = _parse_json_output(v_out)
            else:
                volumes_error = (_v_err or "volumes query failed").strip() or f"volumes query failed (rc={v_rc})"

        return jsonify({
            "devices": devices,
            "device_count": len(devices),
            "hubs": hubs,
            "hub_count": len(hubs),
            "volumes": volumes,
            "volume_count": len(volumes),
            "hubs_error": hubs_error,
            "volumes_error": volumes_error,
        })

    @app.route("/usb/eject", methods=["POST"])
    @require_auth
    def route_usb_eject():
        if os.name != "nt" or not ps_available:
            return _windows_only()
        body = _json_body()
        raw = body.get("drive") if isinstance(body, dict) else None
        if not raw:
            return _missing_field("drive")
        drive = _normalize_drive_letter(raw)
        if not drive:
            return jsonify({"error": "invalid drive letter"}), 400

        removable, check_err = _drive_removable(drive)
        if not removable:
            _log(f"usb/eject {drive} rejected: {check_err}")
            return jsonify({"error": check_err or "drive is not removable", "drive": drive}), 400

        script = _eject_drive_ps(drive)
        out, err, rc = _run_ps(script, timeout=20)
        ok = rc == 0 and "ejected" in (out or "").lower()
        _log(f"usb/eject {drive} rc={rc}")
        return jsonify({
            "status": "ok" if ok else "error",
            "drive": drive,
            "stdout": (out or "").strip(),
            "stderr": (err or "").strip(),
            "returncode": rc,
        }), (200 if ok else 500)

    @app.route("/usb/monitor", methods=["GET", "POST"])
    @require_auth
    def route_usb_monitor():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        body = _json_body()
        reset = False
        if isinstance(body, dict):
            reset = bool(body.get("reset", False))

        with _MONITOR_LOCK:
            # Collect the snapshot under the lock so two concurrent monitor
            # requests cannot both diff against the same "previous" snapshot
            # and silently lose device-change events.
            current, err = _collect_snapshot()
            if err:
                return jsonify({"error": err}), 500

            current_by_id = {d["id"]: d for d in current}
            current_ids = set(current_by_id)

            previous = _MONITOR_STATE["snapshot"]
            previous_ts = _MONITOR_STATE["ts"]
            baseline = previous is None or reset

            if baseline:
                _MONITOR_STATE["snapshot"] = current
                _MONITOR_STATE["ts"] = time.time()
                return jsonify({
                    "baseline": True,
                    "devices": current,
                    "count": len(current),
                    "attached": [],
                    "detached": [],
                    "previous_snapshot_ts": previous_ts,
                })

            previous_by_id = {d["id"]: d for d in previous}
            previous_ids = set(previous_by_id)
            attached_ids = current_ids - previous_ids
            detached_ids = previous_ids - current_ids
            attached = [current_by_id[i] for i in attached_ids]
            detached = [previous_by_id[i] for i in detached_ids]

            _MONITOR_STATE["snapshot"] = current
            _MONITOR_STATE["ts"] = time.time()

        return jsonify({
            "baseline": False,
            "devices": current,
            "count": len(current),
            "attached": attached,
            "detached": detached,
            "previous_snapshot_ts": previous_ts,
        })

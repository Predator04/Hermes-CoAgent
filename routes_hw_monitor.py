"""Hardware monitoring routes.

Endpoints:
  GET/POST /hw/status - snapshot of CPU/GPU temperatures, fan speeds and power

Data is collected via a layered strategy:

  1. OpenHardwareMonitor / LibreHardwareMonitor WMI namespace
     (root/OpenHardwareMonitor, root/LibreHardwareMonitor) if the user runs
     one of those tools; this is the most reliable source for temps + fans.
  2. MSAcpi_ThermalZoneTemperature under root/WMI as a generic ACPI fallback.
  3. Win32_Fan, Win32_Battery, Win32_PerfFormattedData for fans + power.
  4. PowerShell CIM queries with pure-ASCII scripts; timeouts are short so a
     missing provider does not hang the request.

On non-Windows hosts (Linux CI syntax-check), the endpoint returns HTTP 501
rather than failing at import time.
"""

import json as _json
import os
import shutil
import subprocess

from flask import jsonify

from shared import _json_body, _log


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_powershell():
    return (
        shutil.which("pwsh")
        or shutil.which("pwsh.exe")
        or shutil.which("powershell")
        or shutil.which("powershell.exe")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )


def _run_ps(script, timeout=15):
    """Run a PowerShell script and return (stdout, stderr, returncode)."""
    ps = _find_powershell()
    if not ps or not os.path.isfile(ps):
        return "", "powershell.exe not found", -1
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", -1
    except FileNotFoundError as exc:
        return "", str(exc), -1


def _parse_json_output(text):
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


# --- WMI / CIM query strings -------------------------------------------------
# All ASCII, no smart quotes, no em-dashes.

# OpenHardwareMonitor / LibreHardwareMonitor exposes a Sensor class with
# SensorType in {Temperature, Fan, Power, Voltage, Load, Clock}.
_OHM_SENSORS_PS = (
    "$ns = @('root/OpenHardwareMonitor','root/LibreHardwareMonitor'); "
    "$all = @(); "
    "foreach ($n in $ns) { "
    "try { "
    "$s = Get-CimInstance -Namespace $n -ClassName Sensor -ErrorAction Stop; "
    "if ($s) { $all += ($s | Select-Object Name,Value,Min,Max,SensorType,Parent,Identifier,@{n='Namespace';e={$n}}) } "
    "} catch {} "
    "} "
    "$all | ConvertTo-Json -Depth 3 -Compress"
)

# Generic ACPI thermal zones. Values are tenths of Kelvin.
_ACPI_THERMAL_PS = (
    "try { "
    "Get-CimInstance -Namespace root/WMI -ClassName MSAcpi_ThermalZoneTemperature "
    "-ErrorAction Stop | "
    "Select-Object InstanceName,CurrentTemperature,CriticalTripPoint | "
    "ConvertTo-Json -Depth 2 -Compress "
    "} catch { '' }"
)

_WIN32_FAN_PS = (
    "try { "
    "Get-CimInstance -ClassName Win32_Fan -ErrorAction Stop | "
    "Select-Object Name,DesiredSpeed,Status,ActiveCooling,VariableSpeed | "
    "ConvertTo-Json -Depth 2 -Compress "
    "} catch { '' }"
)

# Battery / power. Not all systems have batteries; empty output is fine.
_WIN32_BATTERY_PS = (
    "try { "
    "Get-CimInstance -ClassName Win32_Battery -ErrorAction Stop | "
    "Select-Object Name,EstimatedChargeRemaining,BatteryStatus,"
    "EstimatedRunTime,DesignCapacity,FullChargeCapacity | "
    "ConvertTo-Json -Depth 2 -Compress "
    "} catch { '' }"
)

# CPU load + clock as a coarse power/utilization proxy when no sensor is
# available. Uses the perf counter class so it works on stock Windows.
_CPU_PERF_PS = (
    "try { "
    "Get-CimInstance -ClassName Win32_PerfFormattedData_PerfOS_Processor "
    "-Filter \"Name!='_Total'\" -ErrorAction Stop | "
    "Select-Object Name,PercentProcessorTime,PercentPrivilegedTime,PercentUserTime | "
    "ConvertTo-Json -Depth 2 -Compress "
    "} catch { '' }"
)

# GPU utilization (Windows 10+) via perf counters. Aggregated per-engine.
_GPU_PERF_PS = (
    "try { "
    "Get-CimInstance -ClassName Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine "
    "-ErrorAction Stop | "
    "Where-Object { $_.UtilizationPercentage -gt 0 } | "
    "Select-Object Name,UtilizationPercentage | "
    "ConvertTo-Json -Depth 2 -Compress "
    "} catch { '' }"
)


def _kelvin_tenths_to_celsius(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    # MSAcpi_ThermalZoneTemperature reports temperature in tenths of Kelvin.
    if v <= 0:
        return None
    return round((v / 10.0) - 273.15, 2)


def _classify_ohm_sensors(raw):
    """Split OpenHardwareMonitor Sensor rows into temp/fan/power buckets."""
    temps, fans, powers, voltages, loads, clocks = [], [], [], [], [], []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        stype = str(entry.get("SensorType") or "").strip().lower()
        record = {
            "name": entry.get("Name"),
            "parent": entry.get("Parent"),
            "identifier": entry.get("Identifier"),
            "value": entry.get("Value"),
            "min": entry.get("Min"),
            "max": entry.get("Max"),
            "namespace": entry.get("Namespace"),
        }
        if stype == "temperature":
            temps.append(record)
        elif stype == "fan":
            fans.append(record)
        elif stype == "power":
            powers.append(record)
        elif stype == "voltage":
            voltages.append(record)
        elif stype == "load":
            loads.append(record)
        elif stype == "clock":
            clocks.append(record)
    return {
        "temperatures_c": temps,
        "fans_rpm": fans,
        "power_w": powers,
        "voltages_v": voltages,
        "loads_pct": loads,
        "clocks_mhz": clocks,
    }


def _collect_status(sources=None):
    """Aggregate hardware status. sources is a set of str filters or None."""
    wanted = None if sources is None else set(sources)
    result = {
        "sources": [],
        "cpu": {},
        "gpu": {},
        "fans": [],
        "power": {},
        "temperatures": [],
        "errors": {},
    }

    def want(name):
        return wanted is None or name in wanted

    # 1. OpenHardwareMonitor / LibreHardwareMonitor.
    if want("ohm"):
        out, err, rc = _run_ps(_OHM_SENSORS_PS, timeout=12)
        parsed = _parse_json_output(out) if rc == 0 else []
        if parsed:
            classified = _classify_ohm_sensors(parsed)
            result["sources"].append("open_hardware_monitor")
            result["temperatures"].extend(classified["temperatures_c"])
            result["fans"].extend(classified["fans_rpm"])
            result["power"]["sensors_w"] = classified["power_w"]
            result["cpu"]["loads_pct"] = [
                r for r in classified["loads_pct"]
                if "cpu" in str(r.get("parent") or "").lower()
                or "cpu" in str(r.get("name") or "").lower()
            ]
            result["gpu"]["loads_pct"] = [
                r for r in classified["loads_pct"]
                if "gpu" in str(r.get("parent") or "").lower()
                or "gpu" in str(r.get("name") or "").lower()
            ]
            result["cpu"]["clocks_mhz"] = [
                r for r in classified["clocks_mhz"]
                if "cpu" in str(r.get("parent") or "").lower()
            ]
            result["gpu"]["clocks_mhz"] = [
                r for r in classified["clocks_mhz"]
                if "gpu" in str(r.get("parent") or "").lower()
            ]
        elif rc != 0 and err:
            result["errors"]["ohm"] = err.strip()

    # 2. ACPI thermal zones (always try; often the only source w/o OHM).
    if want("acpi"):
        out, err, rc = _run_ps(_ACPI_THERMAL_PS, timeout=8)
        rows = _parse_json_output(out) if rc == 0 else []
        acpi = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            acpi.append({
                "zone": row.get("InstanceName"),
                "current_c": _kelvin_tenths_to_celsius(row.get("CurrentTemperature")),
                "critical_c": _kelvin_tenths_to_celsius(row.get("CriticalTripPoint")),
            })
        if acpi:
            result["sources"].append("acpi_thermal")
            result["acpi_zones"] = acpi
        elif rc != 0 and err:
            result["errors"]["acpi"] = err.strip()

    # 3. Fans via Win32_Fan (often empty on desktops, useful on servers).
    if want("fan"):
        out, err, rc = _run_ps(_WIN32_FAN_PS, timeout=8)
        rows = _parse_json_output(out) if rc == 0 else []
        if rows:
            result["sources"].append("win32_fan")
            for row in rows:
                if isinstance(row, dict):
                    result["fans"].append({
                        "name": row.get("Name"),
                        "desired_speed": row.get("DesiredSpeed"),
                        "status": row.get("Status"),
                        "active_cooling": row.get("ActiveCooling"),
                        "variable_speed": row.get("VariableSpeed"),
                    })
        elif rc != 0 and err:
            result["errors"]["win32_fan"] = err.strip()

    # 4. Battery / power info.
    if want("battery"):
        out, err, rc = _run_ps(_WIN32_BATTERY_PS, timeout=8)
        rows = _parse_json_output(out) if rc == 0 else []
        batts = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            batts.append({
                "name": row.get("Name"),
                "charge_pct": row.get("EstimatedChargeRemaining"),
                "status_code": row.get("BatteryStatus"),
                "estimated_runtime_min": row.get("EstimatedRunTime"),
                "design_capacity_mwh": row.get("DesignCapacity"),
                "full_charge_capacity_mwh": row.get("FullChargeCapacity"),
            })
        if batts:
            result["sources"].append("win32_battery")
            result["power"]["batteries"] = batts
        elif rc != 0 and err:
            result["errors"]["battery"] = err.strip()

    # 5. CPU perf counters (utilization).
    if want("cpu_perf"):
        out, err, rc = _run_ps(_CPU_PERF_PS, timeout=8)
        rows = _parse_json_output(out) if rc == 0 else []
        if rows:
            result["sources"].append("perf_cpu")
            result["cpu"]["utilization_pct"] = [
                {
                    "core": r.get("Name"),
                    "total": r.get("PercentProcessorTime"),
                    "privileged": r.get("PercentPrivilegedTime"),
                    "user": r.get("PercentUserTime"),
                }
                for r in rows if isinstance(r, dict)
            ]
        elif rc != 0 and err:
            result["errors"]["cpu_perf"] = err.strip()

    # 6. GPU perf counters (utilization).
    if want("gpu_perf"):
        out, err, rc = _run_ps(_GPU_PERF_PS, timeout=8)
        rows = _parse_json_output(out) if rc == 0 else []
        if rows:
            result["sources"].append("perf_gpu")
            engines = [
                {"engine": r.get("Name"), "utilization_pct": r.get("UtilizationPercentage")}
                for r in rows if isinstance(r, dict)
            ]
            result["gpu"]["engines"] = engines
        elif rc != 0 and err:
            result["errors"]["gpu_perf"] = err.strip()

    if not result["errors"]:
        result.pop("errors")
    return result


_VALID_SOURCES = {"ohm", "acpi", "fan", "battery", "cpu_perf", "gpu_perf"}


def register_routes(app, state, require_auth):
    ps_exe = _find_powershell()
    ps_available = bool(ps_exe and os.path.isfile(ps_exe))

    @app.route("/hw/status", methods=["GET", "POST"])
    @require_auth
    def route_hw_status():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        body = _json_body()
        sources = None
        if isinstance(body, dict):
            requested = body.get("sources")
            if isinstance(requested, list):
                filtered = {str(s).lower() for s in requested if isinstance(s, str)}
                filtered &= _VALID_SOURCES
                if not filtered:
                    return jsonify({"error": "no valid sources requested"}), 400
                sources = filtered

        try:
            status = _collect_status(sources)
        except Exception as exc:  # never let a WMI hiccup 500 the whole call
            _log(f"hw/status failed: {type(exc).__name__}: {exc}")
            return jsonify({"error": "hw status unavailable"}), 500

        return jsonify({
            "status": "ok",
            "sources_used": status.get("sources", []),
            "cpu": status.get("cpu", {}),
            "gpu": status.get("gpu", {}),
            "fans": status.get("fans", []),
            "power": status.get("power", {}),
            "temperatures": status.get("temperatures", []),
            "acpi_zones": status.get("acpi_zones", []),
            "errors": status.get("errors", {}),
        })

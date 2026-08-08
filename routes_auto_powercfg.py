# Auto-added feature: microsoft/windows (built-in) — PowerCfg
# Description: powercfg.exe — Windows power management CLI: list, query, change power schemes,
#   set active scheme, configure sleep/hibernate settings, report battery health
# Source: Built-in Windows tool at C:\Windows\system32\powercfg.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows power management — enumerate power schemes, query/subgroup settings, set active plan, configure sleep/hibernate/display timeouts, generate battery health report",
    "url": "https://learn.microsoft.com/en-us/windows-hardware/operations/powercfg",
    "added": "2026-07-08",
    "command": "powercfg <list|query|changename|duplicatescheme|delete|setactive|getactivescheme|change|hibernate|sleepstudy|batteryreport>",
}

POWER_PATTERN = re.compile(
    r"Power Scheme GUID:\s+(\S+)\s+\(([^)]+)\)"
)

SUBGROUP_PATTERN = re.compile(
    r"Subgroup GUID:\s+(\S+)\s+\(([^)]*)\)"
)

SETTING_PATTERN = re.compile(
    r"Power Setting GUID:\s+(\S+)\s+\(([^)]*)\)"
)

AC_VALUE_PATTERN = re.compile(r"Current AC Power Setting Index:\s+(0x[0-9a-fA-F]+)")
DC_VALUE_PATTERN = re.compile(r"Current DC Power Setting Index:\s+(0x[0-9a-fA-F]+)")


def _find_powercfg():
    """Locate powercfg.exe — always in system32 on Windows."""
    exe = shutil.which("powercfg") or shutil.which("powercfg.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\powercfg.exe",
        r"C:\Windows\SysWOW64\powercfg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_powercfg_available():
    exe = _find_powercfg()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "/?"], capture_output=True, text=True, timeout=10)
        return result.returncode in (0, 1)  # /? returns 1 on success
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_powercfg(args, timeout=15):
    """Run powercfg with given args, return (stdout, stderr, exit_code)."""
    exe = _find_powercfg()
    if not exe:
        raise RuntimeError("powercfg not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _parse_schemes(text):
    """Parse powercfg /LIST output into structured scheme list."""
    schemes = []
    for line in text.splitlines():
        m = POWER_PATTERN.search(line)
        if m:
            guid, name = m.group(1), m.group(2).strip()
            active = line.strip().endswith("*") or " *" in line
            schemes.append({
                "guid": guid,
                "name": name,
                "active": active,
            })
    return schemes


def _parse_query(text):
    """Parse powercfg /QUERY output into structured settings tree."""
    sections = []
    current_subgroup = None
    current_setting = None

    for line in text.splitlines():
        m = SUBGROUP_PATTERN.search(line)
        if m:
            current_subgroup = {
                "guid": m.group(1),
                "name": m.group(2).strip() if m.group(2) else "",
                "settings": [],
            }
            sections.append(current_subgroup)
            current_setting = None
            continue

        m = SETTING_PATTERN.search(line)
        if m:
            current_setting = {
                "guid": m.group(1),
                "name": m.group(2).strip() if m.group(2) else "",
                "ac_value": None,
                "dc_value": None,
            }
            if current_subgroup:
                current_subgroup["settings"].append(current_setting)
            continue

        if current_setting:
            mac = AC_VALUE_PATTERN.search(line)
            if mac:
                current_setting["ac_value"] = mac.group(1)
            mdc = DC_VALUE_PATTERN.search(line)
            if mdc:
                current_setting["dc_value"] = mdc.group(1)

    return sections


def register_routes(app, state, require_auth):
    @app.route("/auto/powercfg/info", methods=["GET"])
    @require_auth
    def route_auto_powercfg_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/powercfg/ping", methods=["GET"])
    @require_auth
    def route_auto_powercfg_ping():
        exe = _find_powercfg()
        available = _is_powercfg_available() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "powercfg (built-in)",
            "available": available,
            "command": exe or "powercfg",
        })

    @app.route("/auto/powercfg/list", methods=["GET"])
    @require_auth
    def route_auto_powercfg_list():
        """List all power schemes with active indicator."""
        try:
            stdout, stderr, rc = _run_powercfg(["/LIST"])
            if rc != 0:
                return jsonify({"ok": False, "error": stderr.strip() or "powercfg /LIST failed"}), 502
            schemes = _parse_schemes(stdout)
            active = next((s for s in schemes if s["active"]), None)
            return jsonify({
                "ok": True,
                "schemes": schemes,
                "active_scheme": active,
                "count": len(schemes),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "powercfg list timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/powercfg/query", methods=["GET"])
    @require_auth
    def route_auto_powercfg_query():
        """Query current active power scheme settings in detail."""
        try:
            stdout, stderr, rc = _run_powercfg(["/QUERY"])
            if rc != 0:
                return jsonify({"ok": False, "error": stderr.strip() or "powercfg /QUERY failed"}), 502
            sections = _parse_query(stdout)
            return jsonify({
                "ok": True,
                "sections": sections,
                "count": len(sections),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "powercfg query timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/powercfg/set_active", methods=["POST"])
    @require_auth
    def route_auto_powercfg_set_active():
        """Set the active power scheme by GUID."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        guid = body.get("guid", "").strip()
        if not guid:
            return jsonify({"ok": False, "error": _missing_field("guid")}), 400

        # Basic GUID validation
        guid_pattern = r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
        if not re.match(guid_pattern, guid):
            return jsonify({"ok": False, "error": "invalid GUID format"}), 400

        try:
            stdout, stderr, rc = _run_powercfg(["/S", guid])
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "powercfg /S failed",
                }), 502
            return jsonify({
                "ok": True,
                "guid": guid,
                "stdout": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "powercfg set_active timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/powercfg/energy", methods=["GET"])
    @require_auth
    def route_auto_powercfg_energy():
        """Generate energy efficiency report (runs for 60s)."""
        try:
            stdout, stderr, rc = _run_powercfg(["/ENERGY"], timeout=75)
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "note": "Full report saved to energy-report.html in working directory",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "powercfg energy report timed out (takes ~60s to sample)"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/powercfg/battery_report", methods=["GET"])
    @require_auth
    def route_auto_powercfg_battery_report():
        """Generate battery life report (laptops only)."""
        try:
            stdout, stderr, rc = _run_powercfg(["/BATTERYREPORT"], timeout=30)
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "note": "Full report saved to battery-report.html in working directory",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "powercfg battery report timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/powercfg/hibernate", methods=["POST"])
    @require_auth
    def route_auto_powercfg_hibernate():
        """Enable or disable hibernation."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        enable = body.get("enable", None)
        if enable is None:
            return jsonify({"ok": False, "error": _missing_field("enable")}), 400

        try:
            action = "/H" if body.get("mode", "").lower() in ("on", "enable", "yes", "1", "true") else "/H OFF"
            if isinstance(enable, bool):
                action = "/H ON" if enable else "/H OFF"
            args = action.split()
            stdout, stderr, rc = _run_powercfg(args, timeout=15)
            return jsonify({
                "ok": rc == 0,
                "enable": "ON" in action.upper(),
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "powercfg hibernate command timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

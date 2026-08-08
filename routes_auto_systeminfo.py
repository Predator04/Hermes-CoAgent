# Auto-added feature: microsoft/windows (built-in) — SystemInfo
# Description: systeminfo.exe — Windows system information CLI.
#   Query OS version, build, system type, total/free physical and virtual memory,
#   available processors, hotfixes installed, uptime, boot device, and more.
# Source: Built-in Windows tool at C:\Windows\system32\systeminfo.exe

import os
import re
import shutil
import subprocess

from flask import jsonify

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows system information — query OS version, build number, system type, total/free physical and virtual memory, processor count, hotfix list, uptime, boot device, time zone, and detailed configuration",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/systeminfo",
    "added": "2026-07-13",
    "command": "systeminfo [/S system] [/U username] [/FO format]",
}

# Regexes for parsing systeminfo key-value output
KEY_VALUE_RE = re.compile(r"^(.+?):\s+(.+)$")

# Known keys to extract as structured fields
TARGET_KEYS = {
    "OS Name": "os_name",
    "OS Version": "os_version",
    "OS Manufacturer": "os_manufacturer",
    "OS Configuration": "os_configuration",
    "OS Build Type": "os_build_type",
    "Registered Owner": "registered_owner",
    "Registered Organization": "registered_organization",
    "System Manufacturer": "system_manufacturer",
    "System Model": "system_model",
    "System Type": "system_type",
    "Processor(s)": "processors",
    "BIOS Version": "bios_version",
    "Windows Directory": "windows_dir",
    "System Directory": "system_dir",
    "Boot Device": "boot_device",
    "System Locale": "system_locale",
    "Input Locale": "input_locale",
    "Time Zone": "time_zone",
    "Total Physical Memory": "total_physical_mb",
    "Available Physical Memory": "available_physical_mb",
    "Virtual Memory: Max Size": "virtual_memory_max_mb",
    "Virtual Memory: Available": "virtual_memory_available_mb",
    "Virtual Memory: In Use": "virtual_memory_in_use_mb",
    "Page File Location(s)": "page_file_location",
    "Domain": "domain",
    "Logon Server": "logon_server",
    "Hotfix(s)": "hotfix_count",
    "Network Card(s)": "network_cards",
}


def _find_systeminfo():
    """Locate systeminfo.exe — always in system32 on Windows."""
    exe = shutil.which("systeminfo") or shutil.which("systeminfo.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\systeminfo.exe",
        r"C:\Windows\SysWOW64\systeminfo.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_systeminfo_available():
    exe = _find_systeminfo()
    if not exe:
        return False
    try:
        result = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_systeminfo(args, timeout=30):
    """Run systeminfo with given args, return (stdout, stderr, exit_code)."""
    exe = _find_systeminfo()
    if not exe:
        raise RuntimeError("systeminfo not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _parse_systeminfo_output(text):
    """Parse systeminfo key: value output into structured dict."""
    result = {}
    hotfixes = []
    networks = []
    current_section = None
    lines = text.split("\n")

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Check for section headers
        if line_stripped.startswith("Hotfix(s):"):
            current_section = "hotfixes"
            parts = line_stripped.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                try:
                    result["hotfix_count"] = int(parts[1].strip())
                except ValueError:
                    result["hotfix_count"] = parts[1].strip()
            continue

        if line_stripped.startswith("Network Card(s):"):
            current_section = "network"
            parts = line_stripped.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                try:
                    result["network_card_count"] = int(parts[1].strip())
                except ValueError:
                    result["network_card_count"] = parts[1].strip()
            continue

        if current_section == "hotfixes":
            # Parse hotfix entries like "[01]: KB123456"
            if "]" in line_stripped and "KB" in line_stripped:
                hotfixes.append(line_stripped)
            elif KEY_VALUE_RE.match(line_stripped):
                # May be next key-value, go back to general parsing
                current_section = None
            continue

        if current_section == "network":
            if "]" in line_stripped and ":" in line_stripped:
                networks.append(line_stripped)
            elif KEY_VALUE_RE.match(line_stripped):
                current_section = None
            continue

        m = KEY_VALUE_RE.match(line_stripped)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            mapped = TARGET_KEYS.get(key)
            if mapped:
                # Try to convert memory values (e.g., "16,319 MB" -> 16319)
                if "Memory" in key or "Virtual Memory" in key:
                    try:
                        num_str = value.split()[0].replace(",", "")
                        result[mapped] = int(num_str)
                    except (ValueError, IndexError):
                        result[mapped] = value
                elif key == "Hotfix(s)":
                    try:
                        result[mapped] = int(value)
                    except ValueError:
                        result[mapped] = value
                else:
                    result[mapped] = value

    if hotfixes:
        result["hotfix_list"] = hotfixes
    if networks:
        result["network_card_list"] = networks

    return result


def _parse_uptime(text):
    """Extract uptime from systeminfo output."""
    m = re.search(r"System Boot Time:\s+(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def register_routes(app, state, require_auth):

    @app.route("/auto/systeminfo/info", methods=["GET"])
    @require_auth
    def route_auto_systeminfo_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/systeminfo/ping", methods=["GET"])
    @require_auth
    def route_auto_systeminfo_ping():
        exe = _find_systeminfo()
        available = _is_systeminfo_available()
        return jsonify({
            "status": "ok",
            "feature": "microsoft/windows",
            "available": available,
            "command": exe or "systeminfo",
        })

    @app.route("/auto/systeminfo/report", methods=["GET"])
    @require_auth
    def route_auto_systeminfo_report():
        """Get full system information as structured data."""
        exe = _find_systeminfo()
        if not exe:
            return jsonify({"ok": False, "error": "systeminfo not found"}), 503

        try:
            stdout, stderr, rc = _run_systeminfo(["/FO", "LIST"], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "systeminfo failed",
                }), 502

            parsed = _parse_systeminfo_output(stdout)
            boot_time = _parse_uptime(stdout)

            return jsonify({
                "ok": True,
                "system": parsed,
                "boot_time": boot_time,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "systeminfo timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/systeminfo/os", methods=["GET"])
    @require_auth
    def route_auto_systeminfo_os():
        """Get OS-specific information only."""
        exe = _find_systeminfo()
        if not exe:
            return jsonify({"ok": False, "error": "systeminfo not found"}), 503

        try:
            stdout, stderr, rc = _run_systeminfo(["/FO", "LIST"], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "systeminfo failed",
                }), 502

            parsed = _parse_systeminfo_output(stdout)
            os_info = {
                k: parsed.get(k)
                for k in ["os_name", "os_version", "os_manufacturer",
                          "os_configuration", "os_build_type", "registered_owner",
                          "registered_organization", "boot_device", "time_zone"]
                if k in parsed
            }

            return jsonify({
                "ok": True,
                "os_info": os_info,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "systeminfo timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/systeminfo/hardware", methods=["GET"])
    @require_auth
    def route_auto_systeminfo_hardware():
        """Get hardware-specific information only."""
        exe = _find_systeminfo()
        if not exe:
            return jsonify({"ok": False, "error": "systeminfo not found"}), 503

        try:
            stdout, stderr, rc = _run_systeminfo(["/FO", "LIST"], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "systeminfo failed",
                }), 502

            parsed = _parse_systeminfo_output(stdout)
            hw_info = {
                k: parsed.get(k)
                for k in ["system_manufacturer", "system_model", "system_type",
                          "processors", "bios_version", "total_physical_mb",
                          "available_physical_mb", "virtual_memory_max_mb",
                          "virtual_memory_available_mb", "virtual_memory_in_use_mb",
                          "page_file_location"]
                if k in parsed
            }

            # Calculate memory usage percentage
            if "total_physical_mb" in hw_info and "available_physical_mb" in hw_info:
                total = hw_info["total_physical_mb"]
                avail = hw_info["available_physical_mb"]
                if total and total > 0:
                    hw_info["memory_used_pct"] = round(
                        (total - avail) / total * 100, 1
                    )

            return jsonify({
                "ok": True,
                "hardware": hw_info,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "systeminfo timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/systeminfo/hotfixes", methods=["GET"])
    @require_auth
    def route_auto_systeminfo_hotfixes():
        """Get list of installed hotfixes/updates."""
        exe = _find_systeminfo()
        if not exe:
            return jsonify({"ok": False, "error": "systeminfo not found"}), 503

        try:
            stdout, stderr, rc = _run_systeminfo(["/FO", "LIST"], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "systeminfo failed",
                }), 502

            parsed = _parse_systeminfo_output(stdout)
            return jsonify({
                "ok": True,
                "hotfix_count": parsed.get("hotfix_count", 0),
                "hotfixes": parsed.get("hotfix_list", []),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "systeminfo timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

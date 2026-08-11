# Auto-added feature: microsoft/windows (built-in) — ipconfig.exe
# Description: ipconfig.exe — Windows network configuration CLI.
#   Display all TCP/IP network configuration values, refresh DHCP and DNS settings,
#   show detailed adapter information (IP addresses, subnet masks, default gateways,
#   DNS servers, MAC addresses), release/renew IP addresses, flush DNS cache,
#   register DNS with DHCP, and display DNS resolver cache contents.
# Source: Built-in Windows tool at C:\Windows\system32\ipconfig.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows network configuration — display all adapter configurations (IP addresses, subnet masks, default gateways, DNS servers, MAC addresses/WINS servers/DHCP status), release/renew DHCP leases, flush and display DNS resolver cache, register DNS names with DHCP, show DNS resolver cache statistics, and show DHCP class IDs for all adapters",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/ipconfig",
    "added": "2026-07-14",
    "command": "ipconfig [/allcompartments] [/all] [/renew [adapter]] [/release [adapter]] [/flushdns] [/displaydns] [/registerdns] [/showclassid adapter] [/setclassid adapter [classid]]",
}

# Regex for parsing ipconfig /all output
ADAPTER_HEADER_RE = re.compile(r"^(?:\r\n|\n)*\s*Ethernet adapter|Wireless LAN adapter|Bluetooth|Tunnel adapter|Wi-Fi|Local Area Connection|Unknown adapter")
ADAPTER_NAME_RE = re.compile(r"^(Ethernet adapter|Wireless LAN adapter|Bluetooth|Tunnel adapter|Wi-Fi|Local Area Connection|Unknown adapter)\s+(.+?):")
CONNECTION_SPECIFIC_RE = re.compile(r"^\s+Connection-specific DNS Suffix\s+\.\s*:\s+(.+)$")
HOST_NAME_RE = re.compile(r"^\s+Host Name\s+\.\s*:\s+(.+)$")
DNS_SUFFIX_RE = re.compile(r"^\s+Primary Dns Suffix\s+\.\s*:\s+(.+)$")
NODE_TYPE_RE = re.compile(r"^\s+Node Type\s+\.\s*:\s+(.+)$")
ROUTING_ENABLED_RE = re.compile(r"^\s+IP Routing Enabled\s+\.\s*:\s+(.+)$")
WINS_PROXY_RE = re.compile(r"^\s+WINS Proxy Enabled\s+\.\s*:\s+(.+)$")
ADAPTER_KEY_RE = re.compile(r"^\s+(.+?)\s+\.\s*:\s+(.+)$")


def _find_ipconfig():
    """Locate ipconfig.exe."""
    exe = shutil.which("ipconfig") or shutil.which("ipconfig.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\ipconfig.exe",
        r"C:\Windows\SysWOW64\ipconfig.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_ipconfig_available():
    exe = _find_ipconfig()
    if not exe:
        return False
    try:
        result = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_ipconfig(args, timeout=15):
    """Run ipconfig with given args, return (stdout, stderr, exit_code)."""
    exe = _find_ipconfig()
    if not exe:
        raise RuntimeError("ipconfig not found")
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return result.stdout, result.stderr, result.returncode


def _clean_adapter_name(name):
    """Validate an adapter name."""
    n = str(name or "").strip()
    if not n:
        raise ValueError("adapter name must not be empty")
    if len(n) > 256:
        raise ValueError("adapter name too long (max 256 chars)")
    if "\x00" in n:
        raise ValueError("adapter name cannot contain null bytes")
    return n


def _parse_ipconfig_all(text):
    """Parse ipconfig /all output into structured data."""
    result = {}
    host_info = {}
    adapters = []
    current_adapter = None
    lines = text.split("\n")

    for line in lines:
        stripped = line.rstrip("\r")

        # Detect global host info lines
        m = HOST_NAME_RE.match(line)
        if m:
            host_info["host_name"] = m.group(1).strip()
            continue

        m = DNS_SUFFIX_RE.match(line)
        if m:
            host_info["primary_dns_suffix"] = m.group(1).strip()
            continue

        m = NODE_TYPE_RE.match(line)
        if m:
            host_info["node_type"] = m.group(1).strip()
            continue

        m = ROUTING_ENABLED_RE.match(line)
        if m:
            host_info["ip_routing_enabled"] = m.group(1).strip()
            continue

        m = WINS_PROXY_RE.match(line)
        if m:
            host_info["wins_proxy_enabled"] = m.group(1).strip()
            continue

        # Detect adapter header
        m = ADAPTER_NAME_RE.match(line)
        if m:
            if current_adapter:
                adapters.append(current_adapter)
            current_adapter = {
                "interface_type": m.group(1).strip(),
                "name": m.group(2).strip().rstrip(":"),
                "properties": [],
            }
            continue

        # Parse key-value pairs within adapter
        if current_adapter:
            m = ADAPTER_KEY_RE.match(line)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                current_adapter["properties"].append({
                    "key": key,
                    "value": value,
                })

    # Add last adapter
    if current_adapter:
        adapters.append(current_adapter)

    result["host"] = host_info
    result["adapters"] = adapters
    result["adapter_count"] = len(adapters)
    return result


def _parse_dns_cache(text):
    """Parse ipconfig /displaydns output."""
    records = []
    current = {}
    lines = text.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("---"):
            continue

        if stripped.startswith("    ") or stripped.startswith("\t"):
            # Continuation or value line
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                mapped_key = {
                    "Record Name": "record_name",
                    "Record Type": "record_type",
                    "Time To Live": "ttl",
                    "Data Length": "data_length",
                    "Section": "section",
                    "A (Host) Record": "a_record",
                    "AAAA Record": "aaaa_record",
                    "CNAME Record": "cname_record",
                }.get(key, key.lower().replace(" ", "_"))
                current[mapped_key] = value
        else:
            # New record
            if current and ("record_name" in current or "a_record" in current):
                records.append(current)
                current = {}

            # Could be a record name line: "www.example.com"
            # or "----------------------------------------"
            if "---" not in stripped and not stripped.startswith("Record Name"):
                current["record_name"] = stripped

    if current and ("record_name" in current or "a_record" in current):
        records.append(current)

    return records


def register_routes(app, state, require_auth):

    @app.route("/auto/ipconfig/info", methods=["GET"])
    @require_auth
    def route_auto_ipconfig_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/ipconfig/ping", methods=["GET"])
    @require_auth
    def route_auto_ipconfig_ping():
        exe = _find_ipconfig()
        available = _is_ipconfig_available()
        return jsonify({
            "status": "ok",
            "feature": "microsoft/windows",
            "available": available,
            "command": exe or "ipconfig.exe",
        })

    @app.route("/auto/ipconfig/all", methods=["GET"])
    @require_auth
    def route_auto_ipconfig_all():
        """Get full network configuration for all adapters."""
        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        try:
            stdout, stderr, rc = _run_ipconfig(["/all"], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "ipconfig /all failed",
                }), 502

            parsed = _parse_ipconfig_all(stdout)
            return jsonify({
                "ok": True,
                "host": parsed["host"],
                "adapters": parsed["adapters"],
                "adapter_count": parsed["adapter_count"],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /all timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/ipconfig/renew", methods=["POST"])
    @require_auth
    def route_auto_ipconfig_renew():
        """Renew DHCP lease for all adapters or a specific adapter."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        adapter = body.get("adapter", None)

        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        args = ["/renew"]
        if adapter:
            try:
                adapter = _clean_adapter_name(adapter)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            args.append(adapter)

        try:
            stdout, stderr, rc = _run_ipconfig(args, timeout=30)
            return jsonify({
                "ok": rc == 0,
                "adapter": adapter or "all",
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /renew timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/ipconfig/release", methods=["POST"])
    @require_auth
    def route_auto_ipconfig_release():
        """Release DHCP lease for all adapters or a specific adapter."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        adapter = body.get("adapter", None)

        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        args = ["/release"]
        if adapter:
            try:
                adapter = _clean_adapter_name(adapter)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            args.append(adapter)

        try:
            stdout, stderr, rc = _run_ipconfig(args, timeout=30)
            return jsonify({
                "ok": rc == 0,
                "adapter": adapter or "all",
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /release timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/ipconfig/flushdns", methods=["POST"])
    @require_auth
    def route_auto_ipconfig_flushdns():
        """Flush the DNS resolver cache."""
        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        try:
            stdout, stderr, rc = _run_ipconfig(["/flushdns"], timeout=15)
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /flushdns timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/ipconfig/displaydns", methods=["GET"])
    @require_auth
    def route_auto_ipconfig_displaydns():
        """Display the DNS resolver cache contents."""
        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        try:
            stdout, stderr, rc = _run_ipconfig(["/displaydns"], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "ipconfig /displaydns failed",
                }), 502

            records = _parse_dns_cache(stdout)
            return jsonify({
                "ok": True,
                "record_count": len(records),
                "records": records[:200],  # cap at 200 to avoid huge responses
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /displaydns timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/ipconfig/registerdns", methods=["POST"])
    @require_auth
    def route_auto_ipconfig_registerdns():
        """Register DNS names with DHCP and refresh DNS registrations."""
        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        try:
            stdout, stderr, rc = _run_ipconfig(["/registerdns"], timeout=30)
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /registerdns timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/ipconfig/showclassid", methods=["GET"])
    @require_auth
    def route_auto_ipconfig_showclassid():
        """Show DHCP class ID for all adapters or a specific adapter."""
        try:
            from flask import request
            adapter = request.args.get("adapter", "")
        except Exception:
            adapter = ""

        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        args = ["/showclassid"]
        if adapter:
            try:
                adapter = _clean_adapter_name(adapter)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            args.append(adapter)

        try:
            stdout, stderr, rc = _run_ipconfig(args, timeout=15)
            return jsonify({
                "ok": rc == 0,
                "adapter": adapter or "all",
                "output": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /showclassid timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/ipconfig/setclassid", methods=["POST"])
    @require_auth
    def route_auto_ipconfig_setclassid():
        """Set DHCP class ID for a specific adapter."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        adapter = body.get("adapter", "")
        class_id = body.get("class_id", "")

        try:
            adapter = _clean_adapter_name(adapter)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        cid = str(class_id or "").strip()
        if not cid:
            return _missing_field("class_id")
        if len(cid) > 256:
            return jsonify({"ok": False, "error": "class_id too long (max 256 chars)"}), 400

        exe = _find_ipconfig()
        if not exe:
            return jsonify({"ok": False, "error": "ipconfig not found"}), 503

        try:
            stdout, stderr, rc = _run_ipconfig(["/setclassid", adapter, cid], timeout=15)
            return jsonify({
                "ok": rc == 0,
                "adapter": adapter,
                "class_id": cid,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "ipconfig /setclassid timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

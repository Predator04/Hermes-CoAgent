# Auto-added feature: nmap/nmap (13179 stars)
# Description: Nmap is a utility for network discovery, port scanning, OS detection, and security auditing.
# Source: https://github.com/nmap/nmap

import json
import os
import re
import shutil
import subprocess

from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "nmap/nmap",
    "stars": 13179,
    "desc": "Nmap (Network Mapper) is a free and open-source utility for network discovery, port scanning, OS fingerprinting, service/version detection, and security auditing",
    "url": "https://github.com/nmap/nmap",
    "added": "2026-07-12",
    "command": "nmap <target> [options]",
}

# Read-only scan types that are safe for automated use
SAFE_SCAN_TYPES = {
    "ping": "-sn",
    "tcp_syn": "-sS",
    "tcp_connect": "-sT",
    "version": "-sV",
    "os": "-O",
    "aggressive": "-A",
}

# Scan speed templates
SPEED_TEMPLATES = {
    "paranoid": "-T0",
    "sneaky": "-T1",
    "polite": "-T2",
    "normal": "-T3",
    "aggressive": "-T4",
    "insane": "-T5",
}

# Output formats
OUTPUT_FORMATS = ["normal", "xml", "grepable", "json"]


def _find_nmap():
    """Locate nmap binary."""
    candidates = ["nmap", "nmap.exe"]
    for name in candidates:
        exe = shutil.which(name)
        if exe:
            return exe
    for p in [
        r"C:\Program Files (x86)\Nmap\nmap.exe",
        r"C:\Program Files\Nmap\nmap.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_nmap_available():
    exe = _find_nmap()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and "Nmap" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _get_nmap_version():
    exe = _find_nmap()
    if not exe:
        return None
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "Nmap version" in line:
                    return line.strip()
            return result.stdout.split("\n")[0].strip() if result.stdout else None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _validate_target(target):
    """Validate a scan target (hostname, IP, CIDR, range) to prevent injection."""
    if not target or not isinstance(target, str):
        raise ValueError("target must be a non-empty string")
    if len(target) > 256:
        raise ValueError("target too long (max 256 chars)")
    # Allow: hostnames, IPv4, IPv6, CIDR, dash ranges, and common chars
    allowed = re.compile(r'^[a-zA-Z0-9.\-:/_\[\]*,]+$')
    if not allowed.match(target):
        raise ValueError(f"target contains disallowed characters: {target!r}")
    # Block shell metacharacters
    if re.search(r'[;&|`$(){}!<>~]', target):
        raise ValueError("target contains shell metacharacters")
    return target


def _run_nmap(args, timeout=120):
    """Run nmap with args and return (stdout, stderr, exit_code)."""
    exe = _find_nmap()
    if not exe:
        raise RuntimeError("nmap not found")
    nargs = [exe] + args
    result = subprocess.run(
        nargs, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _parse_nmap_grepable(stdout):
    """Parse nmap grepable (-oG) output into structured data."""
    hosts = []
    current_host = {}
    port_lines = []

    for line in stdout.split("\n"):
        line = line.strip()
        if line.startswith("#"):
            continue
        if line.startswith("Host:"):
            if current_host and current_host.get("host"):
                current_host["ports"] = port_lines
                hosts.append(current_host)
                port_lines = []
            current_host = {"host": "", "status": "", "os": ""}
            # Parse: Host: 192.168.1.1 () Status: Up
            parts = line.split("Status:")
            host_part = parts[0].replace("Host:", "").strip() if parts else ""
            # Extract IP
            ip_match = re.search(r'([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', host_part)
            if ip_match:
                current_host["host"] = ip_match.group(1)
            # Also grab hostname in parentheses if present
            hname_match = re.search(r'\(([^)]+)\)', host_part) if parts else None
            if hname_match:
                current_host["hostname"] = hname_match.group(1)
            current_host["status"] = parts[1].strip() if len(parts) > 1 else ""
            # Ports: Ports: 22/open/tcp//ssh///
            ports_match = re.search(r'Ports:\s+(.+)', line)
            if ports_match:
                port_lines = [p.strip() for p in ports_match.group(1).split(",") if p.strip()]
            # OS
            os_match = re.search(r'OS:\s+(.+?)(?:\s+//|$)', line)
            if os_match:
                current_host["os"] = os_match.group(1).strip()
        elif current_host and "Ports:" in line:
            ports_match = re.search(r'Ports:\s+(.+)', line)
            if ports_match:
                port_lines = [p.strip() for p in ports_match.group(1).split(",") if p.strip()]
        elif current_host:
            pass

    if current_host and current_host.get("host"):
        current_host["ports"] = port_lines
        hosts.append(current_host)
    return hosts


def register_routes(app, state, require_auth):
    @app.route("/auto/nmap/info", methods=["GET"])
    @require_auth
    def route_auto_nmap_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/nmap/ping", methods=["GET"])
    @require_auth
    def route_auto_nmap_ping():
        exe = _find_nmap()
        available = _is_nmap_available() if exe else False
        version = _get_nmap_version() if available else None
        return jsonify({
            "ok": True,
            "available": available,
            "version": version,
            "exe": exe,
        })

    @app.route("/auto/nmap/scan", methods=["POST"])
    @require_auth
    def route_auto_nmap_scan():
        """Run a basic nmap scan against a target."""
        body = _json_body(request)
        if body is None:
            return jsonify({"ok": False, "error": "request body must be JSON"}), 400

        target = body.get("target", "")
        scan_type = body.get("scan_type", "ping")
        speed = body.get("speed", "normal")
        ports = body.get("ports", "")
        extra_args = body.get("extra_args", "")

        if not target:
            return jsonify({"ok": False, "error": _missing_field("target")}), 400

        try:
            target = _validate_target(target)

            # Build args
            args = []

            # Scan type
            if scan_type in SAFE_SCAN_TYPES:
                args.append(SAFE_SCAN_TYPES[scan_type])
            else:
                return jsonify({
                    "ok": False,
                    "error": f"unsupported scan_type '{scan_type}'. Valid: {', '.join(SAFE_SCAN_TYPES.keys())}"
                }), 400

            # Speed template
            if speed in SPEED_TEMPLATES:
                args.append(SPEED_TEMPLATES[speed])
            else:
                return jsonify({
                    "ok": False,
                    "error": f"unsupported speed '{speed}'. Valid: {', '.join(SPEED_TEMPLATES.keys())}"
                }), 400

            # Port specification
            if ports:
                port_re = re.compile(r'^[0-9,\-]+$')
                if not port_re.match(ports):
                    return jsonify({"ok": False, "error": "ports must be comma/dash separated numbers"}), 400
                args.append("-p")
                args.append(ports)

            # Extra args — whitelist only safe flags
            if extra_args:
                safe_extra_re = re.compile(r'^-[a-zA-Z0-9]+(?:\s+-[a-zA-Z0-9]+)*$')
                if not safe_extra_re.match(extra_args.strip()):
                    return jsonify({"ok": False, "error": "extra_args must be simple dash-prefixed flags"}), 400
                args.extend(extra_args.strip().split())

            # Output in grepable format for parsing
            args.append("-oG")
            args.append("-")
            args.append(target)

            _log("nmap", f"Scanning {target} ({scan_type}, {speed})")
            stdout, stderr, code = _run_nmap(args, timeout=120)

            # Parse grepable output
            hosts = _parse_nmap_grepable(stdout) if stdout else []
            summary = {
                "target": target,
                "scan_type": scan_type,
                "speed": speed,
                "ports": ports or "default",
                "hosts_found": len(hosts),
                "hosts": hosts,
                "raw_stdout": stdout.strip()[:5000] if stdout else "",
                "stderr": stderr.strip()[:2000] if stderr else "",
                "exit_code": code,
            }

            if code != 0:
                summary["warning"] = f"nmap exited with code {code}"

            return jsonify(summary)

        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "scan timed out (120s max)"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502

    @app.route("/auto/nmap/quick-scan", methods=["POST"])
    @require_auth
    def route_auto_nmap_quick_scan():
        """Quick ping scan to discover live hosts on a subnet."""
        body = _json_body(request)
        if body is None:
            return jsonify({"ok": False, "error": "request body must be JSON"}), 400

        target = body.get("target", "")
        if not target:
            return jsonify({"ok": False, "error": _missing_field("target")}), 400

        try:
            target = _validate_target(target)

            args = ["-sn", "-T4", "-oG", "-", target]
            _log("nmap", f"Quick ping scan: {target}")
            stdout, stderr, code = _run_nmap(args, timeout=60)

            hosts = _parse_nmap_grepable(stdout) if stdout else []
            up_hosts = [h for h in hosts if "Up" in h.get("status", "")]

            return jsonify({
                "ok": True,
                "target": target,
                "hosts_up": len(up_hosts),
                "total_hosts": len(hosts),
                "hosts": up_hosts,
                "exit_code": code,
                "stderr": stderr.strip()[:1000] if stderr else "",
            })
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "quick scan timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502

    @app.route("/auto/nmap/version-scan", methods=["POST"])
    @require_auth
    def route_auto_nmap_version_scan():
        """Version detection scan — identifies service versions on open ports."""
        body = _json_body(request)
        if body is None:
            return jsonify({"ok": False, "error": "request body must be JSON"}), 400

        target = body.get("target", "")
        ports = body.get("ports", "")

        if not target:
            return jsonify({"ok": False, "error": _missing_field("target")}), 400

        try:
            target = _validate_target(target)

            args = ["-sV", "-T4", "--version-intensity", "5", "-oG", "-"]
            if ports:
                port_re = re.compile(r'^[0-9,\-]+$')
                if not port_re.match(ports):
                    return jsonify({"ok": False, "error": "ports must be comma/dash separated numbers"}), 400
                args.extend(["-p", ports])
            args.append(target)

            _log("nmap", f"Version scan: {target}")
            stdout, stderr, code = _run_nmap(args, timeout=180)

            hosts = _parse_nmap_grepable(stdout) if stdout else []

            return jsonify({
                "ok": True,
                "target": target,
                "hosts_found": len(hosts),
                "hosts": hosts,
                "exit_code": code,
                "raw_stdout": stdout.strip()[:8000] if stdout else "",
                "stderr": stderr.strip()[:2000] if stderr else "",
            })
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "version scan timed out (180s max)"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502

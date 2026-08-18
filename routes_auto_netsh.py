# Auto-added feature: microsoft/windows (built-in) — Netsh
# Description: netsh.exe — Windows network shell: Wi-Fi profiles, firewall rules,
#   interface configuration, TCP/IP settings, DNS cache, proxy configuration, routing
# Source: Built-in Windows tool at C:\Windows\system32\netsh.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows network shell — manage Wi-Fi profiles/interfaces, firewall rules (advfirewall), TCP/IP settings, DNS client cache, network interfaces, HTTP settings, network bridge, routing table, proxy configuration",
    "url": "https://learn.microsoft.com/en-us/windows-server/networking/technologies/netsh/netsh-contexts",
    "added": "2026-07-08",
    "command": "netsh <interface|wlan|advfirewall|dnsclient|http|winhttp|bridge>",
}

# Contexts we support
CONTEXTS = [
    "interface",     # Network interfaces, IP, DNS
    "wlan",          # Wi-Fi profiles and connections
    "advfirewall",   # Windows Firewall
    "dnsclient",     # DNS client cache
    "winhttp",       # WinHTTP proxy
    "http",          # HTTP port/reserved URLs
    "bridge",        # Network bridge
    "ras",           # Remote access/RAS
]

# Netsh context and commands that are safe for read-only
READONLY_CONTEXTS = {
    "interface": ["show", "dump"],
    "wlan": ["show"],
    "advfirewall": ["show"],
    "dnsclient": ["show"],
    "winhttp": ["show"],
    "http": ["show"],
    "bridge": ["show"],
}


def _find_netsh():
    """Locate netsh.exe — always in system32 on Windows."""
    exe = shutil.which("netsh") or shutil.which("netsh.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\netsh.exe",
        r"C:\Windows\SysWOW64\netsh.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_netsh_available():
    exe = _find_netsh()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "help"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _clean_context(value):
    """Validate that the requested context is in our allowed list."""
    ctx = str(value or "").strip().lower()
    if ctx not in CONTEXTS:
        raise ValueError(f"unsupported netsh context '{ctx}'. Allowed: {', '.join(CONTEXTS)}")
    return ctx


def _clean_netsh_command(args_list, context_readonly=True):
    """Validate and sanitize netsh arguments to prevent injection.

    Each argument must be alphanumeric, a colon-separated key=value,
    or a common netsh flag (show, set, add, delete, dump, help, ?).
    """
    allowed_tokens_re = re.compile(r'^[a-zA-Z0-9_\-.:=?@/\\+*]+$')
    for arg in args_list:
        if not allowed_tokens_re.match(arg):
            raise ValueError(f"netsh argument contains disallowed characters: {arg!r}")
        if len(arg) > 256:
            raise ValueError(f"netsh argument too long: {len(arg)} chars (max 256)")
        if "\x00" in arg:
            raise ValueError("netsh argument contains null bytes")
    return args_list


def _run_netsh(context, *args, timeout=15):
    """Run netsh <context> <args> and return (stdout, stderr, exit_code)."""
    exe = _find_netsh()
    if not exe:
        raise RuntimeError("netsh not found")
    safe_args = _clean_netsh_command([context] + list(args))
    result = subprocess.run(
        [exe] + safe_args, capture_output=True, text=True, timeout=timeout,
        errors="replace", stdin=subprocess.DEVNULL,
    )
    return result.stdout, result.stderr, result.returncode


def register_routes(app, state, require_auth):
    @app.route("/auto/netsh/info", methods=["GET"])
    @require_auth
    def route_auto_netsh_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/netsh/ping", methods=["GET"])
    @require_auth
    def route_auto_netsh_ping():
        exe = _find_netsh()
        available = _is_netsh_available() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "netsh (built-in)",
            "available": available,
            "command": exe or "netsh",
        })

    @app.route("/auto/netsh/interface/show", methods=["GET"])
    @require_auth
    def route_auto_netsh_interface_show():
        """Show network interface configuration (IP, DNS, interfaces)."""
        try:
            results = {}
            for sub_cmd in ["interface", "interface ip", "interface ipv4", "interface ipv6"]:
                try:
                    parts = sub_cmd.split()
                    stdout, stderr, rc = _run_netsh(*parts, "show", "config", timeout=15)
                    results[sub_cmd.replace(" ", "_")] = stdout.strip() if rc == 0 else stderr.strip()
                except Exception as e:
                    results[sub_cmd] = str(e)

            # Also show interface list
            stdout, stderr, rc = _run_netsh("interface", "show", "interface", timeout=15)
            results["interfaces"] = stdout.strip() if rc == 0 else stderr.strip()

            return jsonify({
                "ok": True,
                "results": results,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/netsh/wifi", methods=["GET"])
    @require_auth
    def route_auto_netsh_wifi():
        """Show Wi-Fi profiles and interfaces."""
        try:
            results = {}
            # Show Wi-Fi interfaces
            try:
                stdout, stderr, rc = _run_netsh("wlan", "show", "interfaces", timeout=15)
                results["interfaces"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["interfaces"] = str(e)

            # Show Wi-Fi profiles
            try:
                stdout, stderr, rc = _run_netsh("wlan", "show", "profiles", timeout=15)
                results["profiles"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["profiles"] = str(e)

            # Show hostednetwork
            try:
                stdout, stderr, rc = _run_netsh("wlan", "show", "hostednetwork", timeout=10)
                results["hosted_network"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["hosted_network"] = str(e)

            return jsonify({
                "ok": True,
                "results": results,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/netsh/wifi/profile", methods=["GET"])
    @require_auth
    def route_auto_netsh_wifi_profile():
        """Get detailed Wi-Fi profile info by name."""
        name = None
        try:
            from flask import request
            name = request.args.get("name", "")
        except Exception:
            pass

        if not name:
            return _missing_field("name (query param)")

        try:
            stdout, stderr, rc = _run_netsh("wlan", "show", "profile", f"name={name}", "key=clear", timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or f"Wi-Fi profile '{name}' not found",
                }), 404
            return jsonify({
                "ok": True,
                "profile_name": name,
                "details": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "netsh wlan profile timed out"}), 504
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/netsh/firewall", methods=["GET"])
    @require_auth
    def route_auto_netsh_firewall():
        """Show Windows Firewall rules and state."""
        try:
            results = {}
            # Firewall state
            try:
                stdout, stderr, rc = _run_netsh("advfirewall", "show", "allprofiles", timeout=15)
                results["profiles_state"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["profiles_state"] = str(e)

            # Global firewall settings
            try:
                stdout, stderr, rc = _run_netsh("advfirewall", "show", "global", timeout=15)
                results["global_settings"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["global_settings"] = str(e)

            # Current firewall state
            try:
                stdout, stderr, rc = _run_netsh("advfirewall", "show", "currentprofile", timeout=15)
                results["current_profile"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["current_profile"] = str(e)

            return jsonify({
                "ok": True,
                "results": results,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/netsh/dns", methods=["GET"])
    @require_auth
    def route_auto_netsh_dns():
        """Show DNS client cache and configuration."""
        try:
            results = {}
            # DNS cache
            try:
                stdout, stderr, rc = _run_netsh("dnsclient", "show", "state", timeout=15)
                results["cache_state"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["cache_state"] = str(e)

            # Show DNSSEC
            try:
                stdout, stderr, rc = _run_netsh("dnsclient", "show", "dnssec", timeout=10)
                results["dnssec"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["dnssec"] = str(e)

            # Show Doh settings
            try:
                stdout, stderr, rc = _run_netsh("dnsclient", "show", "dohset", timeout=10)
                results["doh"] = stdout.strip() if rc == 0 else stderr.strip()
            except Exception as e:
                results["doh"] = str(e)

            return jsonify({
                "ok": True,
                "results": results,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/netsh/proxy", methods=["GET"])
    @require_auth
    def route_auto_netsh_proxy():
        """Show WinHTTP proxy settings."""
        try:
            stdout, stderr, rc = _run_netsh("winhttp", "show", "proxy", timeout=10)
            return jsonify({
                "ok": rc == 0,
                "proxy_config": stdout.strip() if rc == 0 else stderr.strip(),
                "exit_code": rc,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "netsh winhttp proxy timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/netsh/command", methods=["POST"])
    @require_auth
    def route_auto_netsh_command():
        """Run an arbitrary read-only netsh command. Only 'show' and 'dump' subcommands allowed for safety."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        context = body.get("context", "").strip()
        command = body.get("command", "").strip()

        if not context:
            return jsonify({"ok": False, "error": "Missing required field: context"}), 400

        # Validate context
        try:
            context = _clean_context(context)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        # Validate command
        if not command:
            return jsonify({"ok": False, "error": "Missing required field: command"}), 400

        # Only allow show/dump for safety. Default-deny: any context not
        # explicitly listed in READONLY_CONTEXTS (e.g. "ras") is rejected so
        # state-changing subcommands can never slip through.
        cmd_parts = command.split()
        if not cmd_parts:
            return jsonify({"ok": False, "error": "Missing required field: command"}), 400
        allowed = READONLY_CONTEXTS.get(context)
        if not allowed or cmd_parts[0].lower() not in allowed:
            return jsonify({
                "ok": False,
                "error": f"Context '{context}' only allows read-only subcommands: {', '.join(allowed or ['show'])}",
            }), 400

        try:
            stdout, stderr, rc = _run_netsh(context, *cmd_parts, timeout=20)
            return jsonify({
                "ok": rc == 0,
                "context": context,
                "command": command,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "netsh command timed out"}), 504
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

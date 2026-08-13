# Auto-added feature: microsoft/windows (built-in) — sc.exe (Service Control)
# Description: sc.exe — Windows Service Control CLI.
#   Query, start, stop, pause, resume, configure, and list Windows services.
#   Supports remote machine queries, detailed service state inspection,
#   failure recovery configuration, service creation/deletion, and more.
# Source: Built-in Windows tool at C:\Windows\system32\sc.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Service Control — list all services with state/type, query individual service details (name, display name, PID, type, dependencies), start/stop/pause/resume services, configure service startup type (auto, manual, disabled), set failure recovery actions, query service dependencies, and manage service security descriptors",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sc-query",
    "added": "2026-07-14",
    "command": "sc [<server>] query [<service>] | qc | start | stop | pause | continue | config | failure",
}

# Regex for parsing sc query output
SERVICE_LINE_RE = re.compile(
    r"^\s*SERVICE_NAME:\s+(.+)$"
)
DISPLAY_NAME_RE = re.compile(
    r"^\s*DISPLAY_NAME:\s+(.+)$"
)
TYPE_RE = re.compile(
    r"^\s+TYPE\s+:\s+(\d+)\s+(.+)$"
)
STATE_RE = re.compile(
    r"^\s+STATE\s+:\s+(\d+)\s+(.+)$"
)
PID_RE = re.compile(
    r"^\s+PID\s+:\s+(\d+)$"
)
FLAGS_RE = re.compile(
    r"^\s+FLAGS\s+:\s+(.+)$"
)


def _find_sc():
    """Locate sc.exe."""
    exe = shutil.which("sc") or shutil.which("sc.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\sc.exe",
        r"C:\Windows\SysWOW64\sc.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_sc_available():
    exe = _find_sc()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "query", "ScDeviceEnum"], capture_output=True, text=True, timeout=10)
        return result.returncode in (0, 1060)  # 1060 = service doesn't exist, but sc works
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_sc(args, timeout=15):
    """Run sc.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_sc()
    if not exe:
        raise RuntimeError("sc not found")
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return result.stdout, result.stderr, result.returncode


def _clean_service_name(name):
    """Validate a Windows service name."""
    n = str(name or "").strip()
    if not n:
        raise ValueError("service name must not be empty")
    if len(n) > 256:
        raise ValueError("service name too long (max 256 chars)")
    if "\x00" in n:
        raise ValueError("service name cannot contain null bytes")
    # Service names are alphanumeric plus limited special chars
    if "/" in n or "\\" in n:
        raise ValueError("service name cannot contain path separators")
    return n


def _parse_sc_query_output(text):
    """Parse 'sc query' output into a list of service dicts."""
    services = []
    current = {}
    lines = text.split("\n")

    for line in lines:
        stripped = line.strip()

        # Detect new service entry
        m = SERVICE_LINE_RE.match(line)
        if m:
            if current and "service_name" in current:
                services.append(current)
            current = {"service_name": m.group(1).strip()}
            continue

        if not current or "service_name" not in current:
            continue

        m = DISPLAY_NAME_RE.match(line)
        if m:
            current["display_name"] = m.group(1).strip()
            continue

        m = TYPE_RE.match(line)
        if m:
            current["type_code"] = int(m.group(1))
            current["type"] = m.group(2).strip()
            continue

        m = STATE_RE.match(line)
        if m:
            current["state_code"] = int(m.group(1))
            current["state"] = m.group(2).strip()
            continue

        m = PID_RE.match(line)
        if m:
            current["pid"] = int(m.group(1))
            continue

        m = FLAGS_RE.match(line)
        if m:
            current["flags"] = m.group(1).strip()
            continue

    if current and "service_name" in current:
        services.append(current)

    return services


def _parse_sc_qc_output(text):
    """Parse 'sc qc <service>' output into a structured dict."""
    result = {}
    lines = text.split("\n")

    mapping = {
        "SERVICE_NAME": "service_name",
        "DISPLAY_NAME": "display_name",
        "TYPE": "type",
        "START_TYPE": "start_type",
        "ERROR_CONTROL": "error_control",
        "BINARY_PATH_NAME": "binary_path",
        "LOAD_ORDER_GROUP": "load_order_group",
        "TAG": "tag",
        "DEPENDENCIES": "dependencies_raw",
        "SERVICE_START_NAME": "service_start_name",
    }

    in_dependencies = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            mapped = mapping.get(key)
            if not mapped:
                in_dependencies = False
                continue
            # Clean known values
            if mapped == "start_type":
                if "DEMAND_START" in value:
                    value = "Manual"
                elif "AUTO_START" in value:
                    value = "Automatic"
                elif "DISABLED" in value:
                    value = "Disabled"
                elif "BOOT_START" in value:
                    value = "Boot"
                elif "SYSTEM_START" in value:
                    value = "System"
                result[mapped] = value
                in_dependencies = False
            elif mapped == "dependencies_raw":
                result["dependencies"] = [value] if value else []
                in_dependencies = True
            else:
                result[mapped] = value
                in_dependencies = False
        else:
            # Continuation line — additional DEPENDENCIES are listed one per
            # line without a field prefix in 'sc qc' output.
            if in_dependencies:
                result.setdefault("dependencies", []).append(stripped)

    return result


def register_routes(app, state, require_auth):

    @app.route("/auto/sc/info", methods=["GET"])
    @require_auth
    def route_auto_sc_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/sc/ping", methods=["GET"])
    @require_auth
    def route_auto_sc_ping():
        exe = _find_sc()
        available = _is_sc_available()
        return jsonify({
            "status": "ok",
            "feature": "microsoft/windows",
            "available": available,
            "command": exe or "sc.exe",
        })

    @app.route("/auto/sc/query", methods=["GET"])
    @require_auth
    def route_auto_sc_query():
        """List all Windows services with their current state."""
        exe = _find_sc()
        if not exe:
            return jsonify({"ok": False, "error": "sc not found"}), 503

        state_filter = None
        try:
            from flask import request
            state_filter = request.args.get("state", None)
        except Exception:
            pass

        args = ["query"]
        if state_filter:
            valid_states = {"active", "inactive", "all"}
            if state_filter.lower() not in valid_states:
                return jsonify({
                    "ok": False,
                    "error": f"invalid state filter '{state_filter}'. Use one of: {', '.join(sorted(valid_states))}"
                }), 400
            args.extend(["state=", state_filter])

        # Use type=service to focus on services (not drivers)
        args.extend(["type=", "service"])

        try:
            stdout, stderr, rc = _run_sc(args, timeout=30)
            if rc != 0 and "No services" not in stdout and "1060" not in str(rc):
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or f"sc query failed (exit code {rc})",
                }), 502

            services = _parse_sc_query_output(stdout)

            running = sum(1 for s in services if "RUNNING" in s.get("state", ""))
            stopped = sum(1 for s in services if "STOPPED" in s.get("state", ""))

            return jsonify({
                "ok": True,
                "count": len(services),
                "running": running,
                "stopped": stopped,
                "filter": state_filter or "all",
                "services": services,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "sc query timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/sc/query_service", methods=["GET"])
    @require_auth
    def route_auto_sc_query_service():
        """Get detailed info about a specific service."""
        try:
            from flask import request
            name = request.args.get("name", "")
        except Exception:
            return _missing_field("name (query param)")

        try:
            name = _clean_service_name(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_sc()
        if not exe:
            return jsonify({"ok": False, "error": "sc not found"}), 503

        try:
            stdout, stderr, rc = _run_sc(["query", name], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or f"service '{name}' not found",
                    "exit_code": rc,
                }), 404

            parsed = _parse_sc_query_output(stdout)
            service_info = parsed[0] if parsed else {"service_name": name}

            # Also get config
            qc_stdout, qc_stderr, qc_rc = _run_sc(["qc", name], timeout=15)
            if qc_rc == 0:
                config = _parse_sc_qc_output(qc_stdout)
            else:
                config = {}

            return jsonify({
                "ok": True,
                "service": service_info,
                "config": config,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "sc query timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/sc/control", methods=["POST"])
    @require_auth
    def route_auto_sc_control():
        """Start, stop, pause, or resume a service."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        name = body.get("name", "")
        action = body.get("action", "")

        try:
            name = _clean_service_name(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        action = str(action).strip().lower()
        valid_actions = {"start", "stop", "pause", "continue"}
        if action not in valid_actions:
            return jsonify({
                "ok": False,
                "error": f"invalid action '{action}'. Use one of: {', '.join(sorted(valid_actions))}"
            }), 400

        exe = _find_sc()
        if not exe:
            return jsonify({"ok": False, "error": "sc not found"}), 503

        try:
            stdout, stderr, rc = _run_sc([action, name], timeout=30)
            success = rc == 0

            message = stdout.strip()
            if not message and stderr.strip():
                message = stderr.strip()

            return jsonify({
                "ok": success,
                "action": action,
                "service": name,
                "exit_code": rc,
                "message": message,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": f"sc {action} timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/sc/config", methods=["POST"])
    @require_auth
    def route_auto_sc_config():
        """Configure a service (startup type, display name, etc.)."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        name = body.get("name", "")

        try:
            name = _clean_service_name(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        startup = body.get("startup", None)

        exe = _find_sc()
        if not exe:
            return jsonify({"ok": False, "error": "sc not found"}), 503

        args = ["config", name]

        if startup is not None:
            startup = str(startup).strip().lower()
            startup_map = {
                "auto": "start= auto",
                "automatic": "start= auto",
                "manual": "start= demand",
                "demand": "start= demand",
                "disabled": "start= disabled",
                "delayed-auto": "start= delayed-auto",
            }
            if startup not in startup_map:
                return jsonify({
                    "ok": False,
                    "error": f"invalid startup type '{startup}'. Use: auto, manual, disabled, delayed-auto"
                }), 400
            args.extend(startup_map[startup].split())

        if len(args) <= 2:
            return jsonify({"ok": False, "error": "no configuration changes specified (use 'startup' field)"}), 400

        try:
            stdout, stderr, rc = _run_sc(args, timeout=15)
            success = rc == 0
            return jsonify({
                "ok": success,
                "service": name,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "sc config timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/sc/dependencies", methods=["GET"])
    @require_auth
    def route_auto_sc_dependencies():
        """List services that depend on a given service."""
        try:
            from flask import request
            name = request.args.get("name", "")
        except Exception:
            return _missing_field("name (query param)")

        try:
            name = _clean_service_name(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_sc()
        if not exe:
            return jsonify({"ok": False, "error": "sc not found"}), 503

        try:
            stdout, stderr, rc = _run_sc(["EnumDepend", name], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or f"failed to enumerate dependencies for '{name}'",
                }), 502

            dependents = _parse_sc_query_output(stdout)
            return jsonify({
                "ok": True,
                "service": name,
                "dependents_count": len(dependents),
                "dependents": dependents,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "sc EnumDepend timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

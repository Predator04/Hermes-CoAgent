# Auto-added feature: microsoft/windows (built-in) — shutdown.exe
# Description: shutdown.exe — Windows system power management CLI.
#   Shutdown, restart, logoff, hibernate, and abort pending shutdowns.
#   Supports remote machines, custom timeout delays, custom messages,
#   reason codes for logging, and forced shutdowns.
# Source: Built-in Windows tool at C:\Windows\system32\shutdown.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows system power management — shutdown (with delay, message, reason), restart (with delay, message, reason), logoff current session, hibernate/sleep, abort pending shutdown, remote machine shutdown/restart (with credentials), and forced termination of running applications on shutdown",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shutdown",
    "added": "2026-07-15",
    "command": "shutdown [/i | /l | /s | /r | /g | /a | /p | /h | /hybrid] [/f] [/m \\\\<computer>] [/t <seconds>] [/d <p>:<rr>:<c>] [/c <comment>]",
}


def _find_shutdown():
    """Locate shutdown.exe."""
    exe = shutil.which("shutdown") or shutil.which("shutdown.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\shutdown.exe",
        r"C:\Windows\SysWOW64\shutdown.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_shutdown_available():
    exe = _find_shutdown()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "/?"], capture_output=True, text=True, timeout=10)
        return result.returncode in (0, 1)
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_shutdown(args, timeout=30):
    """Run shutdown.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_shutdown()
    if not exe:
        raise RuntimeError("shutdown not found")
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return result.stdout, result.stderr, result.returncode


def _validate_reason_code(reason):
    """Validate a shutdown reason code in the Windows /d format '[p|u:]xx:yy'."""
    r = str(reason or "").strip()
    if not r:
        return None
    parts = r.split(":")
    if len(parts) == 3:
        prefix, major_s, minor_s = parts
        if prefix.lower() not in ("p", "u"):
            raise ValueError("reason prefix must be 'p' (planned) or 'u' (unplanned)")
    elif len(parts) == 2:
        major_s, minor_s = parts
    else:
        raise ValueError("reason code must be in format '[p|u:]xx:yy' (e.g., 'p:0:0' or '0:0')")
    try:
        major = int(major_s)
        minor = int(minor_s)
    except ValueError:
        raise ValueError("reason code parts must be integers")
    if major < 0 or major > 255:
        raise ValueError("major reason must be 0-255")
    if minor < 0 or minor > 65535:
        raise ValueError("minor reason must be 0-65535")
    return r


def _parse_delay(value, default=30):
    try:
        d = int(value)
    except (TypeError, ValueError):
        raise ValueError("delay must be an integer number of seconds")
    if d < 0 or d > 315360000:
        raise ValueError("delay must be between 0 and 315360000 seconds (10 years)")
    return d


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def register_routes(app, state, require_auth):

    @app.route("/auto/shutdown/info", methods=["GET"])
    @require_auth
    def route_auto_shutdown_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/shutdown/ping", methods=["GET"])
    @require_auth
    def route_auto_shutdown_ping():
        exe = _find_shutdown()
        available = _is_shutdown_available()
        return jsonify({
            "status": "ok",
            "feature": "microsoft/windows",
            "available": available,
            "command": exe or "shutdown.exe",
        })

    @app.route("/auto/shutdown/shutdown", methods=["POST"])
    @require_auth
    def route_auto_shutdown_shutdown():
        """Shutdown the system."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        try:
            delay = _parse_delay(body.get("delay", 30))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        force = _parse_bool(body.get("force", False))
        message = str(body.get("message", ""))
        reason = body.get("reason", None)
        remote = str(body.get("remote", ""))

        exe = _find_shutdown()
        if not exe:
            return jsonify({"ok": False, "error": "shutdown not found"}), 503

        args = ["/s", f"/t", str(delay)]
        if force:
            args.append("/f")
        if message:
            if len(message) > 4096:
                return jsonify({"ok": False, "error": "message too long (max 4096 chars)"}), 400
            args.extend(["/c", message])
        if reason:
            try:
                r = _validate_reason_code(reason)
                if r:
                    args.extend(["/d", r])
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
        if remote:
            remote = str(remote).strip()
            if not remote.startswith("\\\\"):
                remote = f"\\\\{remote}"
            args.extend(["/m", remote])

        try:
            stdout, stderr, rc = _run_shutdown(args, timeout=60)
            success = rc == 0
            return jsonify({
                "ok": success,
                "action": "shutdown",
                "delay": delay,
                "force": force,
                "remote": remote or "local",
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip() or f"Shutdown initiated with {delay}s delay",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "shutdown timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/shutdown/restart", methods=["POST"])
    @require_auth
    def route_auto_shutdown_restart():
        """Restart the system."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        try:
            delay = _parse_delay(body.get("delay", 30))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        force = _parse_bool(body.get("force", False))
        message = str(body.get("message", ""))
        reason = body.get("reason", None)
        remote = str(body.get("remote", ""))
        boot_to_firmware = _parse_bool(body.get("boot_to_firmware", False))

        exe = _find_shutdown()
        if not exe:
            return jsonify({"ok": False, "error": "shutdown not found"}), 503

        args = ["/r", f"/t", str(delay)]
        if force:
            args.append("/f")
        if boot_to_firmware:
            args.append("/fw")
        if message:
            if len(message) > 4096:
                return jsonify({"ok": False, "error": "message too long (max 4096 chars)"}), 400
            args.extend(["/c", message])
        if reason:
            try:
                r = _validate_reason_code(reason)
                if r:
                    args.extend(["/d", r])
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
        if remote:
            remote = str(remote).strip()
            if not remote.startswith("\\\\"):
                remote = f"\\\\{remote}"
            args.extend(["/m", remote])

        try:
            stdout, stderr, rc = _run_shutdown(args, timeout=60)
            success = rc == 0
            return jsonify({
                "ok": success,
                "action": "restart",
                "delay": delay,
                "force": force,
                "boot_to_firmware": boot_to_firmware,
                "remote": remote or "local",
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip() or f"Restart initiated with {delay}s delay",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "restart timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/shutdown/logoff", methods=["POST"])
    @require_auth
    def route_auto_shutdown_logoff():
        """Log off the current user session."""
        exe = _find_shutdown()
        if not exe:
            return jsonify({"ok": False, "error": "shutdown not found"}), 503

        try:
            stdout, stderr, rc = _run_shutdown(["/l"], timeout=30)
            success = rc == 0
            return jsonify({
                "ok": success,
                "action": "logoff",
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip() or "Logoff initiated",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "logoff timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/shutdown/hibernate", methods=["POST"])
    @require_auth
    def route_auto_shutdown_hibernate():
        """Hibernate the system."""
        exe = _find_shutdown()
        if not exe:
            return jsonify({"ok": False, "error": "shutdown not found"}), 503

        try:
            stdout, stderr, rc = _run_shutdown(["/h"], timeout=30)
            success = rc == 0
            return jsonify({
                "ok": success,
                "action": "hibernate",
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip() or "Hibernate initiated",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "hibernate timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/shutdown/abort", methods=["POST"])
    @require_auth
    def route_auto_shutdown_abort():
        """Abort a pending shutdown or restart."""
        exe = _find_shutdown()
        if not exe:
            return jsonify({"ok": False, "error": "shutdown not found"}), 503

        try:
            stdout, stderr, rc = _run_shutdown(["/a"], timeout=15)
            success = rc == 0
            return jsonify({
                "ok": success,
                "action": "abort",
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip() or "Pending shutdown aborted",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "abort timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/shutdown/poweroff", methods=["POST"])
    @require_auth
    def route_auto_shutdown_poweroff():
        """Power off the system immediately (no delay, no warning)."""
        exe = _find_shutdown()
        if not exe:
            return jsonify({"ok": False, "error": "shutdown not found"}), 503

        try:
            stdout, stderr, rc = _run_shutdown(["/p"], timeout=30)
            success = rc == 0
            return jsonify({
                "ok": success,
                "action": "poweroff",
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip() or "Power off initiated",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "poweroff timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/shutdown/hybrid_shutdown", methods=["POST"])
    @require_auth
    def route_auto_shutdown_hybrid():
        """Hybrid shutdown (fast startup) — prepares for faster boot."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        try:
            delay = _parse_delay(body.get("delay", 0))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        force = _parse_bool(body.get("force", False))

        exe = _find_shutdown()
        if not exe:
            return jsonify({"ok": False, "error": "shutdown not found"}), 503

        args = ["/s", "/hybrid", f"/t", str(delay)]
        if force:
            args.append("/f")

        try:
            stdout, stderr, rc = _run_shutdown(args, timeout=60)
            success = rc == 0
            return jsonify({
                "ok": success,
                "action": "hybrid_shutdown",
                "delay": delay,
                "force": force,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip() or f"Hybrid shutdown initiated",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "hybrid shutdown timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/shutdown/status", methods=["GET"])
    @require_auth
    def route_auto_shutdown_status():
        """Check if a shutdown is pending, and list last shutdown info."""
        import subprocess as sp
        exe = _find_shutdown()
        available = _is_shutdown_available()

        # Check if shutdown is pending via wevtutil (event log)
        pending = False
        last_shutdown = None
        wevtutil = shutil.which("wevtutil") or shutil.which("wevtutil.exe")
        if wevtutil:
            try:
                # Query system log for recent shutdown events (ID 1074)
                result = sp.run(
                    [wevtutil, "qe", "System", "/q",
                     "*[System[(EventID=1074)]]",
                     "/rd", "true", "/c", "1", "/format:text"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0 and result.stdout.strip():
                    last_shutdown = result.stdout.strip()[:500]
            except Exception:
                pass

        return jsonify({
            "status": "ok",
            "available": available,
            "command": exe or "shutdown.exe",
            "shutdown_pending": pending,
            "last_shutdown_event": last_shutdown,
            "feature": "microsoft/windows",
        })

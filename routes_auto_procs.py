# Auto-added feature: dalance/procs (6131 stars)
# A modern replacement for ps with JSON output — process monitoring made programmatic
# Source: https://github.com/dalance/procs
# Install: winget install procs  OR  scoop install procs

import glob
import shutil
import subprocess
import os
import json
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "dalance/procs",
    "stars": 6131,
    "desc": "procs is a modern replacement for ps written in Rust. It outputs process information with colored terminal output by default, but its killer feature for automation is native JSON output (--json). Filters by name, PID, user, CPU/memory usage, and more. Supports tree view, watch mode, and customizable columns. Perfect for programmatic process monitoring.",
    "url": "https://github.com/dalance/procs",
    "added": "2026-08-12",
    "command": "procs [--json] [--watch] [--tree] [--only-name <name>] [--or] [--sorta cpu|mem] [PID...]",
    "install": {
        "winget": "winget install procs",
        "scoop": "scoop install procs",
    },
    "endpoints": {
        "/auto/procs/info": "Feature metadata, install status, version",
        "/auto/procs/ping": "Health check",
        "/auto/procs/list": "GET — list all processes as JSON (optional filters: name, pid, user)",
        "/auto/procs/tree": "GET — process tree view as JSON",
        "/auto/procs/find": "GET — find process by name/PID with detail",
        "/auto/procs/kill": "POST — kill a process by PID (force option)",
    },
}

def _find_procs():
    """Locate procs on this system."""
    exe = shutil.which("procs")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\procs.exe"),
        os.path.expandvars(r"%USERPROFILE%\.cargo\bin\procs.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _get_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def _parse_procs_json(raw_json):
    """Parse procs JSON output into a list of process dicts with selected fields."""
    try:
        processes = json.loads(raw_json)
        if not isinstance(processes, list):
            _log(f"procs_parse: unexpected JSON shape: {type(processes).__name__}")
            return []
        result = []
        for p in processes:
            if not isinstance(p, dict):
                continue
            entry = {
                "pid": p.get("pid"),
                "ppid": p.get("ppid"),
                "name": p.get("name"),
                "exe": p.get("exe"),
                "cpu_usage": p.get("cpu_usage"),
                "mem_usage": p.get("mem_usage"),
                "vms": p.get("vms"),
                "rss": p.get("rss"),
                "status": p.get("status"),
                "user": p.get("user"),
                "read_bytes": p.get("read_bytes"),
                "write_bytes": p.get("write_bytes"),
                "start_time": p.get("start_time"),
                "tcp_sockets": p.get("tcp_sockets"),
                "udp_sockets": p.get("udp_sockets"),
            }
            # Remove None values for cleaner output
            entry = {k: v for k, v in entry.items() if v is not None}
            result.append(entry)
        return result
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        _log(f"procs_parse: JSON parse error: {e}")
        return []


def register_routes(app, state, require_auth):
    @app.route("/auto/procs/info", methods=["GET"])
    @require_auth
    def route_auto_procs_info():
        info = dict(FEATURE_INFO)
        exe = _find_procs()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/procs/ping", methods=["GET"])
    @require_auth
    def route_auto_procs_ping():
        exe = _find_procs()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "dalance/procs",
            "path": exe,
        })

    @app.route("/auto/procs/list", methods=["GET"])
    @require_auth
    def route_auto_procs_list():
        """List processes as JSON. Optional query params: name, pid, user, limit."""
        exe = _find_procs()
        if not exe:
            return jsonify({
                "error": "procs not installed. Install: winget install procs",
                "processes": [],
                "count": 0,
            }), 200

        name_filter = request.args.get("name", "")
        pid_filter = request.args.get("pid", "")
        user_filter = request.args.get("user", "")
        sort = request.args.get("sort", "cpu")  # cpu or mem
        limit = request.args.get("limit", "")

        try:
            cmd = [exe, "--json"]
            if name_filter:
                cmd.extend(["--only-name", name_filter])
            if sort in ("cpu", "mem"):
                cmd.extend(["--sorta", sort])

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                _log(f"procs_list: procs exited {r.returncode}: {r.stderr.strip()}")
                return jsonify({"error": r.stderr.strip(), "processes": [], "count": 0}), 500

            processes = _parse_procs_json(r.stdout)

            # Apply additional filters that procs CLI doesn't support natively
            if pid_filter:
                try:
                    target_pid = int(pid_filter)
                    processes = [p for p in processes if p.get("pid") == target_pid]
                except ValueError:
                    pass

            if user_filter:
                processes = [p for p in processes if user_filter.lower() in str(p.get("user") or "").lower()]

            total = len(processes)
            if limit:
                try:
                    lim_int = int(limit)
                except ValueError:
                    return jsonify({"error": f"Invalid limit: {limit}", "processes": [], "count": 0}), 400
                if lim_int <= 0:
                    return jsonify({"error": "limit must be positive", "processes": [], "count": 0}), 400
                processes = processes[:lim_int]

            return jsonify({
                "processes": processes,
                "count": len(processes),
                "total_matched": total,
                "filters": {
                    "name": name_filter or None,
                    "pid": pid_filter or None,
                    "user": user_filter or None,
                },
            })
        except subprocess.TimeoutExpired:
            _log("procs_list: procs --json timed out")
            return jsonify({"error": "procs timed out", "processes": [], "count": 0}), 504
        except Exception as e:
            _log(f"procs_list: Error: {e}")
            return jsonify({"error": str(e), "processes": [], "count": 0}), 500

    @app.route("/auto/procs/tree", methods=["GET"])
    @require_auth
    def route_auto_procs_tree():
        """Show processes in tree view with parent-child relationships."""
        exe = _find_procs()
        if not exe:
            return jsonify({
                "error": "procs not installed. Install: winget install procs",
                "processes": [],
                "count": 0,
            }), 200

        name_filter = request.args.get("name", "")

        try:
            cmd = [exe, "--tree", "--json"]
            if name_filter:
                cmd.extend(["--only-name", name_filter])

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                _log(f"procs_tree: procs --tree exited {r.returncode}: {r.stderr.strip()}")
                return jsonify({"error": r.stderr.strip(), "processes": [], "count": 0}), 500

            processes = _parse_procs_json(r.stdout)
            # Build tree structure from flat list with ppid relationships
            by_pid = {p.get("pid"): p for p in processes if p.get("pid")}
            roots = []
            for p in processes:
                ppid = p.get("ppid")
                if ppid and ppid in by_pid:
                    parent = by_pid[ppid]
                    parent.setdefault("children", []).append(p)
                else:
                    roots.append(p)

            return jsonify({
                "processes": roots,
                "count": len(roots),
                "total": len(processes),
            })
        except subprocess.TimeoutExpired:
            _log("procs_tree: procs --tree timed out")
            return jsonify({"error": "procs timed out", "processes": [], "count": 0}), 504
        except Exception as e:
            _log(f"procs_tree: Error: {e}")
            return jsonify({"error": str(e), "processes": [], "count": 0}), 500

    @app.route("/auto/procs/find", methods=["GET"])
    @require_auth
    def route_auto_procs_find():
        """Find a specific process by name or PID. Returns detailed info."""
        exe = _find_procs()
        if not exe:
            return jsonify({
                "error": "procs not installed. Install: winget install procs",
                "found": False,
            }), 200

        name = request.args.get("name", "")
        pid_str = request.args.get("pid", "")

        if not name and not pid_str:
            return jsonify({"error": "Provide ?name=<process> or ?pid=<number>"}), 400

        try:
            cmd = [exe, "--json"]
            if name:
                cmd.extend(["--only-name", name])
                # Use --or to show header even if no match
                cmd.append("--or")

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return jsonify({"error": r.stderr.strip(), "found": False}), 500

            processes = _parse_procs_json(r.stdout)

            if pid_str:
                try:
                    target_pid = int(pid_str)
                    processes = [p for p in processes if p.get("pid") == target_pid]
                except ValueError:
                    return jsonify({"error": f"Invalid PID: {pid_str}", "found": False}), 400

            if not processes:
                return jsonify({
                    "found": False,
                    "query": {"name": name or None, "pid": pid_str or None},
                    "message": "No matching process found",
                })

            return jsonify({
                "found": True,
                "process": processes[0],
                "count": len(processes),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "procs timed out", "found": False}), 504
        except Exception as e:
            _log(f"procs_find: Error: {e}")
            return jsonify({"error": str(e), "found": False}), 500

    @app.route("/auto/procs/kill", methods=["POST"])
    @require_auth
    def route_auto_procs_kill():
        """Kill a process by PID. Optionally force-kill with ?force=1."""
        body = _json_body()
        if body is None:
            body = {}

        pid = body.get("pid") or request.args.get("pid")
        if not pid:
            return jsonify({"error": "Provide 'pid' in JSON body or ?pid=<number>"}), 400

        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            return jsonify({"error": f"Invalid PID: {pid}"}), 400

        if pid_int <= 4 or pid_int in (os.getpid(), os.getppid()):
            return jsonify({
                "error": f"Refusing to kill protected PID {pid_int}",
                "pid": pid_int,
                "success": False,
            }), 400

        force = body.get("force", False) or request.args.get("force") in ("1", "true", "yes")

        try:
            if force:
                # Use taskkill /f for force
                r = subprocess.run(
                    ["taskkill", "/f", "/pid", str(pid_int)],
                    capture_output=True, text=True, timeout=10
                )
            else:
                r = subprocess.run(
                    ["taskkill", "/pid", str(pid_int)],
                    capture_output=True, text=True, timeout=10
                )

            success = r.returncode == 0
            return jsonify({
                "success": success,
                "pid": pid_int,
                "force": force,
                "detail": r.stdout.strip() or r.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "taskkill timed out", "pid": pid_int, "success": False}), 504
        except Exception as e:
            _log(f"procs_kill: Error killing PID {pid_int}: {e}")
            return jsonify({"error": str(e), "pid": pid_int, "success": False}), 500

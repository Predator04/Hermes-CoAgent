# Auto-added feature: fujiapple852/trippy (7459 stars)
# Network diagnostic tool — traceroute with MTR-style analysis, JSON/CSV/pretty output
# Source: https://github.com/fujiapple852/trippy
# Install: winget install trippy  OR  scoop install trippy  OR  cargo install trippy
# CLI: trip -m json -C 5 <target>

import shutil
import subprocess
import json as json_lib

from flask import jsonify, request
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "fujiapple852/trippy",
    "stars": 7459,
    "desc": "Network diagnostic tool combining traceroute and ping with MTR-style analysis. Supports JSON, CSV, pretty, markdown, and stream output modes. Works with ICMP, UDP, and TCP protocols.",
    "url": "https://github.com/fujiapple852/trippy",
    "added": "2026-08-05",
    "command": "trip [OPTIONS] [TARGETS]...",
    "install": {
        "winget": "winget install fujiapple852.trippy",
        "scoop": "scoop install trippy",
        "cargo": "cargo install trippy",
    },
    "modes": [
        "tui      - Interactive terminal UI (default)",
        "stream   - Continuous stream of tracing data",
        "pretty   - Pretty text table report",
        "markdown - Markdown table report",
        "csv      - CSV report",
        "json     - JSON report",
        "dot      - Graphviz DOT output",
        "flows    - Display all flows",
        "silent   - No output, just run",
    ],
    "protocols": ["icmp", "udp", "tcp"],
}


def _find_trip():
    """Locate the trip executable on this system."""
    exe = shutil.which("trip")
    if exe:
        return exe
    # Also check common cargo install location
    import os
    cargo_bin = os.path.expanduser(r"~\.cargo\bin\trip.exe")
    if os.path.isfile(cargo_bin):
        return cargo_bin
    return None


def _run_trip(target, mode="json", cycles=5, protocol="icmp", timeout=30, extra_args=None):
    """Run trippy and return parsed output."""
    exe = _find_trip()
    if not exe:
        return None, "trippy not installed"

    args = [
        exe,
        "-m", mode,
        "-C", str(cycles),
        "-p", protocol,
        "--unprivileged",
    ]
    if extra_args:
        args.extend(extra_args)
    args.append("--")
    args.append(target)

    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=min(timeout, 60),
        )
        return {
            "stdout": r.stdout,
            "stderr": r.stderr,
            "exit_code": r.returncode,
        }, None
    except subprocess.TimeoutExpired:
        return None, f"Trace timed out after {timeout}s"
    except FileNotFoundError:
        return None, "trip executable not found"
    except Exception as e:
        return None, str(e)


def register_routes(app, state, require_auth):
    @app.route("/auto/trippy/info", methods=["GET"])
    @require_auth
    def route_auto_trippy_info():
        info = dict(FEATURE_INFO)
        exe = _find_trip()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            try:
                r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
                info["version"] = r.stdout.strip() or r.stderr.strip()
            except Exception:
                info["version"] = "unknown"
        return jsonify(info)

    @app.route("/auto/trippy/ping", methods=["GET"])
    @require_auth
    def route_auto_trippy_ping():
        exe = _find_trip()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "fujiapple852/trippy",
            "path": exe,
        })

    @app.route("/auto/trippy/trace", methods=["POST"])
    @require_auth
    def route_auto_trippy_trace():
        """Run a network trace to the specified target.
        Body: {"target": "google.com", "mode": "json", "cycles": 5, "protocol": "icmp", "timeout": 30}
        Returns: trace output in the requested format.
        """
        body = _json_body()
        if not body:
            return jsonify({"error": "JSON body required"}), 400
        target = body.get("target", "")
        if not isinstance(target, str):
            return jsonify({"error": "target must be a string"}), 400
        target = target.strip()
        if not target:
            return _missing_field("target")
        if target.startswith("-"):
            return jsonify({"error": "target must not look like a CLI flag"}), 400

        mode = body.get("mode", "json")
        cycles = int(body.get("cycles", 5))
        protocol = body.get("protocol", "icmp")
        timeout = int(body.get("timeout", 30))

        # Validate mode
        valid_modes = {"tui", "stream", "pretty", "markdown", "csv", "json", "dot", "flows", "silent"}
        if mode not in valid_modes:
            return jsonify({"error": f"Invalid mode '{mode}'. Valid: {sorted(valid_modes)}"}), 400

        # Validate protocol
        valid_protocols = {"icmp", "udp", "tcp"}
        if protocol not in valid_protocols:
            return jsonify({"error": f"Invalid protocol '{protocol}'. Valid: {sorted(valid_protocols)}"}), 400

        result, error = _run_trip(target, mode=mode, cycles=cycles, protocol=protocol, timeout=timeout)
        if error:
            if "not installed" in error:
                return jsonify({
                    "error": error,
                    "install_hint": "winget install fujiapple852.trippy",
                }), 503
            return jsonify({"error": error}), 500

        response = {
            "target": target,
            "mode": mode,
            "protocol": protocol,
            "cycles": cycles,
            "exit_code": result["exit_code"],
        }

        if mode == "json":
            try:
                parsed = json_lib.loads(result["stdout"])
                response["data"] = parsed
            except json_lib.JSONDecodeError:
                response["raw"] = result["stdout"]
                response["parse_error"] = "Failed to parse JSON output"
        elif mode in ("csv", "pretty", "markdown", "dot"):
            response["data"] = result["stdout"]
        else:
            response["data"] = result["stdout"]

        if result["stderr"]:
            response["stderr"] = result["stderr"]

        return jsonify(response)

    @app.route("/auto/trippy/targets", methods=["GET"])
    @require_auth
    def route_auto_trippy_targets():
        """Quick multi-target trace (predefined diagnostic targets).
        Returns JSON report for common targets: google.com, cloudflare.com, github.com.
        Query: ?targets=google.com,1.1.1.1  (comma-separated, max 5)
        """
        targets_str = request.args.get("targets", "google.com,cloudflare.com,github.com")
        targets = [t.strip() for t in targets_str.split(",") if t.strip()][:5]
        targets = [t for t in targets if not t.startswith("-")]
        if not targets:
            return jsonify({"error": "No valid targets"}), 400

        results = {}
        errors = {}
        for target in targets:
            result, error = _run_trip(target, mode="json", cycles=3, timeout=25)
            if error:
                errors[target] = error
            else:
                try:
                    results[target] = json_lib.loads(result["stdout"])
                except (json_lib.JSONDecodeError, KeyError):
                    results[target] = {"raw": result.get("stdout", "")}

        return jsonify({
            "results": results,
            "errors": errors,
            "targets_requested": targets,
        })

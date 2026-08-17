# Auto-added feature: mikefarah/yq (15842 stars)
# Portable YAML/JSON/XML/CSV/TSV/TOML/HCL/properties processor (jq for YAML)
# Source: https://github.com/mikefarah/yq
# Install: winget install mikefarah.yq  OR  scoop install yq

import glob
import os
import shutil
import subprocess
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "mikefarah/yq",
    "stars": 15842,
    "desc": "yq is a portable command-line processor for YAML, JSON, XML, CSV, TSV, TOML, HCL and properties. It is the jq-equivalent for structured data — query with jq-style expressions and convert between formats. Perfect for CoAgent to read/write configs and transform API payloads.",
    "url": "https://github.com/mikefarah/yq",
    "added": "2026-08-17",
    "command": "yq [eval] [-p FORMAT] [-o FORMAT] '<expression>' [file]",
    "install": {
        "winget": "winget install mikefarah.yq",
        "scoop": "scoop install yq",
    },
    "endpoints": {
        "/auto/yq/info": "Feature metadata, install status, version",
        "/auto/yq/ping": "Health check",
        "/auto/yq/query": "POST — run a jq-style expression against input",
        "/auto/yq/convert": "POST — convert between YAML/JSON/XML/CSV/TSV/TOML/properties",
    },
}

_VALID_FORMATS = {
    "yaml", "yml", "json", "xml", "csv", "tsv", "toml", "properties", "props", "auto",
}


def _normalize_fmt(fmt):
    """Normalize format aliases to yq's canonical names."""
    fmt = (fmt or "").lower()
    if fmt in ("yml",):
        return "yaml"
    if fmt in ("props",):
        return "properties"
    return fmt


def _find_tool():
    """Locate the yq executable on this system."""
    exe = shutil.which("yq")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\mikefarah.yq_*\yq.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\mikefarah.yq_*\yq_windows_amd64.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\yq.exe"),
        os.path.expandvars(r"%USERPROFILE%\.cargo\bin\yq.exe"),
    ]
    for c in candidates:
        if "*" in c:
            matches = glob.glob(c)
            if matches:
                return matches[0]
        elif os.path.isfile(c):
            return c
    return None


def _get_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip() or "unknown"
    except Exception:
        return "unknown"


def register_routes(app, state, require_auth):

    @app.route("/auto/yq/info", methods=["GET"])
    @require_auth
    def route_auto_yq_info():
        info = dict(FEATURE_INFO)
        exe = _find_tool()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/yq/ping", methods=["GET"])
    @require_auth
    def route_auto_yq_ping():
        exe = _find_tool()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "mikefarah/yq",
            "path": exe,
        })

    @app.route("/auto/yq/query", methods=["POST"])
    @require_auth
    def route_auto_yq_query():
        """Run a jq-style expression against structured input.

        Body (JSON):
            expression (str, required): jq-style expression, e.g. ".items[0].name".
            input (str, optional): Raw text to process via stdin.
            path (str, optional): File to read instead of `input`.
            input_format (str, optional): yaml|json|xml|csv|tsv|toml|properties|auto. Default "auto".
            output_format (str, optional): yaml|json|xml|... Default "json".
        """
        body = _json_body()
        expression = body.get("expression")
        if expression in (None, ""):
            return _missing_field(body, "expression")
        input_text = body.get("input")
        path = body.get("path") or None
        if input_text is None and not path:
            return jsonify({"error": "Either 'input' or 'path' is required"}), 400

        in_fmt = _normalize_fmt(body.get("input_format") or "auto")
        out_fmt = _normalize_fmt(body.get("output_format") or "json")
        if in_fmt not in _VALID_FORMATS:
            return jsonify({"error": f"Unsupported input_format '{in_fmt}'. Choose from {sorted(_VALID_FORMATS)}"}), 400
        if out_fmt not in _VALID_FORMATS:
            return jsonify({"error": f"Unsupported output_format '{out_fmt}'. Choose from {sorted(_VALID_FORMATS)}"}), 400

        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "yq is not installed",
                "hint": "Install with: winget install mikefarah.yq",
            }), 503

        args = ["--input-format", in_fmt, "--output-format", out_fmt, expression]
        if path:
            args.append(path)

        try:
            r = subprocess.run(
                [exe] + args,
                input=(input_text if not path else None),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                _log(f"auto_yq_query: yq exited {r.returncode}: {r.stderr[:300]}")
                return jsonify({"error": r.stderr.strip() or "yq query failed"}), 500
            return jsonify({
                "expression": expression,
                "input_format": in_fmt,
                "output_format": out_fmt,
                "output": r.stdout,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "yq timed out after 60s"}), 504
        except Exception as e:
            _log(f"auto_yq_query exception: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/yq/convert", methods=["POST"])
    @require_auth
    def route_auto_yq_convert():
        """Convert structured data between formats.

        Body (JSON):
            input (str, optional): Raw text to convert via stdin.
            path (str, optional): File to read instead of `input`.
            from (str, required): Source format (yaml|json|xml|csv|tsv|toml|properties).
            to (str, required): Target format (yaml|json|xml|csv|tsv|toml|properties).
        """
        body = _json_body()
        input_text = body.get("input")
        path = body.get("path") or None
        if input_text is None and not path:
            return jsonify({"error": "Either 'input' or 'path' is required"}), 400

        src = _normalize_fmt(body.get("from"))
        dst = _normalize_fmt(body.get("to"))
        if src in (None, "", "auto") or src not in _VALID_FORMATS:
            return jsonify({"error": f"Invalid 'from' format '{body.get('from')}'. Choose from {sorted(_VALID_FORMATS)}"}), 400
        if dst in (None, "", "auto") or dst not in _VALID_FORMATS:
            return jsonify({"error": f"Invalid 'to' format '{body.get('to')}'. Choose from {sorted(_VALID_FORMATS)}"}), 400

        exe = _find_tool()
        if not exe:
            return jsonify({
                "error": "yq is not installed",
                "hint": "Install with: winget install mikefarah.yq",
            }), 503

        args = ["--input-format", src, "--output-format", dst, "."]
        if path:
            args.append(path)

        try:
            r = subprocess.run(
                [exe] + args,
                input=(input_text if not path else None),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                _log(f"auto_yq_convert: yq exited {r.returncode}: {r.stderr[:300]}")
                return jsonify({"error": r.stderr.strip() or "yq convert failed"}), 500
            return jsonify({"from": src, "to": dst, "output": r.stdout})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "yq timed out after 60s"}), 504
        except Exception as e:
            _log(f"auto_yq_convert exception: {e}")
            return jsonify({"error": str(e)}), 500

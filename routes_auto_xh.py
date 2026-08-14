# Auto-added feature: ducaale/xh (8014 stars)
# Friendly and fast HTTP client — a better curl with clean JSON output
# Source: https://github.com/ducaale/xh
# Install: winget install ducaale.xh  OR  scoop install xh

import shutil
import subprocess
import os
import time
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "ducaale/xh",
    "stars": 8014,
    "desc": "xh is a friendly and fast HTTP client (a modern curl replacement) written in Rust. Sends requests with clean, structured output, native JSON support, syntax-highlighted responses, and connection reuse that makes it much faster for repeated requests. Ideal for programmatic HTTP from CoAgent when curl is awkward or when you want prettier output.",
    "url": "https://github.com/ducaale/xh",
    "added": "2026-08-14",
    "command": "xh [METHOD] <URL> [name:value headers] [name==value query] [--timeout N] [--follow]",
    "install": {
        "winget": "winget install ducaale.xh",
        "scoop": "scoop install xh",
    },
    "endpoints": {
        "/auto/xh/info": "Feature metadata, install status, version",
        "/auto/xh/ping": "Health check",
        "/auto/xh/request": "POST — send an HTTP request (method, url, headers, query, body)",
        "/auto/xh/headers": "GET — fetch only response headers for a URL",
    },
}


def _find_xh():
    """Locate xh on this system."""
    exe = shutil.which("xh")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\xh.exe"),
        os.path.expandvars(r"%USERPROFILE%\.cargo\bin\xh.exe"),
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


def _parse_xh_output(raw):
    """Parse xh's default (piped) output into status, headers, and body."""
    normalized = (raw or "").replace("\r\n", "\n")
    if "\n\n" in normalized:
        head, body = normalized.split("\n\n", 1)
    else:
        head, body = normalized, ""
    lines = head.split("\n")
    status_code = None
    if lines and lines[0].startswith("HTTP/"):
        parts = lines[0].split()
        if len(parts) >= 2:
            try:
                status_code = int(parts[1])
            except ValueError:
                status_code = None
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
    return status_code, headers, body


def _build_request_items(body):
    """Convert optional dicts into xh request-item tokens."""
    items = []
    for k, v in (body.get("headers") or {}).items():
        items.append(f"{k}:{v}")
    for k, v in (body.get("query") or {}).items():
        items.append(f"{k}=={v}")
    return items


def register_routes(app, state, require_auth):
    @app.route("/auto/xh/info", methods=["GET"])
    @require_auth
    def route_auto_xh_info():
        info = dict(FEATURE_INFO)
        exe = _find_xh()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/xh/ping", methods=["GET"])
    @require_auth
    def route_auto_xh_ping():
        exe = _find_xh()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "ducaale/xh",
            "path": exe,
        })

    @app.route("/auto/xh/request", methods=["POST"])
    @require_auth
    def route_auto_xh_request():
        """Send an HTTP request.

        Body:
          url:      string (required)
          method:   string (default "GET")
          headers:  dict — request headers (e.g. {"Authorization": "Bearer ..."})
          query:    dict — query-string params
          body:     string — request body (sent via stdin; JSON if content-type set)
          timeout:  int seconds (default 30, max 120)
          follow:   bool — follow redirects (default true)
          verify:   bool — verify TLS certs (default true)
          headers_only: bool — return only response headers
        """
        body = _json_body()
        missing = _missing_field(body, "url")
        if missing:
            return missing

        url = body["url"]
        method = str(body.get("method", "GET")).upper()
        timeout = body.get("timeout", 30)
        follow = bool(body.get("follow", True))
        verify = bool(body.get("verify", True))
        headers_only = bool(body.get("headers_only", False))
        req_body = body.get("body")

        try:
            timeout = int(timeout)
        except (ValueError, TypeError):
            return jsonify({"error": f"Invalid timeout: {body.get('timeout')}"}), 400
        timeout = max(5, min(timeout, 120))

        exe = _find_xh()
        if not exe:
            return jsonify({
                "error": "xh not installed",
                "hint": "Install with: winget install ducaale.xh",
            }), 503

        cmd = [exe, method, url, "--timeout", str(timeout)]
        if follow:
            cmd.append("--follow")
        if not verify:
            cmd.append("--verify")
            cmd.append("no")
        if headers_only:
            cmd.append("--headers")
        cmd.extend(_build_request_items(body))
        if req_body is None:
            cmd.append("--ignore-stdin")

        _log(f"xh_request: {method} {url}")

        try:
            start = time.time()
            r = subprocess.run(
                cmd,
                input=None if req_body is None else str(req_body),
                capture_output=True, text=True, timeout=timeout + 10,
            )
            elapsed_ms = int((time.time() - start) * 1000)

            status_code, headers, parsed_body = _parse_xh_output(r.stdout)

            result = {
                "method": method,
                "url": url,
                "exit_code": r.returncode,
                "elapsed_ms": elapsed_ms,
                "success": r.returncode == 0,
            }
            if headers_only:
                # Output is headers only — status line plus headers
                status_code, headers, _ = _parse_xh_output(r.stdout + "\n\n")
                result["status_code"] = status_code
                result["headers"] = headers
                result["raw_output"] = r.stdout.strip()
            else:
                result["status_code"] = status_code
                result["headers"] = headers
                result["body"] = parsed_body
                result["raw_output"] = r.stdout.strip()

            if r.stderr:
                result["stderr"] = r.stderr.strip()
            return jsonify(result)
        except subprocess.TimeoutExpired:
            _log(f"xh_request: timed out ({timeout}s): {method} {url}")
            return jsonify({
                "error": f"xh timed out after {timeout}s",
                "method": method,
                "url": url,
                "success": False,
            }), 504
        except Exception as e:
            _log(f"xh_request: Error: {e}")
            return jsonify({"error": str(e), "method": method, "url": url, "success": False}), 500

    @app.route("/auto/xh/headers", methods=["GET"])
    @require_auth
    def route_auto_xh_headers():
        """Fetch only the response headers for a URL. Query: ?url=<url>&follow=1"""
        url = request.args.get("url", "")
        if not url:
            return jsonify({"error": "Provide ?url=<url>"}), 400
        follow = request.args.get("follow", "1") in ("1", "true", "yes")
        timeout = request.args.get("timeout", "30")
        try:
            timeout = int(timeout)
        except ValueError:
            return jsonify({"error": f"Invalid timeout: {timeout}"}), 400
        timeout = max(5, min(timeout, 120))

        exe = _find_xh()
        if not exe:
            return jsonify({
                "error": "xh not installed",
                "hint": "Install with: winget install ducaale.xh",
            }), 503

        cmd = [exe, "GET", url, "--headers", "--ignore-stdin", "--timeout", str(timeout)]
        if follow:
            cmd.append("--follow")

        try:
            start = time.time()
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
            elapsed_ms = int((time.time() - start) * 1000)
            status_code, headers, _ = _parse_xh_output(r.stdout + "\n\n")
            return jsonify({
                "url": url,
                "status_code": status_code,
                "headers": headers,
                "elapsed_ms": elapsed_ms,
                "exit_code": r.returncode,
                "raw_output": r.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": f"xh timed out after {timeout}s", "url": url}), 504
        except Exception as e:
            _log(f"xh_headers: Error: {e}")
            return jsonify({"error": str(e), "url": url}), 500

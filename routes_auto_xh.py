# Auto-added feature: ducaale/xh (8014 stars)
# Friendly and fast HTTP client — a better curl with clean JSON output
# Source: https://github.com/ducaale/xh
# Install: winget install ducaale.xh  OR  scoop install xh

import shutil
import subprocess
import os
import time
import json
import ipaddress
import socket
import urllib.parse
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
    """Convert optional dicts into xh request-item tokens.

    Header/query keys and values are sanitised: CR/LF are stripped (they are
    the header-injection / request-smuggling vector) and empty keys are skipped.
    """
    items = []
    for k, v in (body.get("headers") or {}).items():
        key = str(k).replace("\r", "").replace("\n", "").strip()
        val = str(v).replace("\r", "").replace("\n", "")
        if not key:
            continue
        items.append(f"{key}:{val}")
    for k, v in (body.get("query") or {}).items():
        key = str(k).replace("\r", "").replace("\n", "").strip()
        val = str(v).replace("\r", "").replace("\n", "")
        if not key:
            continue
        items.append(f"{key}=={val}")
    return items


_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def _validate_url(url):
    """Validate an outgoing request URL for the xh client.

    Returns an error string on failure, or None if the URL is acceptable.
    Guards against argument injection (leading '-'), non-http schemes, and
    SSRF (loopback / link-local / private / multicast / unspecified targets,
    including DNS-rebinding where the hostname resolves to a blocked address).
    """
    if not isinstance(url, str):
        return "url must be a string"
    url = url.strip()
    if not url:
        return "url is required"
    if url.startswith("-"):
        return "url must not start with '-'"
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "invalid URL"
    if parsed.scheme.lower() not in ("http", "https"):
        return "only http/https URLs are allowed"
    host = parsed.hostname
    if not host:
        return "URL has no hostname"
    host_l = host.lower().rstrip(".")
    if host_l in {"localhost", "metadata", "metadata.google.internal", "0.0.0.0"}:
        return "host is blocked"
    try:
        ip = ipaddress.ip_address(host_l)
    except ValueError:
        # Hostname — resolve and reject if any address is private/loopback/etc.
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return None  # let xh surface the resolution error itself
        for info in infos:
            addr = info[4][0]
            try:
                a = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _is_blocked_ip(a):
                return f"host {host!r} resolves to a blocked address"
        return None
    if _is_blocked_ip(ip):
        return "IP address is blocked"
    return None


def _is_blocked_ip(ip):
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def _redact_url(url):
    """Strip credentials and query values from a URL for safe logging."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    host = p.hostname or ""
    if p.username or p.password:
        host = "***:***@" + host
    query = ""
    if p.query:
        query = "?" + "&".join(
            f"{k}=***" for k, _ in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        )
    return f"{p.scheme}://{host}{p.path}{query}"


def _serialize_body(req_body):
    """Serialize a request body for xh's stdin.

    dict/list become JSON (matching the documented behaviour), everything else
    is passed through as a string. None means no body at all.
    """
    if req_body is None:
        return None
    if isinstance(req_body, (dict, list)):
        return json.dumps(req_body)
    return str(req_body)


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
        url_err = _validate_url(url)
        if url_err:
            return jsonify({"error": f"Invalid url: {url_err}"}), 400
        url = url.strip()
        method = str(body.get("method", "GET")).upper()
        if method not in _ALLOWED_METHODS:
            return jsonify({"error": f"Unsupported method: {method}"}), 400
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

        _log(f"xh_request: {method} {_redact_url(url)}")

        try:
            start = time.time()
            r = subprocess.run(
                cmd,
                input=_serialize_body(req_body),
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
            _log(f"xh_request: timed out ({timeout}s): {method} {_redact_url(url)}")
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
        url_err = _validate_url(url)
        if url_err:
            return jsonify({"error": f"Invalid url: {url_err}"}), 400
        url = url.strip()
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

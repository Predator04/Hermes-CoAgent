"""Fleet mode — register and control multiple CoAgent instances from one hub.

Lets a single CoAgent instance securely register peer CoAgent instances (same
LAN or reachable via tunnel) and forward arbitrary endpoint calls to them, so
one agent can drive the whole fleet ("screenshot the desktop, check the
laptop's process list, then run this on both").

Endpoints:
    POST /fleet/register    — add a peer by URL + token
    POST /fleet/unregister  — remove a peer by name
    GET  /fleet/peers       — list peers with health/latency
    POST /fleet/forward     — forward any endpoint call to a peer
    GET  /fleet/dashboard   — aggregated version/status across all peers
"""

import ipaddress
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log

_PEERS_FILE = COAGENT_DIR / "fleet_peers.json"
_peers = {}          # name -> {"url", "token", "added"}
_lock = threading.Lock()

_MAX_PEER_RESPONSE_BYTES = 8 * 1024 * 1024  # 8 MiB
_ALLOWED_FORWARD_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}

# Hosts that a peer URL must never target: loopback (the hub itself) and
# link-local (cloud metadata 169.254.169.254, etc.).
_FORBIDDEN_PEER_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
)


def _peer_url_blocked(url):
    """Return an error string if a peer URL targets a forbidden host, else None."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "invalid peer URL"
    if parsed.scheme.lower() not in ("http", "https"):
        return "peer URL scheme must be http or https"
    host = parsed.hostname
    if not host:
        return "peer URL has no host"
    try:
        port = parsed.port
    except ValueError:
        return "invalid peer URL port"
    port = port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        infos = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return "peer host does not resolve"
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        # Normalize IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) back to IPv4 so it
        # cannot slip past the loopback/link-local checks below. (ipv4_mapped
        # returns None for non-mapped addresses on some Python versions.)
        if isinstance(addr, ipaddress.IPv6Address):
            mapped = addr.ipv4_mapped
            if mapped is not None:
                addr = mapped
        for net in _FORBIDDEN_PEER_NETS:
            if addr in net:
                return "peer URL targets a forbidden address (%s)" % addr
    return None


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects but re-validate the target and never forward the bearer
    token cross-origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None
        if _peer_url_blocked(newurl):
            return None
        old_host = urllib.parse.urlsplit(req.full_url).hostname
        new_host = urllib.parse.urlsplit(newurl).hostname
        if old_host and new_host and old_host.lower() != new_host.lower():
            if "Authorization" in new_req.headers:
                del new_req.headers["Authorization"]
        return new_req


_PEER_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


def _load():
    global _peers
    try:
        if _PEERS_FILE.exists():
            loaded = json.loads(_PEERS_FILE.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("fleet peers file must be a JSON object")
            # Drop malformed entries (non-dict or missing a string url) so a
            # tampered/legacy file can't crash every peer-touching route later.
            _peers = {
                name: entry
                for name, entry in loaded.items()
                if isinstance(entry, dict) and isinstance(entry.get("url"), str)
            }
    except Exception as exc:
        _log(f"fleet: failed to load peers: {exc}")


def _save():
    try:
        tmp = _PEERS_FILE.with_suffix(".tmp")
        payload = json.dumps(_peers, indent=2)
        # Write with restrictive permissions — the file holds bearer tokens and
        # must never be world-readable.
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        tmp.replace(_PEERS_FILE)
    except Exception as exc:
        _log(f"fleet: failed to save peers: {exc}")


_load()


def _norm_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        url = "http://" + url
    # Only strip trailing slashes when a host/path is present so a bare
    # "http://" is never corrupted into "http:".
    if url.count("/") > 2:
        url = url.rstrip("/")
    return url


def _peer_request(peer, method, path, body=None, timeout=20):
    """Call a peer endpoint. Returns (status, json_or_None, latency_ms, error)."""
    url = _norm_url(peer.get("url"))
    token = peer.get("token") or ""
    if not url:
        return None, None, None, "peer has no URL"
    blocked = _peer_url_blocked(url)
    if blocked:
        return None, None, None, blocked
    if token and any(ord(c) < 32 for c in token):
        return None, None, None, "peer token contains control characters"
    target = url + ("/" + path.lstrip("/") if path else "")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(target, data=payload, headers=headers, method=method.upper())
    start = time.monotonic()
    try:
        with _PEER_OPENER.open(req, timeout=timeout) as resp:
            raw_bytes = resp.read(_MAX_PEER_RESPONSE_BYTES + 1)
            elapsed = round((time.monotonic() - start) * 1000)
            if len(raw_bytes) > _MAX_PEER_RESPONSE_BYTES:
                return resp.status, None, elapsed, "peer response exceeds %d bytes" % _MAX_PEER_RESPONSE_BYTES
            raw = raw_bytes.decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw), elapsed, None
            except json.JSONDecodeError:
                return resp.status, {"raw": raw}, elapsed, None
    except urllib.error.HTTPError as exc:
        elapsed = round((time.monotonic() - start) * 1000)
        return exc.code, None, elapsed, "HTTP %d" % exc.code
    except Exception as exc:
        elapsed = round((time.monotonic() - start) * 1000)
        return None, None, elapsed, str(exc)


def register_routes(app, state, require_auth):
    @app.route("/fleet/register", methods=["POST"])
    @require_auth
    def route_fleet_register():
        data = _json_body() or {}
        name = (data.get("name") or data.get("id") or "").strip()
        url = _norm_url(data.get("url") or data.get("host") or "")
        token = data.get("token") or ""
        if not isinstance(token, str):
            return jsonify({"error": "token must be a string"}), 400
        if not name or not url:
            return jsonify({"error": "name and url are required"}), 400
        # Reject control characters to prevent log-line injection and CRLF
        # header injection when the token is forwarded as a Bearer header.
        if any(ord(c) < 32 for c in name):
            return jsonify({"error": "name must not contain control characters"}), 400
        if any(ord(c) < 32 for c in token):
            return jsonify({"error": "token must not contain control characters"}), 400
        blocked = _peer_url_blocked(url)
        if blocked:
            return jsonify({"error": blocked}), 400
        with _lock:
            _peers[name] = {"url": url, "token": token, "added": int(time.time())}
            _save()
        _log("fleet: registered peer '%s' at %s" % (name, url))
        return jsonify({"status": "registered", "peer": name, "url": url})

    @app.route("/fleet/unregister", methods=["POST"])
    @require_auth
    def route_fleet_unregister():
        data = _json_body() or {}
        name = (data.get("name") or "").strip()
        with _lock:
            removed = _peers.pop(name, None)
            _save()
        if removed is None:
            return jsonify({"error": "no peer named '%s'" % name}), 404
        _log("fleet: unregistered peer '%s'" % name)
        return jsonify({"status": "unregistered", "peer": name})

    @app.route("/fleet/peers", methods=["GET"])
    @require_auth
    def route_fleet_peers():
        with _lock:
            snapshot = [(name, dict(peer)) for name, peer in _peers.items()]
        peers = []
        for name, peer in snapshot:
            status, _, latency, err = _peer_request(peer, "GET", "/ping", timeout=10)
            peers.append({
                "name": name,
                "url": peer.get("url"),
                "online": status == 200,
                "latency_ms": latency,
                "error": err,
                "added": peer.get("added"),
            })
        return jsonify({"peers": peers, "count": len(peers)})

    @app.route("/fleet/forward", methods=["POST"])
    @require_auth
    def route_fleet_forward():
        data = _json_body() or {}
        name = (data.get("peer") or data.get("name") or "").strip()
        method = str(data.get("method") or "GET").upper()
        if method not in _ALLOWED_FORWARD_METHODS:
            return jsonify({"error": "unsupported method %r" % method}), 400
        path = str(data.get("path") or "/")
        if not path.startswith("/") or "://" in path or ".." in path.split("/"):
            return jsonify({"error": "invalid forward path"}), 400
        body = data.get("body")
        with _lock:
            peer = dict(_peers.get(name, {}))
        if not peer:
            return jsonify({"error": "unknown peer '%s'" % name}), 404
        status, result, latency, err = _peer_request(peer, method, path, body)
        if err and status is None:
            return jsonify({"error": "forward failed: %s" % err, "peer": name, "latency_ms": latency}), 502
        return jsonify({
            "peer": name,
            "status": status,
            "latency_ms": latency,
            "result": result,
        })

    @app.route("/fleet/dashboard", methods=["GET"])
    @require_auth
    def route_fleet_dashboard():
        with _lock:
            snapshot = [(name, dict(peer)) for name, peer in _peers.items()]
        rows = []
        for name, peer in snapshot:
            vstatus, vbody, vlat, verr = _peer_request(peer, "GET", "/version", timeout=10)
            pstatus, _, plat, perr = _peer_request(peer, "GET", "/ping", timeout=10)
            version = None
            if vstatus == 200 and isinstance(vbody, dict):
                version = vbody.get("version")
            rows.append({
                "name": name,
                "url": peer.get("url"),
                "online": pstatus == 200,
                "version": version,
                "ping_ms": plat,
                "error": verr or perr,
            })
        return jsonify({"peers": rows, "count": len(rows)})

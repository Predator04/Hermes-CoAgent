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

import json
import threading
import time
import urllib.error
import urllib.request

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log

_PEERS_FILE = COAGENT_DIR / "fleet_peers.json"
_peers = {}          # name -> {"url", "token", "added"}
_lock = threading.Lock()


def _load():
    global _peers
    try:
        if _PEERS_FILE.exists():
            _peers = json.loads(_PEERS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"fleet: failed to load peers: {exc}")


def _save():
    try:
        tmp = _PEERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_peers, indent=2), encoding="utf-8")
        tmp.replace(_PEERS_FILE)
    except Exception as exc:
        _log(f"fleet: failed to save peers: {exc}")


_load()


def _norm_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url.rstrip("/")


def _peer_request(peer, method, path, body=None, timeout=20):
    """Call a peer endpoint. Returns (status, json_or_None, latency_ms, error)."""
    url = _norm_url(peer.get("url"))
    token = peer.get("token") or ""
    if not url:
        return None, None, None, "peer has no URL"
    target = url + ("/" + path.lstrip("/") if path else "")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(target, data=payload, headers=headers, method=method.upper())
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            elapsed = round((time.time() - start) * 1000)
            try:
                return resp.status, json.loads(raw), elapsed, None
            except json.JSONDecodeError:
                return resp.status, {"raw": raw}, elapsed, None
    except urllib.error.HTTPError as exc:
        elapsed = round((time.time() - start) * 1000)
        return exc.code, None, elapsed, "HTTP %d" % exc.code
    except Exception as exc:
        elapsed = round((time.time() - start) * 1000)
        return None, None, elapsed, str(exc)


def register_routes(app, state, require_auth):
    @app.route("/fleet/register", methods=["POST"])
    @require_auth
    def route_fleet_register():
        data = _json_body() or {}
        name = (data.get("name") or data.get("id") or "").strip()
        url = _norm_url(data.get("url") or data.get("host") or "")
        token = data.get("token") or ""
        if not name or not url:
            return jsonify({"error": "name and url are required"}), 400
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
        method = (data.get("method") or "GET").upper()
        path = data.get("path") or "/"
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

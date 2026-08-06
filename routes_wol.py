"""Wake-on-LAN routes."""

import json
import os
import re
import socket
import threading
from pathlib import Path

from flask import jsonify

from shared import COAGENT_DIR, _json_body


CONFIG_DIR = COAGENT_DIR / "config"
MACHINES_FILE = CONFIG_DIR / "wol_machines.json"
_MACHINES_LOCK = threading.Lock()
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-]?[0-9A-Fa-f]{2}){5}$")


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status

def _machines_busy():
    return _error("Wake-on-LAN machine file is busy", 409)


def _normalize_mac(mac):
    if not isinstance(mac, str):
        raise ValueError("mac is required")
    compact = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(compact) != 12 or not _MAC_RE.match(mac):
        raise ValueError("mac must be 12 hex digits, optionally separated by : or -")
    return compact.upper()


def _magic_packet(mac):
    compact = _normalize_mac(mac)
    raw = bytes.fromhex(compact)
    return b"\xff" * 6 + raw * 16


def _load_machines():
    if not MACHINES_FILE.exists():
        return {}
    try:
        data = json.loads(MACHINES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_machines(machines):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = MACHINES_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(machines, indent=2), encoding="utf-8")
    os.replace(str(tmp_file), str(MACHINES_FILE))


def _send_wol(mac, broadcast="255.255.255.255", port=9):
    packet = _magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(3)
        sent = sock.sendto(packet, (broadcast, int(port)))
    return sent


def register_routes(app, state, require_auth):
    @app.route("/wol/list", methods=["POST", "GET"])
    @require_auth
    def route_wol_list():
        if not _MACHINES_LOCK.acquire(blocking=False):
            return _machines_busy()
        try:
            machines = _load_machines()
        finally:
            _MACHINES_LOCK.release()
        return jsonify({"machines": machines, "count": len(machines), "file": str(MACHINES_FILE)})

    @app.route("/wol/save", methods=["POST"])
    @require_auth
    def route_wol_save():
        data = _json_body()
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            return _error("name is required")
        try:
            mac = _normalize_mac(data.get("mac"))
        except ValueError as e:
            return _error(str(e))
        broadcast = str(data.get("broadcast") or data.get("ip") or "255.255.255.255")
        try:
            port = int(data.get("port", 9) if data.get("port") is not None else 9)
        except (ValueError, TypeError):
            return _error("port must be an integer", 400)
        port = max(1, min(port, 65535))
        if not _MACHINES_LOCK.acquire(blocking=False):
            return _machines_busy()
        try:
            machines = _load_machines()
            machines[name.strip()] = {"name": name.strip(), "mac": mac, "broadcast": broadcast, "port": port}
            _save_machines(machines)
            return jsonify({"status": "saved", "machine": machines[name.strip()], "file": str(MACHINES_FILE)})
        finally:
            _MACHINES_LOCK.release()

    @app.route("/wol/delete", methods=["POST"])
    @require_auth
    def route_wol_delete():
        data = _json_body()
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            return _error("name is required")
        if not _MACHINES_LOCK.acquire(blocking=False):
            return _machines_busy()
        try:
            machines = _load_machines()
            key = name.strip()
            machine = machines.pop(key, None)
            if machine is None:
                return _error("saved machine not found", 404)
            _save_machines(machines)
            return jsonify({"status": "deleted", "machine": machine, "count": len(machines), "file": str(MACHINES_FILE)})
        finally:
            _MACHINES_LOCK.release()

    @app.route("/wol/wake", methods=["POST"])
    @require_auth
    def route_wol_wake():
        data = _json_body()
        if not _MACHINES_LOCK.acquire(blocking=False):
            return _machines_busy()
        try:
            machines = _load_machines()
        finally:
            _MACHINES_LOCK.release()
        machine = None
        if data.get("name"):
            machine = machines.get(str(data.get("name")))
            if not machine:
                return _error("saved machine not found", 404)
        mac = data.get("mac") or (machine or {}).get("mac")
        if not mac:
            return _error("mac is required", 400)
        broadcast = data.get("broadcast") or data.get("ip") or (machine or {}).get("broadcast") or "255.255.255.255"
        try:
            port = int(data.get("port") if data.get("port") is not None else (machine or {}).get("port", 9))
        except (ValueError, TypeError):
            return _error("port must be an integer", 400)
        port = max(1, min(port, 65535))
        try:
            sent = _send_wol(mac, str(broadcast), port)
            return jsonify({"status": "sent", "mac": _normalize_mac(mac), "broadcast": broadcast, "port": port, "bytes": sent})
        except Exception as e:
            return jsonify({"error": str(e), "type": type(e).__name__}), 500

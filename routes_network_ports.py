"""Enumerate Windows listening ports with owning process and exposure flag.

Shells out to `netstat -ano` and `tasklist /FO CSV /NH` (both read-only, no
admin needed) to answer two questions in one call: what is listening on a
given port, and which listeners are reachable from off-host. Wildcard binds
(0.0.0.0, *, ::, [::]) are marked `"exposed"` since CoAgent itself typically
binds 0.0.0.0 and the agent needs to spot other LAN-reachable services; pure
loopback binds are marked `"loopback"`; everything else is `"specific"`.

Routes:
  GET /network/ports   -> {ok, count, exposed_count,
                           listeners: [{proto, address, port, pid, process,
                                        exposure}, ...]}
"""

import csv
import io
import subprocess

from flask import Blueprint, jsonify

from shared import _wrap_registered_blueprint_routes, _json_body, _log

bp = Blueprint("network_ports", __name__)

_WILDCARD_ADDRS = {"0.0.0.0", "*", "::", "[::]"}
_LOOPBACK_ADDRS = {"127.0.0.1", "[::1]", "::1"}


def _classify_exposure(address):
    if address in _WILDCARD_ADDRS:
        return "exposed"
    if address in _LOOPBACK_ADDRS:
        return "loopback"
    return "specific"


def _split_addr_port(endpoint):
    """Split 'addr:port' at the LAST colon so IPv6 '[::]:1900' parses right."""
    idx = endpoint.rfind(":")
    if idx < 0:
        return endpoint, None
    addr = endpoint[:idx]
    port_str = endpoint[idx + 1:]
    try:
        port = int(port_str)
    except ValueError:
        return addr, None
    return addr, port


def _build_pid_process_map():
    """Return {pid_int: image_name_str} from `tasklist /FO CSV /NH`.

    Missing PIDs are left out; callers fall back to None.
    """
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    mapping = {}
    if result.returncode != 0:
        return mapping
    reader = csv.reader(io.StringIO(result.stdout))
    for row in reader:
        if len(row) < 2:
            continue
        image = (row[0] or "").strip()
        pid_str = (row[1] or "").strip()
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if image:
            mapping[pid] = image
    return mapping


def _parse_netstat(output):
    """Yield listener dicts from `netstat -ano` output.

    TCP rows look like: `  TCP    0.0.0.0:8080     0.0.0.0:0    LISTENING  1234`
    UDP rows look like: `  UDP    0.0.0.0:5353     *:*                      1234`
    """
    listeners = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        proto = parts[0].upper()
        if proto == "TCP":
            if len(parts) < 5:
                continue
            if parts[3].upper() != "LISTENING":
                continue
            local = parts[1]
            pid_str = parts[4]
        elif proto == "UDP":
            local = parts[1]
            pid_str = parts[-1]
        else:
            continue
        addr, port = _split_addr_port(local)
        if port is None:
            continue
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        listeners.append({
            "proto": proto,
            "address": addr,
            "port": port,
            "pid": pid,
            "exposure": _classify_exposure(addr),
        })
    return listeners


@bp.route("/network/ports", methods=["GET"])
def route_network_ports():
    """Enumerate listening TCP/UDP ports and flag LAN-reachable binds."""
    try:
        netstat = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return _json_body({
            "ok": False,
            "error": "netstat unavailable",
            "code": "NETSTAT_MISSING",
        }, 500)
    except subprocess.TimeoutExpired:
        _log("[network_ports] netstat timed out")
        return _json_body({
            "ok": False,
            "error": "netstat timed out",
            "code": "NETSTAT_TIMEOUT",
        }, 500)
    except Exception as exc:
        _log("[network_ports] netstat failed: {}".format(exc))
        return _json_body({
            "ok": False,
            "error": "netstat failed: {}".format(exc),
            "code": "NETSTAT_FAILED",
        }, 500)

    if netstat.returncode != 0:
        return _json_body({
            "ok": False,
            "error": "netstat returned {}: {}".format(
                netstat.returncode, (netstat.stderr or "").strip()
            ),
            "code": "NETSTAT_FAILED",
        }, 500)

    try:
        listeners = _parse_netstat(netstat.stdout or "")
    except Exception as exc:
        _log("[network_ports] parse failed: {}".format(exc))
        return _json_body({
            "ok": False,
            "error": "netstat parse failed: {}".format(exc),
            "code": "PARSE_FAILED",
        }, 500)

    try:
        pid_map = _build_pid_process_map()
    except FileNotFoundError:
        pid_map = {}
    except subprocess.TimeoutExpired:
        _log("[network_ports] tasklist timed out; proceeding without process names")
        pid_map = {}
    except Exception as exc:
        _log("[network_ports] tasklist failed: {}; proceeding without process names".format(exc))
        pid_map = {}

    for entry in listeners:
        entry["process"] = pid_map.get(entry["pid"])

    listeners.sort(key=lambda e: e["port"])
    exposed_count = sum(1 for e in listeners if e["exposure"] == "exposed")

    return jsonify({
        "ok": True,
        "count": len(listeners),
        "exposed_count": exposed_count,
        "listeners": listeners,
    })


def register_routes(app, state, require_auth):
    from shared import _wrap_registered_blueprint_routes
    app.register_blueprint(bp)
    _wrap_registered_blueprint_routes(app, bp.name, require_auth)

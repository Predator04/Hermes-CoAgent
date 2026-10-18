"""Network status / diagnostics route.

One-shot endpoint that answers the questions an AI agent driving this box
repeatedly needs answered:

  * Am I online right now?
  * What is my public IP?
  * Am I on Wi-Fi or Ethernet (or VPN / cellular)?
  * Which SSID, what signal strength, and is it the expected network?
  * What are my local adapters, IPs, gateways and DNS servers?

Pure stdlib (subprocess + socket + urllib) plus PowerShell on Windows. Every
sub-probe is best-effort and never raises, so the endpoint always returns a
usable JSON document even when the machine is offline.

Routes:
  GET /network            full network status
  GET /network/wifi       Wi-Fi only (SSID, signal, auth)
"""

import json
import socket
import subprocess
import sys

from flask import Blueprint, jsonify

from shared import COAGENT_DIR  # noqa: F401  (kept per route convention)


network_bp = Blueprint("network", __name__)


def _run_ps(script, timeout=15):
    """Run a PowerShell snippet, return (rc, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout, shell=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:  # noqa: BLE001
        return -1, "", "{0}: {1}".format(type(exc).__name__, exc)


def _run_cmd(args, timeout=15):
    """Run an arbitrary command, return (rc, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, shell=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:  # noqa: BLE001
        return -1, "", "{0}: {1}".format(type(exc).__name__, exc)


def _can_reach(host, port, timeout=3):
    """Best-effort TCP connect probe."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _public_ip(timeout=5):
    """Best-effort public egress IP via a few redundant HTTPS endpoints."""
    import urllib.request

    for url in ("https://api.ipify.org", "https://ifconfig.me/ip",
                "https://icanhazip.com"):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                text = resp.read().decode("ascii", "replace").strip()
                if text and len(text) < 64 and not text.isspace():
                    return text
        except Exception:  # noqa: BLE001
            continue
    return None


def _wifi_info():
    """Parse `netsh wlan show interfaces` into a dict. Never raises."""
    if sys.platform != "win32":
        return {}
    rc, out, _ = _run_cmd(["netsh", "wlan", "show", "interfaces"])
    if rc != 0 or not out:
        return {}
    parsed = {}
    for line in out.splitlines():
        line = line.rstrip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key and val:
            parsed[key] = val
    signal = parsed.get("Signal", "")
    try:
        signal_pct = int(signal.rstrip("%"))
    except (ValueError, TypeError):
        signal_pct = None
    return {
        "connected": (parsed.get("State", "").lower() == "connected"),
        "ssid": parsed.get("SSID"),
        "authentication": parsed.get("Authentication"),
        "cipher": parsed.get("Cipher"),
        "radio_type": parsed.get("Radio type"),
        "channel": parsed.get("Channel"),
        "signal_pct": signal_pct,
        "receive_mbps": parsed.get("Receive rate (Mbps)"),
        "transmit_mbps": parsed.get("Transmit rate (Mbps)"),
    }


def _adapters():
    """Enumerate network adapters via PowerShell JSON. Never raises."""
    if sys.platform != "win32":
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$adapters = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object {"
        "  $ip = Get-NetIPConfiguration -InterfaceIndex $_.ifIndex -ErrorAction SilentlyContinue;"
        "  $ipif = Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue;"
        "  [PSCustomObject]@{"
        "    name=$_.Name; ifIndex=$_.ifIndex; status=$_.Status;"
        "    mac=$_.MacAddress; mediaType=$_.MediaType; linkSpeed=$_.LinkSpeed;"
        "    ip=@($ip.IPv4Address | ForEach-Object { $_.IPAddress });"
        "    gateway=@($ip.IPv4DefaultGateway | ForEach-Object { $_.NextHop });"
        "    dns=@($ip.DNSServer | Where-Object { $_.AddressFamily -eq 2 } | ForEach-Object { $_.ServerAddresses });"
        "    dhcp=($ipif.Dhcp)"
        "  }"
        "};"
        "@($adapters) | ConvertTo-Json -Depth 5 -Compress"
    )
    rc, out, err = _run_ps(script)
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):  # single adapter -> wrap
        data = [data]
    if not isinstance(data, list):
        return []
    adapters = []
    _DHCP_MAP = {0: "static", 1: "dhcp", 2: "unconfigured"}
    for a in data:
        if not isinstance(a, dict):
            continue
        dhcp_raw = a.get("dhcp")
        if isinstance(dhcp_raw, int):
            dhcp = _DHCP_MAP.get(dhcp_raw, "unknown")
        else:
            dhcp = dhcp_raw
        adapters.append({
            "name": a.get("name"),
            "ifIndex": a.get("ifIndex"),
            "status": a.get("status"),
            "mac": a.get("mac"),
            "media_type": a.get("mediaType"),
            "link_speed": a.get("linkSpeed"),
            "ip": [x for x in (a.get("ip") or []) if x],
            "gateway": [x for x in (a.get("gateway") or []) if x],
            "dns": [x for x in (a.get("dns") or []) if x],
            "dhcp": dhcp,
        })
    return adapters


def _connection_type(wifi, adapters):
    if wifi.get("connected"):
        return "wifi"
    for a in adapters:
        name = (a.get("name") or "").lower()
        media = (a.get("media_type") or "").lower()
        if a.get("gateway"):
            if "ethernet" in media or "802.3" in media or "ethernet" in name:
                return "ethernet"
            if "bluetooth" in name or "bluetooth" in media:
                return "bluetooth"
            return "ethernet"
    for a in adapters:
        name = (a.get("name") or "").lower()
        if "vpn" in name or "tunnel" in name or "tap" in name:
            return "vpn"
    if adapters:
        return "connected"
    return "none"


def _collect():
    wifi = _wifi_info()
    adapters = _adapters()
    public_ip = _public_ip()
    # Internet is "reachable" if we got a public IP, else try a raw TCP probe.
    internet = bool(public_ip) or _can_reach("1.1.1.1", 443) or _can_reach("8.8.8.8", 53)
    has_gateway = any(a.get("gateway") for a in adapters)
    return {
        "internet": internet,
        "public_ip": public_ip,
        "connection_type": _connection_type(wifi, adapters),
        "has_default_gateway": has_gateway,
        "wifi": wifi,
        "adapters": adapters,
    }


@network_bp.route("/network", methods=["GET"])
def route_network():
    data = _collect()
    return jsonify({"ok": True, **data})


@network_bp.route("/network/wifi", methods=["GET"])
def route_network_wifi():
    return jsonify({"ok": True, "wifi": _wifi_info()})


def register_routes(app, state, require_auth):
    app.register_blueprint(network_bp)
    from shared import _wrap_registered_blueprint_routes
    _wrap_registered_blueprint_routes(app, network_bp.name, require_auth)

"""Capability discovery / integration manifest (issue #5).

Exposes a machine-readable manifest of what this CoAgent host can actually do:
every route family, its endpoints, and whether the Python deps / external CLI
tools it relies on are present. Lets an orchestrator plan around what is
installed instead of discovering gaps via mid-task 404s.
"""
import importlib.util
import logging
import shutil

from flask import Blueprint, jsonify

from shared import VERSION, BUILD

_LOGGER = logging.getLogger(__name__)
discover_bp = Blueprint("discover", __name__)

# Route-prefix -> human description of the capability group.
_GROUP_DESCRIPTIONS = {
    "mouse": "Mouse movement, clicks, drags",
    "keyboard": "Keyboard typing and key presses",
    "screen": "Screen capture and monitor info",
    "ocr": "On-screen text recognition",
    "uia": "Windows UI Automation tree access",
    "file": "Sandboxed file read/write",
    "process": "Process listing and control",
    "browser": "Browser automation",
    "recorder": "Action recording and replay",
    "macro": "Macro building and verification",
    "voice": "Voice command capture",
    "approvals": "Human-in-the-loop approval gate",
    "tunnel": "Public tunnel (ngrok/cloudflare)",
    "auto": "Wrapped Windows CLI tools",
}

# Capability group -> {"deps": [python modules], "tools": [PATH executables]}.
# A group is "available" when all listed deps import and all tools resolve.
_GROUP_REQUIREMENTS = {
    "ocr": {"deps": ["pytesseract"], "tools": ["tesseract"]},
    "uia": {"deps": ["comtypes"], "tools": []},
    "browser": {"deps": ["playwright"], "tools": []},
    "voice": {"deps": ["speech_recognition"], "tools": []},
    "auto/netsh": {"deps": [], "tools": ["netsh"]},
    "auto/nmap": {"deps": [], "tools": ["nmap"]},
    "auto/imagemagick": {"deps": [], "tools": ["magick", "convert"]},
    "tunnel": {"deps": [], "tools": ["ngrok", "cloudflared"]},
}


def _dep_present(module_name):
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _tool_present(name):
    return shutil.which(name) is not None


def _requirement_status(reqs):
    """Return (available, detail) for a requirements spec.

    Tools are satisfied if ANY listed executable resolves (alternatives like
    magick/convert); deps are satisfied only if ALL import.
    """
    deps = reqs.get("deps", [])
    tools = reqs.get("tools", [])
    dep_map = {d: _dep_present(d) for d in deps}
    tool_ok = (not tools) or any(_tool_present(t) for t in tools)
    tool_map = {t: _tool_present(t) for t in tools}
    available = all(dep_map.values()) and tool_ok
    return available, {"deps": dep_map, "tools": tool_map}


def _group_for_rule(rule_path):
    parts = [p for p in rule_path.split("/") if p]
    if not parts:
        return None
    if parts[0] == "auto" and len(parts) >= 2:
        return f"auto/{parts[1]}"
    return parts[0]


def build_manifest(url_map):
    """Build the capability manifest from a Werkzeug url_map.

    Pure function of the url_map so it can be unit-tested without a live app.
    """
    groups = {}
    for rule in url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        group = _group_for_rule(str(rule.rule))
        if not group:
            continue
        methods = sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})
        entry = groups.setdefault(group, {"endpoints": []})
        entry["endpoints"].append({"path": str(rule.rule), "methods": methods})

    manifest = []
    for group in sorted(groups):
        endpoints = sorted(groups[group]["endpoints"], key=lambda e: e["path"])
        reqs = _GROUP_REQUIREMENTS.get(group)
        if reqs is not None:
            available, detail = _requirement_status(reqs)
        else:
            available, detail = True, {"deps": {}, "tools": {}}
        base = group.split("/")[0]
        manifest.append({
            "group": group,
            "description": _GROUP_DESCRIPTIONS.get(group) or _GROUP_DESCRIPTIONS.get(base) or "",
            "available": available,
            "requirements": detail,
            "endpoint_count": len(endpoints),
            "endpoints": endpoints,
        })
    return manifest


def register_routes(app, state, require_auth):
    @app.route("/discover", methods=["GET"])
    @require_auth
    def route_discover():
        manifest = build_manifest(app.url_map)
        return jsonify({
            "ok": True,
            "agent": "Hermes CoAgent",
            "version": VERSION,
            "build": BUILD,
            "group_count": len(manifest),
            "available_groups": sorted(g["group"] for g in manifest if g["available"]),
            "unavailable_groups": sorted(g["group"] for g in manifest if not g["available"]),
            "groups": manifest,
        })

    @app.route("/capabilities", methods=["GET"])
    @require_auth
    def route_capabilities():
        manifest = build_manifest(app.url_map)
        return jsonify({"ok": True, "version": VERSION, "groups": manifest})

    _LOGGER.info("Discover/capabilities routes registered")

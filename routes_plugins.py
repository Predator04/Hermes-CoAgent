"""Hot-loadable plugin routes."""

import importlib
import re
import sys
import threading
import time
from pathlib import Path

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log


PLUGINS_DIR = COAGENT_DIR / "plugins"
_SAFE_PLUGIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
_LOCK = threading.RLock()
PLUGINS = {}
PLUGIN_ENDPOINTS = {}


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _safe_name(name):
    if not isinstance(name, str):
        raise ValueError("plugin name must be a valid Python module filename")
    safe = name[:-3] if name.endswith(".py") else name
    if not _SAFE_PLUGIN.match(safe):
        raise ValueError("plugin name must be a valid Python module filename")
    return safe


def _plugin_path(name):
    safe = _safe_name(name)
    path = (PLUGINS_DIR / f"{safe}.py").resolve()
    try:
        path.relative_to(PLUGINS_DIR.resolve())
    except ValueError:
        raise ValueError("plugin path escapes plugins directory")
    return safe, path


def _repo_hash():
    try:
        import subprocess
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(COAGENT_DIR), capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return None


def _active_summary():
    rows = {}
    for name, (module, loaded_at) in PLUGINS.items():
        rows[name] = {
            "name": name,
            "module": getattr(module, "__name__", name),
            "loaded_at": loaded_at,
            "endpoints": PLUGIN_ENDPOINTS.get(name, []),
        }
    return rows


def _scan_plugins():
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(PLUGINS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        active = PLUGINS.get(path.stem)
        rows.append({
            "name": path.stem,
            "file": str(path),
            "bytes": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "loaded": bool(active),
            "loaded_at": active[1] if active else None,
            "endpoints": PLUGIN_ENDPOINTS.get(path.stem, []) if active else [],
        })
    return rows


def _remove_endpoints(app, endpoints):
    endpoint_set = set(endpoints)
    for endpoint in endpoint_set:
        app.view_functions.pop(endpoint, None)
    try:
        app.url_map._rules = [rule for rule in app.url_map._rules if rule.endpoint not in endpoint_set]
        for endpoint in endpoint_set:
            app.url_map._rules_by_endpoint.pop(endpoint, None)
        app.url_map._remap = True
    except Exception:
        pass


def _audit_plugin_endpoints(app, plugin_name, endpoints):
    rows = []
    unauthenticated = []
    for endpoint in endpoints:
        view_func = app.view_functions.get(endpoint)
        auth_wrapped = bool(getattr(view_func, "_hermes_auth_wrapped", False))
        rules = sorted(str(rule) for rule in app.url_map.iter_rules() if rule.endpoint == endpoint)
        auth_status = "require_auth" if auth_wrapped else "missing_require_auth_marker"
        rows.append({
            "endpoint": endpoint,
            "rules": rules,
            "auth_status": auth_status,
        })
        _log(f"[plugins] {plugin_name} endpoint={endpoint} routes={rules} auth_status={auth_status}")
        if not auth_wrapped:
            unauthenticated.append(endpoint)
            _log(f"[plugins] WARNING: {plugin_name} endpoint {endpoint} lacks require_auth protection")
    return rows, unauthenticated


def _load_plugin(app, state, require_auth, name):
    safe, path = _plugin_path(name)
    if not path.exists():
        raise FileNotFoundError(str(path))
    module_name = f"hermes_plugin_{safe}"
    if safe in PLUGINS:
        _unload_plugin(app, safe)
    before_endpoints = set(app.view_functions.keys())
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "register_routes"):
        sys.modules.pop(module_name, None)
        raise AttributeError("plugin must define register_routes(app, state, require_auth)")
    got_first_request = getattr(app, "_got_first_request", False)
    try:
        app._got_first_request = False
        module.register_routes(app, state, require_auth)
    finally:
        app._got_first_request = got_first_request
    endpoints = sorted(set(app.view_functions.keys()) - before_endpoints)
    endpoint_auth, unauthenticated = _audit_plugin_endpoints(app, safe, endpoints)
    loaded_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    PLUGINS[safe] = (module, loaded_at)
    PLUGIN_ENDPOINTS[safe] = endpoints
    info = {
        "name": safe,
        "module_name": module_name,
        "file": str(path),
        "loaded_at": loaded_at,
        "loaded_git_hash": _repo_hash(),
        "endpoints": endpoints,
        "endpoint_auth": endpoint_auth,
        "unauthenticated_endpoints": unauthenticated,
    }
    return info


def _unload_plugin(app, name):
    safe = _safe_name(name)
    loaded = PLUGINS.pop(safe, None)
    if not loaded:
        return None
    module, loaded_at = loaded
    endpoints = PLUGIN_ENDPOINTS.pop(safe, [])
    _remove_endpoints(app, endpoints)
    sys.modules.pop(getattr(module, "__name__", safe), None)
    info = {
        "name": safe,
        "module_name": getattr(module, "__name__", safe),
        "loaded_at": loaded_at,
        "endpoints": endpoints,
    }
    return info


def register_routes(app, state, require_auth):
    @app.route("/plugins/list", methods=["POST", "GET"])
    @require_auth
    def route_plugins_list():
        with _LOCK:
            return jsonify({"plugins": _scan_plugins(), "active": _active_summary(), "directory": str(PLUGINS_DIR)})

    @app.route("/plugins/scan", methods=["POST", "GET"])
    @require_auth
    def route_plugins_scan():
        with _LOCK:
            plugins = _scan_plugins()
        return jsonify({"status": "scanned", "plugins": plugins, "count": len(plugins), "directory": str(PLUGINS_DIR)})

    @app.route("/plugins/load/<name>", methods=["POST"])
    @require_auth
    def route_plugins_load(name):
        with _LOCK:
            try:
                info = _load_plugin(app, state, require_auth, name)
            except FileNotFoundError as e:
                return _error("plugin not found", 404, file=str(e))
            except Exception as e:
                return jsonify({"error": str(e), "type": type(e).__name__}), 500
        return jsonify({"status": "loaded", "plugin": info})

    @app.route("/plugins/unload/<name>", methods=["POST"])
    @require_auth
    def route_plugins_unload(name):
        with _LOCK:
            try:
                info = _unload_plugin(app, name)
            except Exception as e:
                return jsonify({"error": str(e), "type": type(e).__name__}), 500
        if not info:
            return _error("plugin is not loaded", 404)
        return jsonify({"status": "unloaded", "plugin": info})

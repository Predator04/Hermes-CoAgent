"""Hybrid UIA-First Agent Loop routes.

Resolution order: UIA tree -> OCR -> SOM Vision.
Caches UIA snapshots for 500ms and tracks which backend satisfied each request.
"""

import logging
import threading
import time

from flask import Blueprint, jsonify, request
from shared import _self_port

_LOGGER = logging.getLogger(__name__)


hybrid_agent_bp = Blueprint("hybrid_agent_gateway", __name__)


_UIA_CACHE_LOCK = threading.Lock()
_UIA_CACHE: dict = {}
_UIA_CACHE_TTL_SECONDS = 0.5

_STATS_LOCK = threading.Lock()
_HYBRID_STATS = {
    "uia_hits": 0,
    "ocr_hits": 0,
    "som_hits": 0,
    "misses": 0,
    "total_requests": 0,
    "failures": 0,
}

_LAST_METHOD_LOCK = threading.Lock()
_LAST_METHOD_USED = {
    "find": None,
    "act": None,
    "type": None,
    "plan_and_execute": None,
}


def _debug_failure(context, exc):
    _LOGGER.debug("%s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _bump_stat(key):
    with _STATS_LOCK:
        _HYBRID_STATS[key] = _HYBRID_STATS.get(key, 0) + 1


def _set_last_method(action, method):
    with _LAST_METHOD_LOCK:
        _LAST_METHOD_USED[action] = method


def _get_uia_tree():
    """Lazy import uia_engine and fetch a UIA snapshot (cached 500ms)."""
    try:
        from uia_engine import uia_snapshot
    except Exception as exc:
        _debug_failure("uia_engine import", exc)
        return None

    cache_key = "__global_uia__"
    now = time.monotonic()
    with _UIA_CACHE_LOCK:
        entry = _UIA_CACHE.get(cache_key)
        if entry and (now - entry["ts"]) < _UIA_CACHE_TTL_SECONDS:
            return entry["tree"]

    try:
        tree = uia_snapshot()
    except Exception as exc:
        _debug_failure("uia_snapshot", exc)
        return None

    if tree:
        with _UIA_CACHE_LOCK:
            _UIA_CACHE[cache_key] = {"tree": tree, "ts": now}
    return tree


def _invalidate_uia_cache():
    with _UIA_CACHE_LOCK:
        _UIA_CACHE.clear()


def _ocr_find_text(query):
    """Lazy import routes_ocr.ocr_find_text and search."""
    try:
        from routes_ocr import ocr_find_text
    except Exception as exc:
        _debug_failure("routes_ocr import", exc)
        return None
    try:
        return ocr_find_text(query)
    except Exception as exc:
        _debug_failure("ocr_find_text", exc)
        return None


def _get_som_overlay():
    """Lazy import uia_engine.som_overlay and capture a screenshot overlay."""
    try:
        from uia_engine import som_overlay
    except Exception as exc:
        _debug_failure("uia_engine.som_overlay import", exc)
        return None
    try:
        return som_overlay(None)
    except TypeError:
        try:
            return som_overlay()
        except Exception as exc:
            _debug_failure("som_overlay(no-arg)", exc)
            return None
    except Exception as exc:
        _debug_failure("som_overlay", exc)
        return None


def _walk_uia_nodes(node):
    """Yield dict nodes from a UIA tree (dicts / lists / nested)."""
    if isinstance(node, dict):
        # Heuristic: a UIA element dict typically has control_type or name.
        if "control_type" in node or "name" in node or "automation_id" in node:
            yield node
        for value in node.values():
            yield from _walk_uia_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_uia_nodes(item)


def _search_uia(tree, query):
    """Return list of UIA element dicts whose name/automation_id/class match query."""
    if not tree:
        return []
    needle = (query or "").strip().lower()
    if not needle:
        return []
    matches = []
    try:
        for elem in _walk_uia_nodes(tree):
            name = str(elem.get("name") or "").lower()
            aid = str(elem.get("automation_id") or "").lower()
            cls = str(elem.get("class_name") or "").lower()
            ctrl = str(elem.get("control_type") or "").lower()
            if needle in name or needle in aid or needle in cls or needle in ctrl:
                matches.append(elem)
    except Exception as exc:
        _debug_failure("uia tree walk", exc)
    return matches


def _has_ocr_match(result):
    if not result:
        return False
    if isinstance(result, dict):
        return bool(
            result.get("found")
            or result.get("match")
            or result.get("matches")
            or result.get("elements")
            or result.get("box")
            or result.get("center")
        )
    if isinstance(result, (list, tuple)):
        return len(result) > 0
    return bool(result)


def _normalize_ocr_result(result):
    if isinstance(result, dict):
        return {"source": "ocr", **result}
    if isinstance(result, list):
        return {"source": "ocr", "matches": result}
    return {"source": "ocr", "match": result}


def _extract_center(payload):
    """Extract a click center {x, y} from an OCR/SOM/UIA payload, or None."""
    if not isinstance(payload, dict):
        return None
    matches = payload.get("matches", [])
    if matches and isinstance(matches[0], dict):
        m = matches[0]
        center = m.get("center")
        if isinstance(center, dict) and "x" in center and "y" in center:
            return {"x": int(center["x"]), "y": int(center["y"])}
        bbox = m.get("bbox") or m.get("bounds") or m.get("rect")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                return {"x": int(bbox[0] + bbox[2] // 2), "y": int(bbox[1] + bbox[3] // 2)}
            except (TypeError, ValueError):
                return None
    center = payload.get("center")
    if isinstance(center, dict) and "x" in center and "y" in center:
        return {"x": int(center["x"]), "y": int(center["y"])}
    return None


def _hybrid_resolve(query):
    """Resolve a target through the hybrid pipeline.

    Returns (payload, method_used) or (None, None) if nothing matched.
    """
    # 1. UIA tree (cached 500ms)
    tree = _get_uia_tree()
    if tree:
        uia_matches = _search_uia(tree, query)
        if uia_matches:
            return {"source": "uia", "matches": uia_matches, "tree": tree}, "uia"

    # 2. OCR
    ocr_result = _ocr_find_text(query)
    if _has_ocr_match(ocr_result):
        return _normalize_ocr_result(ocr_result), "ocr"

    # 3. SOM Vision
    som_overlay = _get_som_overlay()
    if som_overlay:
        return {"source": "som", "overlay": som_overlay}, "som"

    return None, None


def _read_body():
    """Best-effort JSON body reader that tolerates shared._json_body semantics."""
    try:
        from shared import _json_body
        body = _json_body()
        if body:
            return body
    except Exception as exc:
        _debug_failure("_json_body", exc)
    return request.get_json(force=True, silent=True) or {}


@hybrid_agent_bp.route("/agent/find", methods=["POST"])
def _agent_find():
    body = _read_body()
    query = body.get("query") or body.get("text") or body.get("target")
    if not query:
        return jsonify({"ok": False, "error": "missing 'query'"}), 400

    _bump_stat("total_requests")
    try:
        payload, method = _hybrid_resolve(query)
    except Exception as exc:
        _debug_failure("/agent/find", exc)
        _bump_stat("failures")
        return jsonify({"ok": False, "error": str(exc), "method_used": None}), 500

    if not payload:
        _bump_stat("misses")
        _set_last_method("find", None)
        return jsonify({
            "ok": False,
            "error": "no match in UIA, OCR, or SOM",
            "query": query,
            "method_used": None,
        }), 404

    _bump_stat(f"{method}_hits")
    _set_last_method("find", method)
    return jsonify({
        "ok": True,
        "query": query,
        "result": payload,
        "method_used": method,
        "resolution_order": ["uia", "ocr", "som"],
    })


@hybrid_agent_bp.route("/agent/act", methods=["POST"])
def _agent_act():
    body = _read_body()
    action = body.get("action") or "click"
    target = body.get("target") or body.get("query") or body.get("text")

    # Actions like scroll may not need a textual target.
    targetless_actions = {"scroll", "press_enter", "escape", "tab"}
    if not target and action not in targetless_actions:
        return jsonify({"ok": False, "error": "missing 'target'"}), 400

    _bump_stat("total_requests")

    method = None
    payload = None
    if target:
        try:
            payload, method = _hybrid_resolve(target)
        except Exception as exc:
            _debug_failure("/agent/act resolve", exc)
            _bump_stat("failures")
            return jsonify({"ok": False, "error": str(exc), "method_used": None}), 500

    _invalidate_uia_cache()

    click_error = None
    clicked = False

    # Use CoAgent's own mouse/click endpoint via localhost
    _mouse_port = _self_port()
    if method in ("uia", "ocr", "som"):
        try:
            target_center = None
            if payload and isinstance(payload, dict):
                matches = payload.get("matches", [])
                if matches and isinstance(matches[0], dict):
                    bbox = matches[0].get("bbox") or matches[0].get("bounds") or matches[0].get("rect")
                    center = matches[0].get("center")
                    if center:
                        target_center = center
                    elif bbox and len(bbox) >= 4:
                        target_center = {"x": bbox[0] + bbox[2] // 2, "y": bbox[1] + bbox[3] // 2}
            if target_center:
                _coagent_api_port = _self_port()
                act = {"double_click": "dblclick", "right_click": "rclick"}.get(action, "click")
                coagent_path = f"/mouse/{act}"
                coagent_body = {"x": target_center["x"], "y": target_center["y"]}
                import urllib.request, json
                coagent_url = f"http://127.0.0.1:{_coagent_api_port}{coagent_path}"
                coagent_data = json.dumps(coagent_body).encode("utf-8")
                coagent_req = urllib.request.Request(coagent_url, data=coagent_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(coagent_req, timeout=10) as _resp:
                    clicked = True
            else:
                click_error = "target resolved but no coordinates available"
        except Exception as exc:
            _debug_failure("click via coagent", exc)
            click_error = str(exc)

    if not target:
        # Dispatch targetless actions to the appropriate CoAgent endpoint.
        _targetless = {
            "scroll": ("/mouse/scroll", {"clicks": -3}),
            "press_enter": ("/key/press", {"keys": ["enter"]}),
            "escape": ("/key/press", {"keys": ["esc"]}),
            "tab": ("/key/press", {"keys": ["tab"]}),
        }
        if action in _targetless:
            try:
                import urllib.request, json
                _path, _tbody = _targetless[action]
                _turl = f"http://127.0.0.1:{_self_port()}{_path}"
                _tdata = json.dumps(_tbody).encode("utf-8")
                _treq = urllib.request.Request(_turl, data=_tdata, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(_treq, timeout=10):
                    clicked = True
            except Exception as exc:
                _debug_failure(f"targetless {action}", exc)
                click_error = str(exc)
        else:
            click_error = f"targetless action '{action}' is not implemented"

    # If target was provided but not resolved, fail explicitly
    if target and not payload:
        _bump_stat("misses")
        _set_last_method("act", None)
        return jsonify({
            "ok": False,
            "error": "target unresolvable",
            "action": action,
            "target": target,
            "method_used": None,
        }), 404

    _set_last_method("act", method)
    if not clicked and click_error:
        _bump_stat("failures")
        return jsonify({
            "ok": False,
            "error": click_error,
            "action": action,
            "target": target,
            "method_used": method,
        }), 500

    if not target:
        _bump_stat(f"{action}_hits")
    elif method:
        _bump_stat(f"{method}_hits")

    return jsonify({
        "ok": True,
        "action": action,
        "target": target,
        "method_used": method,
        "result": payload,
        "resolution_order": ["uia", "ocr", "som"],
    })


@hybrid_agent_bp.route("/agent/type", methods=["POST"])
def _agent_type():
    body = _read_body()
    text = body.get("text")
    if text is None:
        return jsonify({"ok": False, "error": "missing 'text'"}), 400

    target = body.get("target") or body.get("query")
    _bump_stat("total_requests")

    method = None
    payload = None
    if target:
        try:
            payload, method = _hybrid_resolve(target)
        except Exception as exc:
            _debug_failure("/agent/type resolve", exc)
            _bump_stat("failures")
            return jsonify({"ok": False, "error": str(exc), "method_used": None}), 500
        if not payload:
            _bump_stat("misses")
            _set_last_method("type", None)
            return jsonify({
                "ok": False,
                "error": "target not resolvable",
                "target": target,
                "method_used": None,
            }), 404
        _bump_stat(f"{method}_hits")

    typed = False
    type_error = None
    try:
        import urllib.request, json as _json
        _type_url = f"http://127.0.0.1:{_self_port()}/key/type"
        _type_data = _json.dumps({"text": str(text)}).encode("utf-8")
        _type_req = urllib.request.Request(_type_url, data=_type_data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(_type_req, timeout=10):
            typed = True
    except Exception as exc:
        _debug_failure("send_input_background", exc)
        type_error = str(exc)

    _invalidate_uia_cache()

    if not typed:
        _bump_stat("failures")
        _set_last_method("type", method)
        return jsonify({
            "ok": False,
            "error": type_error,
            "text": text,
            "method_used": method,
        }), 500

    _set_last_method("type", method or "uia_background")
    return jsonify({
        "ok": True,
        "text": text,
        "target": target,
        "method_used": method or "uia_background",
        "result": payload,
        "resolution_order": ["uia", "ocr", "som"],
    })


@hybrid_agent_bp.route("/agent/plan-and-execute", methods=["POST"])
def _agent_plan_and_execute():
    body = _read_body()
    steps = body.get("steps")
    if not isinstance(steps, list) or not steps:
        return jsonify({"ok": False, "error": "missing 'steps' list"}), 400

    _bump_stat("total_requests")
    results = []
    overall_ok = True
    methods_used = []

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            results.append({"step": idx, "ok": False, "error": "invalid step"})
            overall_ok = False
            continue

        action = (step.get("action") or "act").lower()
        target = step.get("target") or step.get("query") or step.get("text")
        text = step.get("text")
        step_record = {"step": idx, "action": action, "ok": False}

        try:
            if action == "type":
                if text is None:
                    step_record["error"] = "missing text"
                    overall_ok = False
                    results.append(step_record)
                    continue
                method = None
                if target:
                    payload, method = _hybrid_resolve(target)
                    step_record["target_resolved"] = bool(payload)
                    if not payload:
                        step_record["error"] = "target unresolvable"
                        overall_ok = False
                        results.append(step_record)
                        continue
                try:
                    from uia_engine import send_input_background
                    send_input_background(str(text))
                    step_record["ok"] = True
                    step_record["method_used"] = method or "uia_background"
                    methods_used.append(step_record["method_used"])
                    if method:
                        _bump_stat(f"{method}_hits")
                except Exception as exc:
                    _debug_failure("plan-and-execute type", exc)
                    step_record["error"] = str(exc)
                    overall_ok = False

            elif action in {"act", "click", "double_click", "right_click"}:
                if not target:
                    step_record["error"] = "missing target"
                    overall_ok = False
                    results.append(step_record)
                    continue
                payload, method = _hybrid_resolve(target)
                step_record["method_used"] = method
                if not payload:
                    step_record["error"] = "target unresolvable"
                    overall_ok = False
                    _bump_stat("misses")
                else:
                    if method == "uia":
                        try:
                            from uia_engine import uia_click
                            uia_click(target)
                            step_record["ok"] = True
                        except Exception as exc:
                            _debug_failure("plan-and-execute uia_click", exc)
                            step_record["error"] = str(exc)
                            overall_ok = False
                    else:
                        # OCR/SOM: extract coordinates and click via CoAgent's mouse endpoint
                        target_center = _extract_center(payload)
                        if not target_center:
                            step_record["error"] = "target resolved but no coordinates available"
                            overall_ok = False
                        else:
                            try:
                                import urllib.request
                                import json as _json
                                act = {"double_click": "dblclick", "right_click": "rclick"}.get(action, "click")
                                _url = f"http://127.0.0.1:{_self_port()}/mouse/{act}"
                                _data = _json.dumps({"x": target_center["x"], "y": target_center["y"]}).encode("utf-8")
                                _req = urllib.request.Request(_url, data=_data, headers={"Content-Type": "application/json"})
                                with urllib.request.urlopen(_req, timeout=10):
                                    step_record["ok"] = True
                            except Exception as exc:
                                _debug_failure("plan-and-execute click", exc)
                                step_record["error"] = str(exc)
                                overall_ok = False
                    if method:
                        _bump_stat(f"{method}_hits")
                        methods_used.append(method)
                    step_record["result"] = payload

            elif action == "find":
                if not target:
                    step_record["error"] = "missing query"
                    overall_ok = False
                    results.append(step_record)
                    continue
                payload, method = _hybrid_resolve(target)
                step_record["method_used"] = method
                step_record["ok"] = bool(payload)
                step_record["result"] = payload
                if payload and method:
                    _bump_stat(f"{method}_hits")
                    methods_used.append(method)
                else:
                    _bump_stat("misses")
                    overall_ok = False
                    step_record["error"] = "no match"

            else:
                step_record["error"] = f"unknown action '{action}'"
                overall_ok = False

        except Exception as exc:
            _debug_failure(f"plan-and-execute step {idx}", exc)
            step_record["error"] = str(exc)
            overall_ok = False

        results.append(step_record)
        _invalidate_uia_cache()

    _set_last_method("plan_and_execute", methods_used[-1] if methods_used else None)
    return jsonify({
        "ok": overall_ok,
        "steps_total": len(steps),
        "steps_executed": len(results),
        "methods_used": methods_used,
        "resolution_order": ["uia", "ocr", "som"],
        "results": results,
    })


@hybrid_agent_bp.route("/agent/hybrid/status", methods=["GET"])
def _agent_hybrid_status():
    with _STATS_LOCK:
        stats = dict(_HYBRID_STATS)
    with _LAST_METHOD_LOCK:
        last_methods = dict(_LAST_METHOD_USED)
    with _UIA_CACHE_LOCK:
        cache_entries = len(_UIA_CACHE)
        cache_age_ms = None
        if _UIA_CACHE:
            newest = max(entry["ts"] for entry in _UIA_CACHE.values())
            cache_age_ms = int((time.monotonic() - newest) * 1000)
    return jsonify({
        "ok": True,
        "resolution_order": ["uia", "ocr", "som"],
        "uia_cache_ttl_ms": int(_UIA_CACHE_TTL_SECONDS * 1000),
        "uia_cache_entries": cache_entries,
        "uia_cache_age_ms": cache_age_ms,
        "stats": stats,
        "last_method_used": last_methods,
    })


def register_routes(app, state, require_auth):
    """Register hybrid agent blueprint routes on the given Flask app."""
    app.register_blueprint(hybrid_agent_bp)
    try:
        from shared import _wrap_registered_blueprint_routes
        _wrap_registered_blueprint_routes(app, hybrid_agent_bp.name, require_auth)
    except Exception as exc:
        _LOGGER.error("Failed to wrap hybrid_agent_bp routes with auth: %s: %s", type(exc).__name__, exc)
        # Fail closed: unregister the blueprint's routes so nothing runs unauthenticated.
        prefix = f"{hybrid_agent_bp.name}."
        for endpoint in [e for e in list(app.view_functions) if e.startswith(prefix)]:
            app.view_functions.pop(endpoint, None)
    return hybrid_agent_bp
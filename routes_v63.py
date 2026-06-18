"""v6.3 feature routes: cursor overlay, recording, waits, and element actions."""

from flask import jsonify

import shared
from shared import _json_body, _result_response

try:
    import coagent_features as features

    _FEATURES_ERROR = None
except Exception as e:
    features = None
    _FEATURES_ERROR = e


def _feature_error():
    return {"error": f"coagent_features unavailable: {_FEATURES_ERROR}"}


def route_cursor_enable():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.cursor_set_enabled(_json_body()))


def route_cursor_style():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.cursor_set_style(_json_body()))


def route_cursor_status():
    if not features:
        return jsonify(_feature_error()), 500
    return jsonify(features.cursor_get_status())


def route_recording_start():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.recording_start(_json_body()))


def route_recording_stop():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.recording_stop())


def route_recording_status():
    if not features:
        return jsonify(_feature_error()), 500
    return jsonify(features.recording_status())


def route_features():
    if not features:
        return jsonify({"available": False, **_feature_error()}), 500
    status = features.get_status()
    status.update(
        {
            "available": True,
            "v70": {
                "modular_routes": "route monolith split into modules",
                "sse_mcp": "SSE transport for MCP",
                "health_watchdog": "auto-restart watchdog",
                "thread_pool_4": "increased SOM thread pool",
            },
        }
    )
    return jsonify(status)


def route_element_find():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.element_find(_json_body()))


def route_element_click_by_name():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.element_click_by_name(_json_body()), default_error_status=404)


def route_element_click_by_index():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.element_click_by_index(_json_body()), default_error_status=404)


def route_wait_element():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.wait_element(_json_body()), default_error_status=408)


def route_wait_element_gone():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.wait_element_gone(_json_body()), default_error_status=408)


def route_stabilize():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.stabilize_action(_json_body()), default_error_status=408)


def route_window_tree():
    if not features:
        return jsonify(_feature_error()), 500
    return _result_response(features.get_window_tree(), default_error_status=500)


def _add(app, rules, func, methods=None, auth=False):
    view = shared.require_auth(func) if auth else func
    for rule in rules:
        app.add_url_rule(rule, endpoint=func.__name__, view_func=view, methods=methods)


def register_routes(app):
    _add(app, ["/cursor/enable"], route_cursor_enable, methods=["POST"], auth=True)
    _add(app, ["/cursor/style"], route_cursor_style, methods=["POST"], auth=True)
    _add(app, ["/cursor/status"], route_cursor_status)
    _add(app, ["/recording/start"], route_recording_start, methods=["POST"], auth=True)
    _add(app, ["/recording/stop"], route_recording_stop, methods=["POST"], auth=True)
    _add(app, ["/recording/status"], route_recording_status)
    _add(app, ["/features"], route_features)
    _add(app, ["/uia/element/find"], route_element_find, methods=["POST"], auth=True)
    _add(app, ["/uia/element/click-by-name"], route_element_click_by_name, methods=["POST"], auth=True)
    _add(app, ["/uia/element/click-by-index"], route_element_click_by_index, methods=["POST"], auth=True)
    _add(app, ["/wait/element"], route_wait_element, methods=["POST"], auth=True)
    _add(app, ["/wait/element-gone"], route_wait_element_gone, methods=["POST"], auth=True)
    _add(app, ["/stabilize"], route_stabilize, methods=["POST"], auth=True)
    _add(app, ["/uia/window-tree"], route_window_tree)

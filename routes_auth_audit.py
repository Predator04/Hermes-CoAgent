"""Auth-coverage audit: report which registered HTTP routes are unauthenticated.

Every routes_*.py blueprint is supposed to auth-protect its endpoints via
`_wrap_registered_blueprint_routes` (or an explicit `@require_auth`). A route
file that forgets this leaves its endpoints reachable with no token — and
since CoAgent binds 0.0.0.0, that means any LAN client can hit them. This
endpoint enumerates the live Flask route table and flags anything not
carrying the auth wrapper's marker, so the agent/user can spot such gaps in
one call instead of auditing ~150 files by hand.

Routes:
  GET /auth/audit   -> {ok, total_routes, authenticated, unauthenticated,
                        unauthenticated_endpoints: [{rule, methods, endpoint}]}
"""

from flask import Blueprint, current_app, jsonify

from shared import _wrap_registered_blueprint_routes

bp = Blueprint("auth_audit", __name__)


def _route_table(app):
    """Build {endpoint: [{rule, methods}, ...]} from Flask's url_map.

    A single view function can be mounted at multiple rules; keep every rule
    so the audit reports each exposed path rather than silently dropping all
    but the last.
    """
    table = {}
    for rule in app.url_map.iter_rules():
        endpoint = rule.endpoint
        if endpoint == "static":
            continue
        methods = sorted({m for m in (rule.methods or set()) if m not in ("HEAD", "OPTIONS")})
        table.setdefault(endpoint, []).append({"rule": rule.rule, "methods": methods})
    return table


def _unauth_summary(app):
    """Return (total, authenticated, unauth_list) across live view functions."""
    table = _route_table(app)
    unauth = []
    total = 0
    authenticated = 0
    for endpoint, view_func in app.view_functions.items():
        if endpoint == "static" or endpoint.startswith("static"):
            continue
        if endpoint not in table:
            continue
        total += 1
        if getattr(view_func, "_hermes_auth_wrapped", False):
            authenticated += 1
        else:
            for info in table[endpoint]:
                unauth.append({
                    "rule": info["rule"],
                    "methods": info["methods"],
                    "endpoint": endpoint,
                })
    unauth.sort(key=lambda e: e["rule"])
    return total, authenticated, unauth


@bp.route("/auth/audit", methods=["GET"])
def route_auth_audit():
    """Enumerate live routes and flag any that are not auth-wrapped."""
    total, authenticated, unauth = _unauth_summary(current_app._get_current_object())
    return jsonify({
        "ok": True,
        "total_routes": total,
        "authenticated": authenticated,
        "unauthenticated": len(unauth),
        "unauthenticated_endpoints": unauth,
    })


def register_routes(app, state, require_auth):
    app.register_blueprint(bp)
    _wrap_registered_blueprint_routes(app, bp.name, require_auth)

"""Semantic discover-then-act UIA targeting (issue #8).

Instead of clicking raw coordinates, describe the target by role + name and let
the agent discover the matching element in the UIA tree, then act on it. The
matching/scoring is a pure function (unit-tested with a synthetic tree); the
live snapshot is Windows-only and falls back to a dry run that returns ranked
candidates.
"""
import logging

from flask import Blueprint, jsonify

from shared import _json_body

_LOGGER = logging.getLogger(__name__)
uia_semantic_bp = Blueprint("uia_semantic", __name__)


def _norm(s):
    return " ".join(str(s or "").lower().split())


def score_element(el, role=None, name=None):
    """Score 0..1 how well an element matches the requested role/name."""
    score = 0.0
    weight = 0.0
    if role:
        weight += 0.4
        if _norm(el.get("role")) == _norm(role):
            score += 0.4
        elif _norm(role) and _norm(role) in _norm(el.get("role")):
            score += 0.25
    if name:
        weight += 0.6
        en, qn = _norm(el.get("name")), _norm(name)
        if en == qn:
            score += 0.6
        elif qn and qn in en:
            score += 0.42
        elif en and en in qn:
            score += 0.3
    if weight == 0:
        return 0.0
    return round(score / weight, 4)


def rank_candidates(tree, role=None, name=None, limit=5):
    """Return elements ranked by match score (descending), best first."""
    scored = []
    for el in tree or []:
        if not isinstance(el, dict):
            continue
        sc = score_element(el, role, name)
        if sc > 0:
            scored.append({"score": sc, "element": el})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def _live_tree():
    """Best-effort live UIA element list (flattened). Returns None if unavailable.

    The live UIA snapshot is a nested tree whose nodes expose ``control_type``
    (not ``role``). Flatten it and map ``control_type`` → ``role`` so the
    role/name scorer matches what the tree actually contains.
    """
    try:
        from routes_uia import _get_uia_engine, _walk_uia_nodes
        ue = _get_uia_engine()
        if ue is None:
            return None
        snap = ue.uia_snapshot()
        if not snap.get("success"):
            return None
        elements = []
        for node in _walk_uia_nodes(snap.get("tree", {})):
            if not isinstance(node, dict):
                continue
            node = dict(node)
            node.setdefault("role", node.get("control_type", ""))
            elements.append(node)
        return elements or None
    except Exception:
        return None


def register_routes(app, state, require_auth):
    @app.route("/uia/act", methods=["POST"])
    @require_auth
    def route_uia_act():
        body = _json_body()
        role = body.get("role")
        name = body.get("name")
        if not role and not name:
            return jsonify({"ok": False, "error": "Missing required field: role or name"}), 400
        action = str(body.get("action") or "click").lower()
        tree = body.get("tree")  # test/dry-run injection
        live = tree is None
        if live:
            tree = _live_tree()
        if tree is None:
            return jsonify({"ok": False, "error": "UIA tree unavailable on this host",
                            "dry_run": True}), 501
        ranked = rank_candidates(tree, role, name)
        if not ranked:
            return jsonify({"ok": False, "error": "no matching element",
                            "candidates": []}), 404
        best = ranked[0]
        return jsonify({
            "ok": True,
            "action": action,
            "matched": best["element"],
            "score": best["score"],
            "candidates": ranked,
            "executed": False,  # discovery-only endpoint — no action is performed
            "dry_run": not live,
        })

    _LOGGER.info("Semantic UIA routes registered")

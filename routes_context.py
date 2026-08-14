"""Response Context Optimizer — token-budget middleware for CoAgent.

Shrinks heavy responses (UIA trees, screenshots, verbose logs) before the
calling agent pays tokens for them. Hooks into Flask as an after_request
post-processor and exposes ``POST /context/optimize`` for arbitrary JSON.

Activation is opt-in per request via ``?context_budget=N``. When the query
param is absent or the payload is already small, the response is returned
unchanged.
"""

import base64
import io
import json

from flask import jsonify, request

from shared import _log


DEFAULT_BUDGET = 8000  # rough token budget (~ 32 KB of JSON)

_TARGET_PATH_PREFIXES = ("/uia/tree", "/uia/snapshot", "/process/list", "/screen")

_NOISE_CONTROL_TYPES = {
    "Pane", "Custom", "Group", "TitleBar", "MenuBar", "StatusBar",
    "Separator", "Thumb", "ScrollBar", "Tooltip", "Image",
}

_LEAFY_KEYS_TO_KEEP = {
    "name", "control_type", "automation_id", "class_name", "rect",
    "value", "is_enabled", "is_offscreen",
}

_ERR_KEYWORDS = (
    "error", "err:", "traceback", "exception", "fatal",
    "failed", "warning", "warn:", "critical",
)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------
def estimate_tokens(payload):
    """Rough token estimate assuming ~4 chars per token."""
    if payload is None:
        return 0
    if isinstance(payload, (bytes, bytearray)):
        return max(1, len(payload) // 4)
    if isinstance(payload, str):
        return max(1, len(payload) // 4)
    try:
        s = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(payload)
    return max(1, len(s) // 4)


# ---------------------------------------------------------------------------
# UIA tree trimming
# ---------------------------------------------------------------------------
def _rect_area(rect):
    if not isinstance(rect, dict):
        return 0
    try:
        w = int(rect.get("width", rect.get("w", 0)))
        h = int(rect.get("height", rect.get("h", 0)))
    except (TypeError, ValueError):
        return 0
    return max(0, w) * max(0, h)


def _is_noise_node(node):
    if not isinstance(node, dict):
        return True
    if node.get("is_offscreen") is True:
        return True
    rect = node.get("rect")
    if rect and _rect_area(rect) == 0 and not node.get("name"):
        return True
    ctype = str(node.get("control_type") or "")
    if ctype in _NOISE_CONTROL_TYPES and not node.get("name"):
        return True
    return False


def _count_nodes(node):
    if not isinstance(node, dict):
        return 0
    total = 1
    for c in node.get("children") or []:
        total += _count_nodes(c)
    return total


def _drop_least_valuable(node):
    if not isinstance(node, dict):
        return False
    children = node.get("children") or []
    for i, c in enumerate(children):
        if not isinstance(c, dict):
            continue
        cchildren = c.get("children") or []
        if not cchildren and not c.get("name"):
            del children[i]
            if not children:
                node.pop("children", None)
            return True
    for c in children:
        if _drop_least_valuable(c):
            return True
    return False


def trim_uia_tree(tree, budget=DEFAULT_BUDGET, max_depth=4):
    """Trim a UIA snapshot: drops off-screen/zero-size/noise nodes, caps depth.

    Returns ``(pruned_tree, report_dict)``. Safe no-op on non-dict input.
    """
    if not isinstance(tree, dict):
        return tree, {"nodes_before": 0, "nodes_after": 0, "changed": False}

    nodes_before = _count_nodes(tree)

    def _prune(node, depth):
        if not isinstance(node, dict) or depth > max_depth:
            return None
        kept = {k: node[k] for k in _LEAFY_KEYS_TO_KEEP if k in node}
        children_out = []
        for child in node.get("children") or []:
            if _is_noise_node(child):
                # promote descendants of noise nodes so we don't lose useful leaves
                for g in child.get("children") or []:
                    p = _prune(g, depth + 1)
                    if p is not None:
                        children_out.append(p)
                continue
            p = _prune(child, depth + 1)
            if p is not None:
                children_out.append(p)
        if children_out:
            kept["children"] = children_out
        return kept

    pruned = _prune(tree, 0) or {}

    guard = 500
    while estimate_tokens(pruned) > budget and guard > 0:
        if not _drop_least_valuable(pruned):
            break
        guard -= 1

    nodes_after = _count_nodes(pruned)
    return pruned, {
        "nodes_before": nodes_before,
        "nodes_after": nodes_after,
        "changed": nodes_after != nodes_before,
    }


# ---------------------------------------------------------------------------
# Screenshot downscaling
# ---------------------------------------------------------------------------
def downscale_screenshot(img_bytes, budget=DEFAULT_BUDGET, max_dim=1280, quality=70):
    """Downscale image bytes to ``max_dim`` and re-encode as JPEG@quality.

    Returns ``(new_bytes, report)``. Safe no-op when Pillow is missing or the
    re-encoded output would be larger than the input.
    """
    if not img_bytes:
        return img_bytes, {"downscaled": False, "reason": "empty"}
    try:
        from PIL import Image
    except ImportError:
        return img_bytes, {"downscaled": False, "reason": "pillow_missing"}
    try:
        im = Image.open(io.BytesIO(img_bytes))
        im.load()
    except Exception as e:
        return img_bytes, {
            "downscaled": False,
            "reason": f"open_failed:{type(e).__name__}",
        }
    orig_w, orig_h = im.size
    orig_bytes = len(img_bytes)
    scale = 1.0
    max_side = max(orig_w, orig_h)
    if max_side > max_dim:
        scale = max_dim / float(max_side)
    if im.mode not in ("RGB", "L"):
        try:
            im = im.convert("RGB")
        except Exception:
            return img_bytes, {"downscaled": False, "reason": "convert_failed"}
    if scale < 1.0:
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))
        try:
            resample = Image.LANCZOS
        except AttributeError:
            resample = getattr(Image, "Resampling", Image).LANCZOS
        im = im.resize((new_w, new_h), resample)
    out_buf = io.BytesIO()
    try:
        im.save(out_buf, format="JPEG", quality=int(quality), optimize=True)
    except Exception as e:
        return img_bytes, {"downscaled": False, "reason": f"encode_failed:{type(e).__name__}"}
    new_bytes = out_buf.getvalue()
    if len(new_bytes) >= orig_bytes and scale >= 1.0:
        return img_bytes, {
            "downscaled": False,
            "reason": "no_savings",
            "orig_bytes": orig_bytes,
            "orig_dim": [orig_w, orig_h],
        }
    return new_bytes, {
        "downscaled": True,
        "orig_bytes": orig_bytes,
        "new_bytes": len(new_bytes),
        "orig_dim": [orig_w, orig_h],
        "new_dim": list(im.size),
        "quality": int(quality),
    }


# ---------------------------------------------------------------------------
# Log / stdout truncation
# ---------------------------------------------------------------------------
def truncate_log(text, budget=DEFAULT_BUDGET, head=40, tail=40):
    """Trim verbose text: keep first/last N lines + every error-flagged line.

    Returns ``(new_text, report)``. No-op when input fits the budget.
    """
    if not isinstance(text, str):
        return text, {"truncated": False, "reason": "not_string"}
    if estimate_tokens(text) <= budget:
        return text, {"truncated": False, "reason": "under_budget"}

    lines = text.splitlines()
    if len(lines) <= head + tail:
        max_chars = max(400, budget * 4)
        if len(text) <= max_chars:
            return text, {"truncated": False, "reason": "under_budget"}
        half = max_chars // 2
        clipped = (
            text[:half]
            + f"\n... [truncated {len(text) - max_chars} chars] ...\n"
            + text[-half:]
        )
        if len(clipped) >= len(text):
            return text, {"truncated": False, "reason": "under_budget"}
        return clipped, {
            "truncated": True,
            "orig_bytes": len(text),
            "new_bytes": len(clipped),
            "mode": "chars",
        }

    kept = set(range(min(head, len(lines))))
    kept.update(range(max(0, len(lines) - tail), len(lines)))
    for i, ln in enumerate(lines):
        low = ln.lower()
        for kw in _ERR_KEYWORDS:
            if kw in low:
                kept.add(i)
                break

    ordered = sorted(kept)
    out_parts = []
    prev = -1
    dropped = 0
    for i in ordered:
        if prev >= 0 and i > prev + 1:
            gap = i - prev - 1
            out_parts.append(f"... [{gap} lines omitted] ...")
            dropped += gap
        out_parts.append(lines[i])
        prev = i
    if prev < len(lines) - 1:
        gap = len(lines) - 1 - prev
        out_parts.append(f"... [{gap} lines omitted] ...")
        dropped += gap
    new_text = "\n".join(out_parts)
    return new_text, {
        "truncated": True,
        "orig_lines": len(lines),
        "kept_lines": len(ordered),
        "dropped_lines": dropped,
        "orig_bytes": len(text),
        "new_bytes": len(new_text),
        "mode": "lines",
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def _detect_type(d):
    if not isinstance(d, dict):
        return None
    if "processes" in d and isinstance(d["processes"], list):
        return "processes"
    if "tree" in d and isinstance(d.get("tree"), dict):
        return "uia_wrapped"
    if isinstance(d.get("children"), list):
        return "uia"
    if isinstance(d.get("windows"), list):
        return "uia"
    return None


def _walk_truncate(obj, per_string_max):
    if isinstance(obj, dict):
        return {k: _walk_truncate(v, per_string_max) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_truncate(x, per_string_max) for x in obj]
    if isinstance(obj, str) and len(obj) > per_string_max:
        cut = per_string_max // 2
        truncated = (
            obj[:cut]
            + f"... [truncated {len(obj) - per_string_max} chars] ..."
            + obj[-cut:]
        )
        if len(truncated) >= len(obj):
            return obj
        return truncated
    return obj


def optimize_payload(payload, budget=DEFAULT_BUDGET, hint=None):
    """Route a JSON-serializable payload through the appropriate optimizer.

    ``hint`` may be ``"uia"``, ``"processes"``, ``"log"``, or ``None`` for
    auto-detection. Returns ``(new_payload, report)``.
    """
    report = {"budget": budget, "actions": []}
    if payload is None:
        report["tokens_before"] = 0
        report["tokens_after"] = 0
        return payload, report

    orig_tokens = estimate_tokens(payload)
    report["tokens_before"] = orig_tokens

    if hint == "log" or isinstance(payload, str):
        new, rep = truncate_log(payload if isinstance(payload, str) else str(payload), budget=budget)
        if rep.get("truncated"):
            report["actions"].append({"op": "truncate_log", **rep})
        report["tokens_after"] = estimate_tokens(new)
        return new, report

    if isinstance(payload, list):
        new_list = payload
        if orig_tokens > budget and payload:
            per_item = max(1, estimate_tokens(payload[0]))
            keep = max(10, budget // per_item)
            if len(payload) > keep:
                new_list = list(payload[:keep])
                new_list.append({"_truncated_items": len(payload) - keep})
                report["actions"].append({
                    "op": "cap_list",
                    "orig_items": len(payload),
                    "kept": keep,
                })
        report["tokens_after"] = estimate_tokens(new_list)
        return new_list, report

    if isinstance(payload, dict):
        detected = hint or _detect_type(payload)
        if detected == "uia":
            new, rep = trim_uia_tree(payload, budget=budget)
            if rep.get("changed"):
                report["actions"].append({"op": "trim_uia_tree", **rep})
            report["tokens_after"] = estimate_tokens(new)
            return new, report
        if detected == "uia_wrapped":
            inner = payload.get("tree") or {}
            new_inner, rep = trim_uia_tree(inner, budget=budget)
            new_payload = dict(payload)
            new_payload["tree"] = new_inner
            if rep.get("changed"):
                report["actions"].append({"op": "trim_uia_tree", **rep})
            report["tokens_after"] = estimate_tokens(new_payload)
            return new_payload, report
        if detected == "processes":
            procs = payload.get("processes") or []
            new_procs, rep = optimize_payload(procs, budget=max(1000, budget - 200))
            new_payload = dict(payload)
            new_payload["processes"] = new_procs
            if isinstance(new_procs, list) and len(new_procs) != len(procs):
                new_payload["count"] = len(new_procs)
            filtered = {k: v for k, v in rep.items() if k != "actions"}
            report["actions"].append({"op": "trim_processes", **filtered})
            report["tokens_after"] = estimate_tokens(new_payload)
            return new_payload, report

        per_string_max = max(400, budget * 2)
        new_payload = _walk_truncate(payload, per_string_max)
        report["tokens_after"] = estimate_tokens(new_payload)
        return new_payload, report

    report["tokens_after"] = orig_tokens
    return payload, report


# ---------------------------------------------------------------------------
# Query-param / after_request wiring
# ---------------------------------------------------------------------------
def parse_budget_arg():
    """Read ``?context_budget=N`` off the current request. ``None`` if absent."""
    try:
        raw = request.args.get("context_budget")
    except RuntimeError:
        return None
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 100:
        return None
    return n


def _path_matches(path):
    if not path:
        return False
    for prefix in _TARGET_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _budget_to_max_dim(budget):
    if budget <= 2000:
        return 640
    if budget <= 6000:
        return 960
    if budget <= 12000:
        return 1280
    return 1600


def _budget_to_quality(budget):
    if budget <= 2000:
        return 55
    if budget <= 6000:
        return 65
    if budget <= 12000:
        return 75
    return 82


def _attach_report(payload, report):
    if isinstance(payload, dict):
        out = dict(payload)
        out["context_saved"] = report
        return out
    return {"data": payload, "context_saved": report}


def optimize_response(response):
    """Flask ``after_request`` hook — trims heavy responses on demand."""
    try:
        budget = parse_budget_arg()
        if budget is None:
            return response
        path = request.path or ""
        if not _path_matches(path):
            return response

        mimetype = (response.mimetype or "").lower()

        if mimetype.startswith("image/"):
            if getattr(response, "direct_passthrough", False):
                return response
            try:
                orig_bytes = response.get_data()
            except Exception:
                return response
            if not orig_bytes:
                return response
            max_dim = _budget_to_max_dim(budget)
            quality = _budget_to_quality(budget)
            new_bytes, rep = downscale_screenshot(
                orig_bytes, budget=budget, max_dim=max_dim, quality=quality,
            )
            if rep.get("downscaled"):
                response.set_data(new_bytes)
                response.mimetype = "image/jpeg"
                saved = max(0, int(rep.get("orig_bytes", 0)) - int(rep.get("new_bytes", 0)))
                response.headers["X-Context-Saved"] = str(saved)
                response.headers["X-Context-Optimizer"] = "screen"
            return response

        if "json" in mimetype:
            data = response.get_json(silent=True)
            if data is None:
                return response
            new_data, report = optimize_payload(data, budget=budget)
            actions = report.get("actions") or []
            if not actions and report.get("tokens_before") == report.get("tokens_after"):
                return response
            new_data = _attach_report(new_data, report)
            body = json.dumps(new_data, ensure_ascii=False, default=str).encode("utf-8")
            response.set_data(body)
            response.mimetype = "application/json"
            saved = max(
                0,
                (int(report.get("tokens_before", 0)) - int(report.get("tokens_after", 0))) * 4,
            )
            response.headers["X-Context-Saved"] = str(saved)
            response.headers["X-Context-Optimizer"] = "json"
        return response
    except Exception as e:
        _log(f"[context] after_request hook error: {e}")
        return response


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
def register_routes(app, state, require_auth):
    @app.route("/context/optimize", methods=["POST"])
    @require_auth
    def route_context_optimize():
        try:
            body = request.get_json(silent=True)
        except Exception:
            body = None
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "body must be a JSON object"}), 400
        budget = body.get("budget", DEFAULT_BUDGET)
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            budget = DEFAULT_BUDGET
        if budget < 100:
            budget = DEFAULT_BUDGET
        hint = body.get("hint")

        image_b64 = body.get("image_base64")
        if image_b64:
            try:
                raw = base64.b64decode(image_b64)
            except Exception as e:
                return jsonify({
                    "ok": False,
                    "error": f"invalid base64: {type(e).__name__}",
                }), 400
            max_dim = int(body.get("max_dim") or _budget_to_max_dim(budget))
            quality = int(body.get("quality") or _budget_to_quality(budget))
            new_bytes, rep = downscale_screenshot(
                raw, budget=budget, max_dim=max_dim, quality=quality,
            )
            return jsonify({
                "ok": True,
                "image_base64": base64.b64encode(new_bytes).decode("ascii"),
                "context_saved": rep,
                "budget": budget,
            })

        payload = body.get("payload")
        if isinstance(payload, str) and body.get("hint") is None:
            hint = "log"
        new_payload, report = optimize_payload(payload, budget=budget, hint=hint)
        return jsonify({
            "ok": True,
            "payload": new_payload,
            "context_saved": report,
            "budget": budget,
        })

    @app.route("/context/optimize/probe", methods=["GET"])
    @require_auth
    def route_context_probe():
        return jsonify({
            "ok": True,
            "endpoints": ["/context/optimize"],
            "target_paths": list(_TARGET_PATH_PREFIXES),
            "default_budget": DEFAULT_BUDGET,
            "query_param": "context_budget",
        })

    app.after_request(optimize_response)

    try:
        state.context_optimizer = {
            "optimize_payload": optimize_payload,
            "trim_uia_tree": trim_uia_tree,
            "downscale_screenshot": downscale_screenshot,
            "truncate_log": truncate_log,
        }
    except Exception:
        pass

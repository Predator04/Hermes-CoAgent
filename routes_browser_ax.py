"""Accessibility-tree element targeting routes (AX find + AX click).

Locates clickable page elements by accessibility role/name instead of
screenshot vision, using Playwright's CDP session:

  - Accessibility.getFullAXTree  -> nodes with role/name/backendDOMNodeId
  - DOM.getBoxModel              -> click coordinates for a backend node

Additive to routes_browser.py: reuses its shared browser session, lock, and
error helpers so both modules drive the same page. Existing screenshot-based
flows are untouched.
"""

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from routes_browser import _BROWSER_LOCK, _ensure_browser, _error
from shared import _wrap_registered_blueprint_routes

browser_ax_bp = Blueprint("browser_ax", __name__)

# AX roles worth surfacing as targetable elements. Everything else in the
# tree (generic containers, StaticText, etc.) is skipped.
_INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "checkbox",
    "radio",
    "switch",
    "combobox",
    "listbox",
    "option",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "tab",
    "treeitem",
    "slider",
    "spinbutton",
    "menuItem",  # some Chrome versions report camelCase variants
    "popUpButton",
    "pushButton",
}

_AX_NODE_LIMIT = 400  # hard cap on nodes returned per call


def _ax_unwrap(field):
    """Unwrap a CDP AXValue into a plain scalar.

    CDP reports role/name as nested AXValue objects, e.g.
      {"type": "role", "value": {"type": "string", "value": "button"}}
      {"type": "string", "value": "Sign in"}
    Depending on Chrome version the nesting depth varies, so unwrap until we
    hit a scalar (str/float/bool/None). Returns "" for anything else.
    """
    depth = 0
    while isinstance(field, dict) and depth < 4:
        field = field.get("value")
        depth += 1
    if isinstance(field, str):
        return field
    if isinstance(field, (int, float, bool)):
        return field
    return ""


def _quad_center(quad):
    """Center point (x, y) of a CDP quad [x1,y1,x2,y2,x3,y3,x4,y4]."""
    if not isinstance(quad, (list, tuple)) or len(quad) < 4:
        return None
    # Flatten pairs; quads are 8 numbers (4 points).
    nums = [n for n in quad if isinstance(n, (int, float))]
    if len(nums) < 8:
        return None
    xs = nums[0::2]
    ys = nums[1::2]
    return sum(xs) / 4.0, sum(ys) / 4.0


def _get_ax_elements(page, cdp, role_filter=None, name_filter=None, limit=_AX_NODE_LIMIT):
    """Return [{role, name, x, y}] for interactive AX nodes on the current page.

    role_filter: optional set/lowercase-str of roles to keep.
    name_filter: optional case-insensitive substring the name must contain.
    """
    tree = cdp.send("Accessibility.getFullAXTree")
    nodes = tree.get("nodes", []) if isinstance(tree, dict) else []

    wanted_roles = _INTERACTIVE_ROLES
    if role_filter:
        if isinstance(role_filter, str):
            role_filter = {role_filter}
        # A custom role filter bypasses the interactive whitelist.
        wanted_roles = {str(r).lower() for r in role_filter}
    else:
        wanted_roles = _INTERACTIVE_ROLES

    needle = name_filter.lower() if isinstance(name_filter, str) and name_filter else None

    elements = []
    seen = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        role = _ax_unwrap(node.get("role")).strip()
        name = _ax_unwrap(node.get("name")).strip()
        if not role or not name:
            continue
        role_l = role.lower()
        if role_l not in wanted_roles:
            continue
        if needle and needle not in name.lower():
            continue
        backend_id = node.get("backendDOMNodeId")
        if not isinstance(backend_id, int):
            continue
        try:
            box = cdp.send("DOM.getBoxModel", backendNodeId=backend_id)
        except Exception:
            continue  # detached/hidden node — no box model
        center = _quad_center((box or {}).get("model", {}).get("quad")) or _quad_center(
            (box or {}).get("quad")
        )
        if center is None:
            continue
        x, y = center
        if x < 0 or y < 0:
            continue
        key = (role_l, name, round(x), round(y))
        if key in seen:
            continue
        seen.add(key)
        elements.append({
            "role": role,
            "name": name[:200],
            "x": round(x),
            "y": round(y),
            "backendDOMNodeId": backend_id,
        })
        if len(elements) >= limit:
            break
    return elements


def _clamp_to_viewport(page, x, y):
    """Clamp coordinates into the current viewport so mouse clicks land."""
    try:
        vp = page.viewport_size or {}
        w, h = vp.get("width"), vp.get("height")
        if isinstance(w, (int, float)) and w > 0:
            x = max(0, min(int(x), int(w) - 1))
        if isinstance(h, (int, float)) and h > 0:
            y = max(0, min(int(y), int(h) - 1))
    except Exception:
        pass
    return int(x), int(y)


def _open_cdp_session(page):
    """Create a CDP session bound to the page. Caller must detach it."""
    return page.context.new_cdp_session(page)


@browser_ax_bp.route("/browser/ax_find", methods=["POST"])
def route_browser_ax_find():
    """List clickable elements by accessibility role/name with click coords.

    Body (all optional): {role: "button", filter: "sign in", limit: 100}
    Returns {url, count, elements: [{role, name, x, y}]}.
    """
    data = _json_payload()
    role = data.get("role")
    name_filter = data.get("filter") or data.get("name")
    try:
        limit = max(1, min(int(data.get("limit", _AX_NODE_LIMIT)), _AX_NODE_LIMIT))
    except (TypeError, ValueError):
        limit = _AX_NODE_LIMIT

    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        cdp = None
        try:
            cdp = _open_cdp_session(page)
            elements = _get_ax_elements(page, cdp, role_filter=role,
                                        name_filter=name_filter, limit=limit)
            # Coordinates are viewport-relative; drop backend ids from output.
            public = [{k: v for k, v in e.items() if k != "backendDOMNodeId"}
                      for e in elements]
            return jsonify({"url": page.url, "count": len(public), "elements": public})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)
        finally:
            if cdp is not None:
                try:
                    cdp.detach()
                except Exception:
                    pass


@browser_ax_bp.route("/browser/ax_click", methods=["POST"])
def route_browser_ax_click():
    """Click the first AX node whose accessible name matches {name}.

    Matching: case-insensitive exact match first, then case-insensitive
    substring. Optional {role: "button"} narrows the search.
    Click is dispatched at the element's computed center via page.mouse.
    """
    data = _json_payload()
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return _error("name is required")
    name = name.strip()
    role = data.get("role")
    timeout_ms = data.get("timeout", 10000)

    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        cdp = None
        try:
            url_before = page.url
            cdp = _open_cdp_session(page)
            elements = _get_ax_elements(page, cdp, role_filter=role)
            needle = name.lower()
            match = next(
                (e for e in elements if e["name"].lower() == needle), None
            ) or next(
                (e for e in elements if needle in e["name"].lower()), None
            )
            if match is None:
                return _error(f"no accessibility node matches name {name!r}", 404,
                              url=page.url, searched=len(elements))
            x, y = _clamp_to_viewport(page, match["x"], match["y"])
            page.mouse.click(x, y)
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            return jsonify({
                "status": "clicked",
                "role": match["role"],
                "name": match["name"],
                "x": x,
                "y": y,
                "url": page.url,
                "url_before": url_before,
                "url_changed": page.url != url_before,
                "title": title,
            })
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)
        finally:
            if cdp is not None:
                try:
                    cdp.detach()
                except Exception:
                    pass


def register_routes(app, state, require_auth):
    app.register_blueprint(browser_ax_bp)
    _wrap_registered_blueprint_routes(app, browser_ax_bp.name, require_auth)

"""UIA accessibility tree, SOM overlay, and element-find routes."""
import sys, base64, time, threading, hashlib
from io import BytesIO
from pathlib import Path
from flask import jsonify, request
from shared import _json_body, _log, _console, _missing_field, COAGENT_DIR

_uia_engine = None
def _get_uia_engine():
    global _uia_engine
    if _uia_engine is None:
        sys.path.insert(0, str(COAGENT_DIR))
        import uia_engine as ue
        _uia_engine = ue
    return _uia_engine

HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    pass

# SOM diff cache
_som_cache = {}
_som_cache_ts = {}
_SOM_CACHE_TTL = 1.0

def register_routes(app, state, require_auth):
    ue = _get_uia_engine()

    @app.route("/uia/tree", methods=["GET"])
    def route_uia_tree():
        snap = ue.uia_snapshot()
        if snap.get("success"):
            return jsonify(snap.get("tree", {}))
        return jsonify({"error": snap.get("error", "UIA timeout"), "windows": []})

    @app.route("/uia/snapshot", methods=["GET"])
    def route_uia_snapshot():
        return route_uia_tree()

    @app.route("/uia/find/<name>", methods=["GET"])
    def route_uia_find(name):
        results = ue.uia_find_deep(name)
        return jsonify({"query": name, "count": len(results), "results": results})

    @app.route("/uia/click", methods=["POST"])
    @require_auth
    def route_uia_click():
        d = _json_body()
        index = d.get("index")
        name = d.get("name")
        if name:
            result = ue.find_on_screen(name)
        elif index is not None:
            result = ue.find_on_screen(str(index))
        else:
            return _missing_field("name or index")
        return jsonify({"status": "queried" if result else "failed", "name": name, "index": index})

    @app.route("/uia/find-cmb", methods=["POST"])
    def route_uia_find_cmb():
        """Combined UIA + text find."""
        d = _json_body()
        text = d.get("text", "")
        matches = []
        if ue.UIA_READY:
            snap = ue.uia_snapshot()
            if snap.get("success"):
                needle = text.lower()
                for win in snap.get("tree", {}).get("children", []):
                    if needle in win.get("name", "").lower():
                        matches.append({"method": "uia", "name": win.get("name", ""),
                                        "control_type": win.get("control_type", ""),
                                        "rect": win.get("rect", {})})
                    for child in win.get("children", []):
                        if needle in child.get("name", "").lower():
                            matches.append({"method": "uia", "name": child.get("name", ""),
                                            "control_type": child.get("control_type", ""),
                                            "rect": child.get("rect", {})})
        return jsonify({"query": text, "count": len(matches), "matches": matches})

    @app.route("/uia/diag", methods=["GET"])
    def route_uia_diag():
        return jsonify({"ready": ue.UIA_READY, "error": getattr(ue, "_uia_error", "")})

    @app.route("/uia/window-tree", methods=["GET"])
    def route_uia_window_tree():
        snap = ue.uia_snapshot()
        if snap.get("success"):
            return jsonify(snap.get("tree", {}))
        return jsonify({"error": snap.get("error", "UIA timeout")})

    @app.route("/uia/element/find", methods=["POST"])
    def route_uia_element_find():
        d = _json_body()
        query = d.get("query", "")
        mode = d.get("mode", "name")
        results = []
        snap = ue.uia_snapshot()
        if snap.get("success"):
            needle = query.lower()
            for win in snap.get("tree", {}).get("children", []):
                for child in win.get("children", []):
                    match = False
                    if mode == "name" and needle in child.get("name", "").lower(): match = True
                    elif mode == "control_type" and needle == child.get("control_type", "").lower(): match = True
                    if match:
                        results.append(child)
        return jsonify({"query": query, "mode": mode, "count": len(results), "results": results})

    @app.route("/uia/element/click-by-name", methods=["POST"])
    @require_auth
    def route_uia_element_click_name():
        d = _json_body()
        name = d.get("name", "")
        result = ue.find_on_screen(name)
        return jsonify({"name": name, "found": bool(result) if isinstance(result, dict) else False})

    @app.route("/uia/element/click-by-index", methods=["POST"])
    @require_auth
    def route_uia_element_click_index():
        d = _json_body()
        index = int(d.get("index", 0))
        result = ue.find_on_screen(str(index))
        return jsonify({"index": index, "found": bool(result)})

    @app.route("/som/screenshot", methods=["GET"])
    def route_som_screenshot():
        """SOM overlay with numbered elements."""
        try:
            from routes_ocr import _capture_raw
            data = _capture_raw(force=True)
            if not data or not HAS_PIL:
                return jsonify({"error": "No screenshot or PIL"}), 500
            img = Image.open(BytesIO(data))
            draw = ImageDraw.Draw(img)
            snap = ue.uia_snapshot()
            elements = []
            if snap.get("success"):
                idx = 1
                for win in snap.get("tree", {}).get("children", []):
                    r = win.get("rect")
                    if r and all(k in r for k in ("left", "top", "width", "height")):
                        x, y, w, h = r["left"], r["top"], r["width"], r["height"]
                        if w >= 20 and h >= 20:
                            cx, cy = x + w // 2, y + 8
                            draw.ellipse([cx-10, cy-10, cx+10, cy+10], fill="red")
                            draw.text((cx-4, cy-6), str(idx), fill="white")
                            draw.rectangle([x, y, x+w, y+h], outline="red", width=2)
                            elements.append({"index": idx, "name": win.get("name", ""),
                                             "control_type": win.get("control_type", "Window"),
                                             "x": cx, "y": cy, "width": w, "height": h})
                            idx += 1
            buf = BytesIO()
            img.save(buf, format="PNG")
            return jsonify({"labeled_screenshot": base64.b64encode(buf.getvalue()).decode(), "elements": elements})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/som/image", methods=["GET"])
    def route_som_image():
        return route_som_screenshot()

    @app.route("/som/cache/clear", methods=["GET"])
    def route_som_cache_clear():
        _som_cache.clear()
        _som_cache_ts.clear()
        return jsonify({"status": "cleared"})

    @app.route("/som/bridge", methods=["GET"])
    def route_som_bridge():
        return route_som_screenshot()

    @app.route("/som/per-window", methods=["GET"])
    def route_som_per_window():
        return route_som_screenshot()

    @app.route("/som/point", methods=["POST"])
    def route_som_point():
        d = _json_body()
        px = int(d.get("x", 0))
        py = int(d.get("y", 0))
        snap = ue.uia_snapshot()
        matches = []
        if snap.get("success"):
            for win in snap.get("tree", {}).get("children", []):
                r = win.get("rect")
                if r:
                    rx, ry, rw, rh = r.get("left", 0), r.get("top", 0), r.get("width", 0), r.get("height", 0)
                    if rx <= px <= rx + rw and ry <= py <= ry + rh:
                        matches.append({"name": win.get("name", ""), "control_type": win.get("control_type", ""),
                                        "rect": r, "distance": min(px-rx, rx+rw-px, py-ry, ry+rh-py)})
        matches.sort(key=lambda m: m.get("distance", 9999))
        return jsonify({"x": px, "y": py, "count": len(matches), "matches": matches[:10]})

    @app.route("/uia/accel-reg", methods=["GET"])
    def route_uia_accel():
        if hasattr(ue, "_ACCEL_REGIONS"):
            return jsonify({"regions": {k: v for k, v in ue._ACCEL_REGIONS.items()}})
        return jsonify({"regions": {}})

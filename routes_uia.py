"""UIA accessibility tree, SOM overlay, and element-find routes."""
import sys
import threading
from pathlib import Path
from flask import jsonify, request
from shared import _json_body, _log, _missing_field, COAGENT_DIR

_uia_engine = None
_uia_engine_lock = threading.Lock()

def _get_uia_engine():
    global _uia_engine
    if _uia_engine is None:
        with _uia_engine_lock:
            if _uia_engine is None:
                if str(COAGENT_DIR) not in sys.path:
                    sys.path.insert(0, str(COAGENT_DIR))
                import uia_engine as ue
                _uia_engine = ue
    return _uia_engine

HAS_PIL = False
try:
    from PIL import Image  # noqa: F401 — required for SOM overlays
    HAS_PIL = True
except ImportError:
    pass

# SOM diff cache
_som_cache = {}
_som_cache_ts = {}
_SOM_CACHE_TTL = 1.0


def _norm_text(value):
    return " ".join(str(value or "").casefold().split())


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _levenshtein(a, b, max_distance=3):
    """Bounded Levenshtein distance for short OCR/UIA labels."""
    a = _norm_text(a)
    b = _norm_text(b)
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        row_min = current[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def _walk_uia_nodes(node, depth=0, max_depth=6):
    if not isinstance(node, dict) or depth > max_depth:
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk_uia_nodes(child, depth + 1, max_depth=max_depth)


def _rect_payload(rect):
    if not isinstance(rect, dict):
        return None
    try:
        left = int(rect.get("left", rect.get("x", 0)))
        top = int(rect.get("top", rect.get("y", 0)))
        width = int(rect.get("width", 0))
        height = int(rect.get("height", 0))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"x": left, "y": top, "width": width, "height": height}


def _uia_candidate_score(node, needle, type_hint=""):
    needle_n = _norm_text(needle)
    type_hint_n = _norm_text(type_hint)
    name = _norm_text(node.get("name"))
    automation_id = _norm_text(node.get("automation_id"))
    control_type = _norm_text(node.get("control_type"))
    class_name = _norm_text(node.get("class_name"))
    haystacks = [name, automation_id, control_type, class_name]

    best = None
    for value in haystacks:
        if not value:
            continue
        if value == needle_n:
            score = 0
        elif needle_n and needle_n in value:
            score = 1
        elif value and value in needle_n:
            score = 2
        else:
            distance = _levenshtein(value, needle_n, max_distance=2)
            if distance < 3:
                score = 3 + distance
            else:
                continue
        if best is None or score < best:
            best = score

    if best is None:
        return None
    if type_hint_n:
        if type_hint_n == control_type or type_hint_n in control_type:
            best -= 1
        else:
            best += 4
    return best


def _find_uia_candidate(ue, text, type_hint=""):
    candidates = []
    try:
        snap = ue.uia_snapshot(timeout=5)
    except Exception as exc:
        snap = {"success": False, "error": str(exc)}

    if snap.get("success"):
        for node in _walk_uia_nodes(snap.get("tree", {})):
            rect = _rect_payload(node.get("rect"))
            if not rect:
                continue
            score = _uia_candidate_score(node, text, type_hint)
            if score is None:
                continue
            candidates.append((score, node, rect))
    else:
        _log(f"[uia] hybrid UIA snapshot failed: {snap.get('error', 'unknown')}")

    if not candidates:
        try:
            for node in ue.uia_find_deep(text):
                if not isinstance(node, dict) or node.get("error"):
                    continue
                rect = _rect_payload(node.get("rect"))
                if not rect:
                    continue
                score = _uia_candidate_score(node, text, type_hint)
                if score is not None:
                    candidates.append((score, node, rect))
        except Exception as exc:
            _log(f"[uia] hybrid uia_find_deep failed: {type(exc).__name__}: {exc}")

    if not candidates:
        return None
    score, node, rect = sorted(
        candidates,
        key=lambda item: (item[0], item[2]["width"] * item[2]["height"]),
    )[0]
    return {
        "found": True,
        "method": "uia",
        "x": rect["x"],
        "y": rect["y"],
        "width": rect["width"],
        "height": rect["height"],
        "center": {"x": rect["x"] + rect["width"] // 2, "y": rect["y"] + rect["height"] // 2},
        "element_info": {
            "name": node.get("name", ""),
            "automation_id": node.get("automation_id", ""),
            "control_type": node.get("control_type", ""),
            "class_name": node.get("class_name", ""),
            "rect": node.get("rect"),
            "score": score,
        },
    }


def _parse_confidence(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ocr_value(ocr_data, key, index, default=0):
    values = ocr_data.get(key)
    if not isinstance(values, list) or index >= len(values):
        return default
    return values[index]


def _ocr_candidates_from_data(ocr_data):
    words = []
    texts = ocr_data.get("text", []) or []
    for index, raw_text in enumerate(texts):
        text = str(raw_text or "").strip()
        if not text:
            continue
        try:
            left = int(ocr_data["left"][index])
            top = int(ocr_data["top"][index])
            width = int(ocr_data["width"][index])
            height = int(ocr_data["height"][index])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if width <= 3 or height <= 3:
            continue
        line_key = (
            _ocr_value(ocr_data, "block_num", index),
            _ocr_value(ocr_data, "par_num", index),
            _ocr_value(ocr_data, "line_num", index),
        )
        words.append({
            "text": text,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "confidence": _parse_confidence(_ocr_value(ocr_data, "conf", index)),
            "line_key": line_key,
        })
    return words


def _merge_word_candidate(words):
    text = " ".join(word["text"] for word in words)
    left = min(word["left"] for word in words)
    top = min(word["top"] for word in words)
    right = max(word["left"] + word["width"] for word in words)
    bottom = max(word["top"] + word["height"] for word in words)
    confidence = sum(word.get("confidence", 0.0) for word in words) / max(1, len(words))
    return {
        "text": text,
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
        "confidence": round(confidence, 2),
    }


def _find_ocr_candidate(text):
    try:
        import pytesseract
        from routes_ocr import _screen_img

        image = _screen_img(force=True)
        if image is None:
            return None
        ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = _ocr_candidates_from_data(ocr_data)
    except ImportError as exc:
        _log(f"[uia] hybrid OCR unavailable: {exc}")
        return None
    except Exception as exc:
        _log(f"[uia] hybrid OCR failed: {type(exc).__name__}: {exc}")
        return None

    needle = _norm_text(text)
    if not needle:
        return None
    needle_word_count = max(1, len(needle.split()))
    best = None
    best_distance = 999
    max_window = min(max(needle_word_count + 2, 3), 8)
    grouped = {}
    for word in words:
        grouped.setdefault(word["line_key"], []).append(word)
    for line_words in grouped.values():
        line_words.sort(key=lambda item: item["left"])
        for start in range(len(line_words)):
            for size in range(1, max_window + 1):
                chunk = line_words[start:start + size]
                if not chunk:
                    continue
                candidate = _merge_word_candidate(chunk)
                candidate_text = _norm_text(candidate["text"])
                if candidate_text == needle:
                    distance = 0
                elif needle in candidate_text:
                    distance = 1
                else:
                    distance = _levenshtein(candidate_text, needle, max_distance=2)
                if distance < 3 and distance < best_distance:
                    best = candidate
                    best_distance = distance
    if not best:
        return None
    return {
        "found": True,
        "method": "ocr",
        "x": best["x"],
        "y": best["y"],
        "width": best["width"],
        "height": best["height"],
        "center": {"x": best["x"] + best["width"] // 2, "y": best["y"] + best["height"] // 2},
        "element_info": {
            "text": best["text"],
            "confidence": best["confidence"],
            "distance": best_distance,
        },
    }


def _find_hybrid_element(ue, text, type_hint="", fallback_to_ocr=True):
    found = _find_uia_candidate(ue, text, type_hint)
    if found:
        return found
    if fallback_to_ocr:
        found = _find_ocr_candidate(text)
        if found:
            return found
    return {"found": False}


def _response_payload(result):
    response = result
    status_code = getattr(result, "status_code", 200)
    if isinstance(result, tuple):
        response = result[0]
        if len(result) > 1:
            status_code = result[1]
    if hasattr(response, "get_json"):
        payload = response.get_json(silent=True)
    else:
        payload = response
    return payload, status_code


def _type_text(text, state):
    from routes_mouse import _key_action

    return _key_action("type", text, state)


def _ocr_screen_text():
    import pytesseract
    from routes_ocr import _screen_img

    image = _screen_img(force=True)
    if image is None:
        raise RuntimeError("screenshot unavailable")
    return pytesseract.image_to_string(image)


def _safe_icon_path(icon_path):
    """Constrain icon template lookups to COAGENT_DIR/templates.

    Rejects empty, absolute, and '..'-traversal paths so callers cannot point
    the template matcher at arbitrary files. Returns a resolved path string or
    None when the input is not allowed.
    """
    if not icon_path or not isinstance(icon_path, str):
        return None
    p = Path(icon_path)
    if p.is_absolute() or ".." in p.parts:
        return None
    templates_dir = (COAGENT_DIR / "templates").resolve()
    resolved = (templates_dir / p).resolve()
    try:
        resolved.relative_to(templates_dir)
    except ValueError:
        return None
    return str(resolved)


def register_routes(app, state, require_auth):
    ue = _get_uia_engine()

    @app.route("/uia/tree", methods=["GET"])
    @require_auth
    def route_uia_tree():
        snap = ue.uia_snapshot()
        if snap.get("success"):
            return jsonify(snap.get("tree", {}))
        return jsonify({"error": snap.get("error", "UIA timeout"), "windows": []})

    @app.route("/uia/snapshot", methods=["GET"])
    @require_auth
    def route_uia_snapshot():
        return route_uia_tree()

    @app.route("/uia/find/<name>", methods=["GET"])
    @require_auth
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
    @require_auth
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

    @app.route("/uia/find-hybrid", methods=["POST"])
    @require_auth
    def route_uia_find_hybrid():
        d = _json_body()
        text = (d.get("text") or d.get("name") or d.get("automation_id") or "").strip()
        if not text:
            return _missing_field("text")
        type_hint = (d.get("type") or d.get("control_type") or "").strip()
        fallback_to_ocr = _as_bool(d.get("fallback_to_ocr"), True)
        result = _find_hybrid_element(ue, text, type_hint, fallback_to_ocr=fallback_to_ocr)
        result["query"] = text
        if type_hint:
            result["type"] = type_hint
        if not result.get("found"):
            result.setdefault("error", f"Element {text!r} not found via UIA or OCR")
            result.setdefault("suggestion",
                "Try POST /som/annotate to see all numbered elements, or check /uia/diag")
            result.setdefault("code", "ELEMENT_NOT_FOUND")
        return jsonify(result)

    @app.route("/uia/find", methods=["POST"])
    @require_auth
    def route_uia_find_post():
        d = _json_body()
        text = (d.get("text") or d.get("name") or d.get("automation_id") or "").strip()
        if not text:
            return _missing_field("text")
        type_hint = (d.get("type") or d.get("control_type") or "").strip()
        fallback_to_ocr = _as_bool(d.get("fallback_to_ocr"), True)
        result = _find_hybrid_element(ue, text, type_hint, fallback_to_ocr=fallback_to_ocr)
        result["query"] = text
        if type_hint:
            result["type"] = type_hint
        return jsonify(result)

    @app.route("/uia/type", methods=["POST"])
    @require_auth
    def route_uia_type():
        d = _json_body()
        text = d.get("text")
        if not isinstance(text, str) or text == "":
            return _missing_field("text")
        return _type_text(text, state)

    @app.route("/uia/ocr", methods=["POST"])
    @require_auth
    def route_uia_ocr():
        try:
            text = _ocr_screen_text()
            return jsonify({"text": text})
        except Exception as exc:
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    @app.route("/uia/text", methods=["POST"])
    @require_auth
    def route_uia_text():
        """
        Extract all visible text from a window using UIA — no OCR needed.
        Much faster and more accurate than OCR for native Windows apps.
        Body: {window: "Calculator"} or {selector: "editfield"} or {} for active window.
        Returns text_elements list with positions and full_text string.
        """
        d = _json_body()
        window_title = (d.get("window") or d.get("title") or "").strip()
        selector = (d.get("selector") or d.get("element") or "").strip()

        try:
            snap = ue.uia_snapshot(timeout=5)
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": "UIA snapshot failed",
                "detail": f"{type(exc).__name__}: {exc}",
                "suggestion": "Check GET /uia/diag to verify UIA availability",
                "code": "UIA_SNAPSHOT_FAILED",
            }), 500

        if not snap.get("success"):
            return jsonify({
                "ok": False,
                "error": "UIA not ready",
                "detail": snap.get("error", "uia_snapshot returned success=false"),
                "suggestion": "UIA requires an interactive Windows session; check /uia/diag",
                "code": "UIA_NOT_READY",
            }), 503

        SKIP_CTRL = {"window", "pane", "group", "toolbar", "statusbar", "titlebar",
                     "scrollbar", "menubar", "appbar", "semantic zoom"}
        texts = []

        def collect_text(node, depth=0):
            if not isinstance(node, dict) or depth > 12:
                return
            name = str(node.get("name") or "").strip()
            ctrl = str(node.get("control_type", "")).lower()
            if "." in ctrl:
                ctrl = ctrl.rsplit(".", 1)[-1]
            if name and ctrl not in SKIP_CTRL:
                rect = _rect_payload(node.get("rect"))
                if rect:
                    texts.append({
                        "text": name,
                        "control_type": ctrl or "unknown",
                        "x": rect["x"],
                        "y": rect["y"],
                        "width": rect["width"],
                        "height": rect["height"],
                        "center": {
                            "x": rect["x"] + rect["width"] // 2,
                            "y": rect["y"] + rect["height"] // 2,
                        },
                        "automation_id": node.get("automation_id", ""),
                        "value": node.get("value", ""),
                    })
            for child in node.get("children", []) or []:
                collect_text(child, depth + 1)

        tree = snap.get("tree", {})
        windows = tree.get("children", []) or []
        matched_window = ""

        if window_title:
            needle = window_title.lower()
            matched = False
            for win in windows:
                win_name = str(win.get("name", "")).lower()
                if win_name and (needle in win_name or win_name in needle):
                    matched_window = win.get("name", "")
                    collect_text(win)
                    matched = True
                    break
            if not matched:
                available = [w.get("name", "") for w in windows[:10]]
                return jsonify({
                    "ok": False,
                    "error": f"Window {window_title!r} not found",
                    "detail": f"Available windows: {available}",
                    "suggestion": "Use exact window title substring or omit to use active window",
                    "code": "WINDOW_NOT_FOUND",
                }), 404
        elif selector:
            needle = selector.lower()
            for win in windows:
                for node in _walk_uia_nodes(win):
                    name = str(node.get("name") or "").lower()
                    auto_id = str(node.get("automation_id") or "").lower()
                    if needle in name or needle in auto_id:
                        rect = _rect_payload(node.get("rect"))
                        if rect:
                            ctrl = str(node.get("control_type", "")).lower()
                            if "." in ctrl:
                                ctrl = ctrl.rsplit(".", 1)[-1]
                            texts.append({
                                "text": node.get("name", ""),
                                "control_type": ctrl or "unknown",
                                "x": rect["x"],
                                "y": rect["y"],
                                "width": rect["width"],
                                "height": rect["height"],
                                "center": {
                                    "x": rect["x"] + rect["width"] // 2,
                                    "y": rect["y"] + rect["height"] // 2,
                                },
                                "automation_id": node.get("automation_id", ""),
                                "value": node.get("value", ""),
                            })
        else:
            # Active window heuristic: skip desktop/Program Manager
            DESKTOP_NAMES = {"program manager", "desktop", ""}
            for win in windows[:5]:
                win_name = str(win.get("name", "")).lower()
                if win_name in DESKTOP_NAMES:
                    continue
                matched_window = win.get("name", "")
                collect_text(win)
                if texts:
                    break

        full_text = " ".join(t["text"] for t in texts if t.get("text"))
        return jsonify({
            "ok": True,
            "window": matched_window,
            "text_elements": texts,
            "full_text": full_text,
            "count": len(texts),
            "method": "uia",
        })

    @app.route("/uia/click-hybrid", methods=["POST"])
    @require_auth
    def route_uia_click_hybrid():
        d = _json_body()
        text = (d.get("text") or d.get("name") or d.get("automation_id") or "").strip()
        if not text:
            return _missing_field("text")
        type_hint = (d.get("type") or d.get("control_type") or "").strip()
        result = _find_hybrid_element(ue, text, type_hint, fallback_to_ocr=_as_bool(d.get("fallback_to_ocr"), True))
        result["query"] = text
        if not result.get("found"):
            return jsonify(result)
        try:
            from routes_mouse import _mouse_action
            center = result.get("center") or {}
            click_result = _mouse_action(
                "click",
                int(center.get("x", result["x"] + result["width"] // 2)),
                int(center.get("y", result["y"] + result["height"] // 2)),
                d.get("button", "left"),
                d.get("background", True),
                state,
            )
            payload, status_code = _response_payload(click_result)
            result["clicked"] = status_code < 400
            result["click_result"] = payload
            return jsonify(result), status_code
        except Exception as exc:
            result["clicked"] = False
            result["error"] = f"{type(exc).__name__}: {exc}"
            return jsonify(result), 500

    @app.route("/uia/diag", methods=["GET"])
    @require_auth
    def route_uia_diag():
        return jsonify({"ready": ue.UIA_READY, "error": getattr(ue, "_uia_error", "")})

    @app.route("/uia/window-tree", methods=["GET"])
    @require_auth
    def route_uia_window_tree():
        snap = ue.uia_snapshot()
        if snap.get("success"):
            return jsonify(snap.get("tree", {}))
        return jsonify({"error": snap.get("error", "UIA timeout")})

    @app.route("/uia/element/find", methods=["POST"])
    @require_auth
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
        index = _safe_int(d.get("index", 0))
        if index is None:
            return jsonify({"error": "index must be an integer"}), 400
        result = ue.find_on_screen(str(index))
        return jsonify({"index": index, "found": bool(result)})

    @app.route("/som/screenshot", methods=["GET"])
    @require_auth
    def route_som_screenshot():
        """SOM overlay with numbered elements."""
        from routes_ocr import _request_monitor
        return _som_monitor_response(_request_monitor(0))

    def _som_monitor_response(monitor_index=0):
        try:
            from routes_ocr import _capture_raw, _coerce_monitor_index
            monitor_index = _coerce_monitor_index(monitor_index)
            data = _capture_raw(force=True, monitor_index=monitor_index)
            if not data or not HAS_PIL:
                return jsonify({"error": "No screenshot or PIL", "monitor_index": monitor_index}), 500
            result = ue.som_overlay(data, monitor_index=monitor_index)
            status = 200 if result.get("success", True) else 500
            return jsonify(result), status
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/som/per-monitor/<int:monitor_id>", methods=["GET"])
    @require_auth
    def route_som_per_monitor(monitor_id):
        return _som_monitor_response(monitor_id)

    @app.route("/som/image", methods=["GET"])
    @require_auth
    def route_som_image():
        return route_som_screenshot()

    @app.route("/som/cache/clear", methods=["GET"])
    @require_auth
    def route_som_cache_clear():
        _som_cache.clear()
        _som_cache_ts.clear()
        return jsonify({"status": "cleared"})

    @app.route("/som/bridge", methods=["GET"])
    @require_auth
    def route_som_bridge():
        return route_som_screenshot()

    @app.route("/som/per-window", methods=["GET"])
    @require_auth
    def route_som_per_window():
        return route_som_screenshot()

    @app.route("/som/point", methods=["POST"])
    @require_auth
    def route_som_point():
        d = _json_body()
        px = _safe_int(d.get("x", 0))
        py = _safe_int(d.get("y", 0))
        if px is None or py is None:
            return jsonify({"error": "x and y must be integers"}), 400
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
    @require_auth
    def route_uia_accel():
        if hasattr(ue, "_ACCEL_REGIONS"):
            return jsonify({"regions": {k: v for k, v in ue._ACCEL_REGIONS.items()}})
        return jsonify({"regions": {}})

    # ── Adaptive Find (v8.2) ───────────────────────────────────────────
    @app.route("/uia/adaptive-find", methods=["POST"])
    @require_auth
    def route_adaptive_find():
        d = _json_body()
        target = d.get("target", "")
        screenshot = d.get("screenshot")
        result = ue.adaptive_find(target, screenshot)
        return jsonify(result)

    # ── SoM Visual Fallback (v8.2) ─────────────────────────────────────
    @app.route("/uia/som-fallback", methods=["GET", "POST"])
    @require_auth
    def route_som_fallback():
        if request.method == "POST":
            d = _json_body()
            screenshot = d.get("screenshot")
        else:
            screenshot = request.args.get("screenshot")
        result = ue.som_visual_fallback(screenshot)
        return jsonify(result)

    # ── Icon/Logo Click by Template Matching (v8.2) ───────────────────
    @app.route("/icon/find", methods=["POST"])
    @require_auth
    def route_icon_find():
        d = _json_body()
        icon_path = _safe_icon_path(d.get("icon_path", ""))
        if icon_path is None:
            return jsonify({"found": False, "error": "Invalid icon_path", "strategy": "template_match"}), 400
        threshold = _safe_float(d.get("threshold", 0.8))
        if threshold is None:
            return jsonify({"found": False, "error": "threshold must be a number", "strategy": "template_match"}), 400
        result = ue.find_icon_by_template(icon_path, threshold)
        return jsonify(result)

    @app.route("/icon/click", methods=["POST"])
    @require_auth
    def route_icon_click():
        d = _json_body()
        icon_path = _safe_icon_path(d.get("icon_path", ""))
        if icon_path is None:
            return jsonify({"found": False, "error": "Invalid icon_path", "strategy": "template_match"}), 400
        threshold = _safe_float(d.get("threshold", 0.8))
        if threshold is None:
            return jsonify({"found": False, "error": "threshold must be a number", "strategy": "template_match"}), 400
        button = d.get("button", "left")
        result = ue.click_icon_by_template(icon_path, threshold, button)
        return jsonify(result)

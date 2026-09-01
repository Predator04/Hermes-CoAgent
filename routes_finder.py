"""Smart OCR-backed element finder routes."""

import base64
import io
import json
import re
import urllib.error
import urllib.request
from difflib import SequenceMatcher

from flask import Blueprint, jsonify, request

from shared import _self_port, COAGENT_DIR, _console, _json_body


STOP_WORDS = {
    "a", "an", "and", "at", "box", "button", "click", "control", "element",
    "field", "find", "for", "input", "in", "label", "link", "me", "of", "on",
    "screen", "text", "the", "to", "type", "with",
}
POSITION_WORDS = {"top", "bottom", "left", "right", "middle", "center", "centre"}


def _auth_header():
    token_file = COAGENT_DIR / ".token"
    if token_file.exists():
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except Exception:
            token = ""
        # Validate token to prevent header injection
        if token and "\n" not in token and "\r" not in token:
            return f"Bearer {token}"
    return request.headers.get("Authorization", "")


def _coagent_post(path, data):
    token = _auth_header()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{_self_port()}{path}",
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read()
            return json.loads(body.decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"error": body or str(exc)}
        payload.setdefault("status_code", exc.code)
        return payload
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _terms_and_hints(description):
    words = re.findall(r"[a-z0-9]+", str(description).lower())
    hints = {word for word in words if word in POSITION_WORDS}
    terms = [word for word in words if word not in STOP_WORDS and word not in POSITION_WORDS and len(word) > 1]
    if not terms:
        terms = [word for word in words if word not in POSITION_WORDS and len(word) > 1]
    return terms, hints


def _decode_screenshot(screenshot):
    if not screenshot:
        return None
    from PIL import Image

    max_bytes = 50 * 1024 * 1024  # 50 MB
    max_pixels = 50_000_000

    if isinstance(screenshot, bytes):
        raw = screenshot.decode("utf-8", errors="ignore")
    else:
        raw = str(screenshot)
    if raw.lstrip().lower().startswith("data:"):
        if "," not in raw:
            raise ValueError("malformed data URI: missing comma separator")
        raw = raw.split(",", 1)[1]
    # Pre-check encoded size before decoding (base64 expands ~4/3 over raw bytes)
    if len(raw) > (max_bytes * 4 // 3) + 4:
        raise ValueError(f"screenshot too large ({len(raw)} encoded chars)")
    data = base64.b64decode(raw)
    if len(data) > max_bytes:
        raise ValueError(f"screenshot too large ({len(data)} bytes)")
    img = Image.open(io.BytesIO(data))
    try:
        width, height = img.size
        if width * height > max_pixels:
            raise ValueError(f"screenshot dimensions too large ({width}x{height})")
        return img.convert("RGB")
    finally:
        img.close()


def _fresh_screenshot():
    import mss as _mss_mod
    from PIL import Image as _PILImage

    try:
        with _mss_mod.mss() as _sct:
            _mon = _sct.monitors[0]
            _sct_img = _sct.grab(_mon)
            return _PILImage.frombytes("RGB", _sct_img.size, _sct_img.rgb).convert("RGB")
    except Exception:
        try:
            with _mss_mod.mss() as _sct:
                _mon = _sct.monitors[1] if len(_sct.monitors) > 1 else _sct.monitors[0]
                _sct_img = _sct.grab(_mon)
                return _PILImage.frombytes("RGB", _sct_img.size, _sct_img.rgb).convert("RGB")
        except Exception:
            from PIL import ImageGrab
            return ImageGrab.grab().convert("RGB")


def _candidate_from_ocr_match(match):
    if not isinstance(match, dict) or match.get("error"):
        return None
    bounds = match.get("bounds") if isinstance(match.get("bounds"), dict) else {}
    center = match.get("center") if isinstance(match.get("center"), dict) else {}
    width = int(bounds.get("width", match.get("w", 0)) or 0)
    height = int(bounds.get("height", match.get("h", 0)) or 0)
    x = bounds.get("x", match.get("x"))
    y = bounds.get("y", match.get("y"))
    if x is None and center:
        x = int(center.get("x", 0)) - width // 2
    if y is None and center:
        y = int(center.get("y", 0)) - height // 2
    if x is None or y is None:
        return None
    try:
        confidence = float(match.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "text": str(match.get("text", "")),
        "x": int(x),
        "y": int(y),
        "w": max(1, width),
        "h": max(1, height),
        "confidence": confidence,
    }


def _ocr_candidates_from_image(image):
    try:
        import pytesseract
    except ImportError:
        return [], "pytesseract not installed"

    try:
        ocr = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except Exception as exc:
        return [], str(exc)

    candidates = []
    lines = {}
    texts = ocr.get("text", [])
    confs = ocr.get("conf") or []
    blk = ocr.get("block_num") or []
    par = ocr.get("par_num") or []
    lin = ocr.get("line_num") or []
    for index, text in enumerate(texts):
        text = str(text or "").strip()
        if not text:
            continue
        try:
            confidence = float(confs[index]) if index < len(confs) else 0.0
        except (TypeError, ValueError, IndexError):
            confidence = 0.0
        try:
            x = int(ocr["left"][index])
            y = int(ocr["top"][index])
            w = int(ocr["width"][index])
            h = int(ocr["height"][index])
        except (IndexError, KeyError):
            continue
        if w <= 0 or h <= 0:
            continue
        candidates.append({"text": text, "x": x, "y": y, "w": w, "h": h, "confidence": max(0.0, confidence), "ocr_conf": max(0.0, confidence)})
        line_key = (
            blk[index] if index < len(blk) else 0,
            par[index] if index < len(par) else 0,
            lin[index] if index < len(lin) else 0,
        )
        line = lines.setdefault(line_key, {"texts": [], "xs": [], "ys": [], "rights": [], "bottoms": [], "confs": []})
        line["texts"].append(text)
        line["xs"].append(x)
        line["ys"].append(y)
        line["rights"].append(x + w)
        line["bottoms"].append(y + h)
        line["confs"].append(max(0.0, confidence))

    for line in lines.values():
        if len(line["texts"]) < 2:
            continue
        text = " ".join(line["texts"])
        x = min(line["xs"])
        y = min(line["ys"])
        right = max(line["rights"])
        bottom = max(line["bottoms"])
        candidates.append({
            "text": text,
            "x": x,
            "y": y,
            "w": max(1, right - x),
            "h": max(1, bottom - y),
            "confidence": round(sum(line["confs"]) / max(1, len(line["confs"])), 2),
            "ocr_conf": round(sum(line["confs"]) / max(1, len(line["confs"])), 2),
        })
    return candidates, None


def _score_candidate(candidate, description, terms, hints, image_size):
    text = str(candidate.get("text", "")).lower()
    description_l = str(description).lower().strip()
    score = 0.0
    if description_l and description_l in text:
        score += 100
    for term in terms:
        if term in text:
            score += 45
        else:
            score += 25 * SequenceMatcher(None, term, text).ratio()
    try:
        score += min(20.0, max(0.0, float(candidate.get("ocr_conf", candidate.get("confidence", 0)))) / 5)
    except (TypeError, ValueError):
        pass

    if image_size and hints:
        width, height = image_size
        cx = candidate["x"] + candidate["w"] / 2
        cy = candidate["y"] + candidate["h"] / 2
        if "top" in hints:
            score += max(0.0, 20.0 * (1.0 - cy / max(1, height)))
        if "bottom" in hints:
            score += max(0.0, 20.0 * (cy / max(1, height)))
        if "left" in hints:
            score += max(0.0, 20.0 * (1.0 - cx / max(1, width)))
        if "right" in hints:
            score += max(0.0, 20.0 * (cx / max(1, width)))
        if "center" in hints or "centre" in hints or "middle" in hints:
            center_distance = abs(cx - width / 2) / max(1, width / 2) + abs(cy - height / 2) / max(1, height / 2)
            score += max(0.0, 25.0 * (1.0 - center_distance / 2))
    return score


def _dedupe(matches):
    seen = set()
    unique = []
    for match in matches:
        key = (match["text"].lower(), match["x"] // 4, match["y"] // 4, match["w"] // 4, match["h"] // 4)
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return unique


def _find_matches(description, screenshot=None):
    terms, hints = _terms_and_hints(description)
    matches = []
    image = None
    image_error = None

    if screenshot:
        try:
            image = _decode_screenshot(screenshot)
        except Exception as exc:
            return [], f"invalid screenshot: {exc}"

    if not screenshot:
        queries = [str(description)] + [term for term in terms if term.lower() != str(description).lower()]
        for query in queries[:6]:
            response = _coagent_post("/ocr/find", {"text": query})
            for raw_match in response.get("matches", []) if isinstance(response, dict) else []:
                candidate = _candidate_from_ocr_match(raw_match)
                if candidate:
                    matches.append(candidate)

    if not matches or screenshot:
        try:
            image = image or _fresh_screenshot()
            candidates, image_error = _ocr_candidates_from_image(image)
            image_size = image.size
            scored = []
            for candidate in candidates:
                score = _score_candidate(candidate, description, terms, hints, image_size)
                if score >= 20 or any(term in candidate["text"].lower() for term in terms):
                    item = dict(candidate)
                    item["confidence"] = round(min(100.0, score), 2)
                    scored.append(item)
            matches.extend(scored)
        except Exception as exc:
            image_error = str(exc)

    image_size = image.size if image is not None else None
    normalized = []
    for match in matches:
        item = dict(match)
        item["confidence"] = round(min(100.0, _score_candidate(item, description, terms, hints, image_size)), 2)
        normalized.append(item)
    normalized = _dedupe(normalized)
    normalized.sort(key=lambda item: item.get("confidence", 0), reverse=True)
    if not normalized and image_error:
        return [], image_error
    return normalized[:20], None


def register_routes(app, state, require_auth):
    bp = Blueprint("finder", __name__)

    @bp.route("/finder/find", methods=["POST"])
    @require_auth
    def route_finder_find():
        data = _json_body()
        description = data.get("description", "")
        if not description:
            return jsonify({"error": "Missing required field: description"}), 400
        matches, error = _find_matches(description, data.get("screenshot"))
        payload = {"matches": matches, "count": len(matches)}
        if error:
            payload["warning"] = error
        return jsonify(payload)

    @bp.route("/finder/click", methods=["POST"])
    @require_auth
    def route_finder_click():
        data = _json_body()
        description = data.get("description", "")
        if not description:
            return jsonify({"error": "Missing required field: description"}), 400
        matches, error = _find_matches(description, data.get("screenshot"))
        if not matches:
            return jsonify({"found": False, "error": error or "no matching element found", "matches": []}), 404
        match = matches[0]
        offset = data.get("click_offset") if isinstance(data.get("click_offset"), dict) else {}
        x = int(match["x"] + match["w"] / 2 + int(offset.get("x", 0)))
        y = int(match["y"] + match["h"] / 2 + int(offset.get("y", 0)))
        click_result = _coagent_post("/mouse/click", {
            "x": x,
            "y": y,
            "button": data.get("button", "left"),
            "background": data.get("background", True),
            "retry": False,
        })
        if isinstance(click_result, dict) and click_result.get("error"):
            _console(f"[finder] click failed: {click_result.get('error')}")
            return jsonify({"found": True, "error": "click failed", "details": click_result, "match": match}), 502
        return jsonify({"found": True, "at": {"x": x, "y": y}, "text": match["text"], "action": "clicked"})

    @bp.route("/finder/type", methods=["POST"])
    @require_auth
    def route_finder_type():
        data = _json_body()
        description = data.get("description", "")
        if not description:
            return jsonify({"error": "Missing required field: description"}), 400
        text = data.get("text")
        if text is None:
            return jsonify({"error": "Missing required field: text"}), 400
        if len(str(text)) > 4096:
            return jsonify({"error": "text exceeds maximum length (4096 chars)"}), 400
        matches, error = _find_matches(description, data.get("screenshot"))
        if not matches:
            return jsonify({"found": False, "error": error or "no matching text field found", "matches": []}), 404
        match = matches[0]
        x = int(match["x"] + match["w"] / 2)
        y = int(match["y"] + match["h"] / 2)
        click_result = _coagent_post("/mouse/click", {"x": x, "y": y, "background": True, "retry": False})
        if isinstance(click_result, dict) and click_result.get("error"):
            return jsonify({"found": True, "error": "click failed", "details": click_result, "match": match}), 502
        if data.get("clear_first", True):
            _coagent_post("/key/press", {"keys": ["ctrl", "a"]})
            _coagent_post("/key/press", {"keys": ["backspace"]})
        type_result = _coagent_post("/key/type", {"text": str(text)})
        if isinstance(type_result, dict) and type_result.get("error"):
            return jsonify({"found": True, "error": "type failed", "details": type_result, "match": match}), 502
        return jsonify({"found": True, "at": {"x": x, "y": y}, "text_field": match["text"], "action": "typed"})

    app.register_blueprint(bp)

"""VLM (vision-language model) screen understanding.

Semantic UI analysis beyond OCR. Captures the current screen (or a
sub-region / window) and sends the image to a vision-capable LLM
(default: OpenAI gpt-4o-mini) so the caller can:

  POST /vlm/describe - free-form description of what's on screen
  POST /vlm/find     - locate a UI element by natural-language description,
                       return pixel coords {x, y, w, h, cx, cy}
  POST /vlm/qa       - answer a free-form question about the screen

Reuses the existing vision provider settings used elsewhere in CoAgent:
the OPENAI_API_KEY environment variable, an optional OPENAI_BASE_URL
override, and the OPENAI_VISION_MODEL env var (default gpt-4o-mini).

Windows-only / third-party imports are wrapped in try/except so the file
imports cleanly under a Linux syntax check.
"""

import base64
import io
import json
import logging
import os
import re
import threading
import time

from flask import jsonify

from shared import _json_body


_LOGGER = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STATE = {
    "total_describe": 0,
    "total_find": 0,
    "total_qa": 0,
    "last_model": None,
    "last_ts": 0,
    "last_error": None,
}

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


# ---------------------------------------------------------------------------
# Screenshot capture (reuses routes_vision._grab_region)
# ---------------------------------------------------------------------------

def _capture(region=None, window=None):
    """Return (PIL.Image, (off_x, off_y), err)."""
    try:
        from routes_vision import _grab_region
    except Exception as exc:
        return None, (0, 0), f"routes_vision unavailable: {exc}"
    try:
        img, offset = _grab_region(region=region, window=window)
        if img is None:
            return None, (0, 0), "screen capture failed"
        return img, offset, None
    except Exception as exc:
        return None, (0, 0), f"capture error: {type(exc).__name__}: {exc}"


def _pil_to_png_b64(pil_img, max_side=1600):
    """Encode a PIL image to base64 PNG. Downscales huge screens for token cost."""
    img = pil_img
    try:
        w, h = img.size
        longest = max(w, h)
        if max_side and longest > max_side:
            scale = max_side / float(longest)
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            try:
                resample = img.Resampling.LANCZOS  # PIL >= 9.1
            except AttributeError:
                resample = 1  # LANCZOS integer fallback
            img = img.resize(new_size, resample)
    except Exception:
        pass
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii"), img.size


# ---------------------------------------------------------------------------
# Vision provider config (reuses OpenAI env vars)
# ---------------------------------------------------------------------------

def _provider_config(body):
    """Resolve provider settings from request body + environment."""
    body = body or {}
    model = (body.get("model") or "").strip() \
        or os.environ.get("OPENAI_VISION_MODEL") \
        or os.environ.get("VISION_MODEL") \
        or _DEFAULT_MODEL
    api_key = (body.get("api_key") or "").strip() or os.environ.get("OPENAI_API_KEY", "")
    base_url = (body.get("base_url") or "").strip() \
        or os.environ.get("OPENAI_BASE_URL") \
        or _DEFAULT_BASE_URL
    base_url = base_url.rstrip("/")
    timeout = int(body.get("timeout") or 45)
    return {"model": model, "api_key": api_key, "base_url": base_url, "timeout": timeout}


def _call_vision(cfg, system_prompt, user_prompt, image_b64, detail="auto"):
    """POST a chat.completions request with an inline image. Returns model text."""
    if not cfg.get("api_key"):
        raise RuntimeError("OPENAI_API_KEY is not set (or api_key not provided)")

    from routes_agent import _post_json, _content_from_openai_payload

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                    "detail": detail,
                },
            },
        ],
    })
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 900,
    }
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = _post_json(f"{cfg['base_url']}/chat/completions", headers, payload, cfg["timeout"])
    return _content_from_openai_payload(data)


# ---------------------------------------------------------------------------
# JSON extraction (models sometimes wrap JSON in markdown fences)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json(text):
    if not text:
        return None
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except Exception:
        pass
    m = _FENCE_RE.search(stripped)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    # Grab the first {...} block
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start:end + 1])
        except Exception:
            return None
    return None


def _coerce_bbox_to_pixels(parsed, img_w, img_h):
    """Accept normalized [0,1], 0-1000 grid, or pixel coords. Return dict or None."""
    if not isinstance(parsed, dict):
        return None
    keys = {k.lower(): parsed[k] for k in parsed if isinstance(k, str)}
    try:
        x = float(keys.get("x", keys.get("left", 0)))
        y = float(keys.get("y", keys.get("top", 0)))
        w = float(keys.get("w", keys.get("width", 0)))
        h = float(keys.get("h", keys.get("height", 0)))
    except (TypeError, ValueError):
        return None

    # If bbox provided as {x1,y1,x2,y2}
    if not w and not h and ("x2" in keys or "right" in keys) and ("y2" in keys or "bottom" in keys):
        try:
            x2 = float(keys.get("x2", keys.get("right")))
            y2 = float(keys.get("y2", keys.get("bottom")))
            w = max(0.0, x2 - x)
            h = max(0.0, y2 - y)
        except (TypeError, ValueError):
            pass

    if img_w <= 0 or img_h <= 0:
        return None

    max_dim = max(x + w, y + h, x, y)
    if max_dim <= 1.5:
        scale_x, scale_y = img_w, img_h
    elif max_dim <= 1000.5:
        scale_x = img_w / 1000.0
        scale_y = img_h / 1000.0
    else:
        scale_x = scale_y = 1.0

    px = int(round(x * scale_x))
    py = int(round(y * scale_y))
    pw = int(round(w * scale_x))
    ph = int(round(h * scale_y))
    # Clamp to image bounds
    px = max(0, min(img_w - 1, px))
    py = max(0, min(img_h - 1, py))
    pw = max(1, min(img_w - px, pw or 1))
    ph = max(1, min(img_h - py, ph or 1))
    return {"x": px, "y": py, "w": pw, "h": ph}


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/vlm/describe", methods=["POST"])
    @require_auth
    def route_vlm_describe():
        """Free-form semantic description of the current screen.

        Body:
          region  ({x,y,w,h}, optional)
          window  (str, optional)   - window title substring
          prompt  (str, optional)   - override the default description prompt
          detail  "low"|"high"|"auto" (default "auto")
          model, api_key, base_url, timeout - override provider settings
        """
        body = _json_body() or {}
        region = body.get("region") if isinstance(body.get("region"), dict) else None
        window = (body.get("window") or "").strip() or None
        detail = (body.get("detail") or "auto").strip().lower()
        if detail not in ("low", "high", "auto"):
            detail = "auto"

        img, offset, err = _capture(region=region, window=window)
        if img is None:
            return jsonify({"ok": False, "error": err or "capture failed"}), 500

        t0 = time.time()
        try:
            b64, sent_size = _pil_to_png_b64(img)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"encode failed: {exc}"}), 500

        cfg = _provider_config(body)
        prompt = body.get("prompt") or (
            "Describe what is currently on this screen. Identify the active "
            "application, key UI regions (menus, panels, dialogs), any prominent "
            "text or buttons, and the likely user task. Be concise (5-10 sentences)."
        )
        try:
            text = _call_vision(cfg, None, prompt, b64, detail=detail)
        except Exception as exc:
            with _LOCK:
                _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
                _STATE["last_ts"] = int(time.time())
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 502

        with _LOCK:
            _STATE["total_describe"] += 1
            _STATE["last_model"] = cfg["model"]
            _STATE["last_ts"] = int(time.time())
            _STATE["last_error"] = None

        return jsonify({
            "ok": True,
            "description": text,
            "model": cfg["model"],
            "screen_size": {"w": img.size[0], "h": img.size[1]},
            "sent_size": {"w": sent_size[0], "h": sent_size[1]},
            "offset": {"x": offset[0], "y": offset[1]},
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        })

    @app.route("/vlm/find", methods=["POST"])
    @require_auth
    def route_vlm_find():
        """Locate a UI element by natural-language description.

        Body:
          query   (str, required)   - description of the element to find
          region  ({x,y,w,h}, optional)
          window  (str, optional)
          detail  "low"|"high"|"auto" (default "high" - coords need pixels)
          model, api_key, base_url, timeout - override provider settings

        Returns pixel coordinates in absolute screen space (accounts for region
        offset and any downscaling used when sending the image).
        """
        body = _json_body() or {}
        query = (body.get("query") or "").strip()
        if not query:
            return jsonify({"ok": False, "error": "missing 'query'"}), 400

        region = body.get("region") if isinstance(body.get("region"), dict) else None
        window = (body.get("window") or "").strip() or None
        detail = (body.get("detail") or "high").strip().lower()
        if detail not in ("low", "high", "auto"):
            detail = "high"

        img, offset, err = _capture(region=region, window=window)
        if img is None:
            return jsonify({"ok": False, "error": err or "capture failed"}), 500

        t0 = time.time()
        try:
            b64, sent_size = _pil_to_png_b64(img)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"encode failed: {exc}"}), 500
        sent_w, sent_h = sent_size
        full_w, full_h = img.size

        cfg = _provider_config(body)
        system_prompt = (
            "You are a UI-element locator. Given a screenshot and a natural-"
            "language description of a UI element, return ONLY strict JSON with "
            "the element's bounding box as normalized fractions of the image "
            "(each in the range 0.0-1.0): "
            '{"found": true, "x": <left>, "y": <top>, "w": <width>, '
            '"h": <height>, "label": "<what you saw>", "confidence": '
            "<0.0-1.0>}. If the element is not visible return "
            '{"found": false, "reason": "<why>"}. No extra text.'
        )
        user_prompt = f"Find this element on the screen: {query}"
        try:
            raw = _call_vision(cfg, system_prompt, user_prompt, b64, detail=detail)
        except Exception as exc:
            with _LOCK:
                _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
                _STATE["last_ts"] = int(time.time())
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 502

        parsed = _extract_json(raw) or {}
        found = bool(parsed.get("found", True)) and any(k in parsed for k in ("x", "left", "x1"))

        with _LOCK:
            _STATE["total_find"] += 1
            _STATE["last_model"] = cfg["model"]
            _STATE["last_ts"] = int(time.time())
            _STATE["last_error"] = None

        if not found:
            return jsonify({
                "ok": False,
                "found": False,
                "query": query,
                "model": cfg["model"],
                "raw": raw,
                "reason": parsed.get("reason") if isinstance(parsed, dict) else None,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            })

        bbox_sent = _coerce_bbox_to_pixels(parsed, sent_w, sent_h)
        if not bbox_sent:
            return jsonify({
                "ok": False,
                "found": False,
                "query": query,
                "model": cfg["model"],
                "error": "could not parse bounding box",
                "raw": raw,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            })

        # Map from downscaled sent-image coords back to original image, then
        # add the capture region offset for absolute screen coords.
        scale_x = full_w / float(sent_w) if sent_w else 1.0
        scale_y = full_h / float(sent_h) if sent_h else 1.0
        local_x = int(round(bbox_sent["x"] * scale_x))
        local_y = int(round(bbox_sent["y"] * scale_y))
        local_w = max(1, int(round(bbox_sent["w"] * scale_x)))
        local_h = max(1, int(round(bbox_sent["h"] * scale_y)))
        abs_x = local_x + int(offset[0])
        abs_y = local_y + int(offset[1])
        cx = abs_x + local_w // 2
        cy = abs_y + local_h // 2

        return jsonify({
            "ok": True,
            "found": True,
            "query": query,
            "model": cfg["model"],
            "x": abs_x,
            "y": abs_y,
            "w": local_w,
            "h": local_h,
            "cx": cx,
            "cy": cy,
            "label": parsed.get("label"),
            "confidence": parsed.get("confidence"),
            "screen_size": {"w": full_w, "h": full_h},
            "offset": {"x": int(offset[0]), "y": int(offset[1])},
            "raw": raw,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        })

    @app.route("/vlm/qa", methods=["POST"])
    @require_auth
    def route_vlm_qa():
        """Answer a free-form question about what's on screen.

        Body:
          question (str, required)
          region   ({x,y,w,h}, optional)
          window   (str, optional)
          detail   "low"|"high"|"auto" (default "auto")
          model, api_key, base_url, timeout - override provider settings
        """
        body = _json_body() or {}
        question = (body.get("question") or body.get("query") or "").strip()
        if not question:
            return jsonify({"ok": False, "error": "missing 'question'"}), 400

        region = body.get("region") if isinstance(body.get("region"), dict) else None
        window = (body.get("window") or "").strip() or None
        detail = (body.get("detail") or "auto").strip().lower()
        if detail not in ("low", "high", "auto"):
            detail = "auto"

        img, offset, err = _capture(region=region, window=window)
        if img is None:
            return jsonify({"ok": False, "error": err or "capture failed"}), 500

        t0 = time.time()
        try:
            b64, _sent = _pil_to_png_b64(img)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"encode failed: {exc}"}), 500

        cfg = _provider_config(body)
        system_prompt = (
            "You are a screen-reading assistant. Answer the user's question "
            "about the screenshot succinctly and factually. If the answer is "
            "not visible, say so."
        )
        try:
            answer = _call_vision(cfg, system_prompt, question, b64, detail=detail)
        except Exception as exc:
            with _LOCK:
                _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
                _STATE["last_ts"] = int(time.time())
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 502

        with _LOCK:
            _STATE["total_qa"] += 1
            _STATE["last_model"] = cfg["model"]
            _STATE["last_ts"] = int(time.time())
            _STATE["last_error"] = None

        return jsonify({
            "ok": True,
            "question": question,
            "answer": answer,
            "model": cfg["model"],
            "offset": {"x": int(offset[0]), "y": int(offset[1])},
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        })

    @app.route("/vlm/status", methods=["GET"])
    @require_auth
    def route_vlm_status():
        with _LOCK:
            snapshot = dict(_STATE)
        snapshot["has_api_key"] = bool(os.environ.get("OPENAI_API_KEY"))
        snapshot["default_model"] = (
            os.environ.get("OPENAI_VISION_MODEL")
            or os.environ.get("VISION_MODEL")
            or _DEFAULT_MODEL
        )
        return jsonify({"ok": True, "state": snapshot})

    _LOGGER.info("VLM screen understanding routes registered")

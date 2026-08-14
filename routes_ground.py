"""GUI action-grounding — click by natural-language description.

Fourth tier of the resolution chain: UIA → OCR → SOM → grounding-model.

Where the earlier tiers work from the accessibility tree, text detection, or
edge-based blob detection, a grounding model works from raw pixels alone. It
is the only reliable option for CEF / Electron / canvas / game / remote-desktop
apps (NVIDIA App, Discord, VS Code, Spotify, Steam, remote viewers) which
expose an empty or useless UIA tree and defeat OCR/SOM heuristics.

Providers
---------
The concrete model is pluggable via env / config:

  GROUNDING_PROVIDER=aria       — Aria-UI hosted API (default). Requires
                                  ARIA_API_KEY. Uses stdlib urllib only.
  GROUNDING_PROVIDER=omniparser — Local Omniparser HTTP endpoint. Requires
                                  GROUNDING_ENDPOINT. Stub — returns a clear
                                  "provider not configured" error unless the
                                  endpoint is reachable.
  GROUNDING_PROVIDER=qwen       — Local Qwen2.5-VL HTTP endpoint. Same shape
                                  as omniparser.

Endpoints
---------
  POST /ground/find    body: {prompt, image | screenshot_source, region?, window?}
                       → {ok, count, elements:[{label, bbox:{x,y,w,h}, confidence}]}

  POST /ground/click   body: same as /ground/find (+ optional 'button')
                       → {ok, clicked, click_point:{x,y}, element, ...}

  GET  /ground/status  → {ok, provider, configured, endpoint?, ...}

All bounding boxes and click points are returned in absolute screen
coordinates so /ground/click can feed the mouse primitive directly.
"""

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log


# ---------------------------------------------------------------------------
# Optional PIL for on-server screenshot capture
# ---------------------------------------------------------------------------

_HAS_PIL = False
try:
    from PIL import Image  # noqa: F401
    _HAS_PIL = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CONFIG_PATH = COAGENT_DIR / "grounding_config.json"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_ARIA_ENDPOINT = "https://api.rhymes.ai/v1/aria-ui/ground"


def _load_config():
    """Merge grounding_config.json (if present) with env vars. Env wins."""
    cfg = {}
    if _CONFIG_PATH.exists():
        try:
            loaded = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except (OSError, ValueError) as exc:
            _log(f"[ground] failed to read {_CONFIG_PATH}: {exc}")

    provider = os.environ.get("GROUNDING_PROVIDER") or cfg.get("provider") or "aria"
    endpoint = os.environ.get("GROUNDING_ENDPOINT") or cfg.get("endpoint") or ""
    api_key = os.environ.get("ARIA_API_KEY") or cfg.get("aria_api_key") or ""
    try:
        timeout = float(os.environ.get("GROUNDING_TIMEOUT",
                                       cfg.get("timeout", _DEFAULT_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT

    return {
        "provider": provider.strip().lower(),
        "endpoint": endpoint.strip(),
        "api_key": api_key.strip(),
        "timeout": timeout,
    }


# ---------------------------------------------------------------------------
# Image / screenshot resolution
# ---------------------------------------------------------------------------

def _grab_screenshot(region=None, window=None):
    """Capture the screen (or a sub-region) into a PIL image + (off_x, off_y).

    Delegates to routes_vision._grab_region so we stay consistent with the
    rest of the resolution chain. Returns (None, (0, 0)) if capture fails.
    """
    try:
        from routes_vision import _grab_region  # local import: optional dep
    except ImportError:
        return None, (0, 0)
    return _grab_region(region=region, window=window)


def _resolve_image(body):
    """Return (png_bytes, image_size, offset).

    - If body['image'] is a base64 PNG/JPEG, decode it and offset=(0,0).
    - Else capture via body['region'] / body['window'] and use that as offset.

    Raises ValueError on failure. image_size is (w, h) or None if unknown.
    """
    b64 = (body.get("image") or "").strip()
    if b64:
        try:
            raw = base64.b64decode(b64)
        except Exception as exc:
            raise ValueError(f"Invalid base64 image: {exc}") from exc
        size = None
        if _HAS_PIL:
            try:
                with Image.open(io.BytesIO(raw)) as img:
                    size = img.size
            except Exception:
                size = None
        return raw, size, (0, 0)

    if not _HAS_PIL:
        raise ValueError("PIL/Pillow not available — provide 'image' as base64 "
                         "instead of relying on server-side capture")

    region = body.get("region")
    window = (body.get("window") or "").strip() or None
    img, offset = _grab_screenshot(region=region, window=window)
    if img is None:
        raise ValueError("Screen capture failed and no 'image' provided")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img.size, offset


# ---------------------------------------------------------------------------
# Bounding-box normalisation
# ---------------------------------------------------------------------------

def _normalize_bbox(raw, image_size):
    """Coerce a bbox in any common shape/scale to {x, y, w, h} pixel dict.

    Accepted inputs:
      - {"x":..,"y":..,"w":..,"h":..}
      - {"x":..,"y":..,"width":..,"height":..}
      - {"left":..,"top":..,"right":..,"bottom":..}
      - [x, y, w, h]  or  [x1, y1, x2, y2]
    Values in [0,1] are treated as normalised and scaled by image_size.
    """
    if raw is None:
        return None

    x = y = w = h = None
    if isinstance(raw, dict):
        if "w" in raw and "h" in raw:
            x, y, w, h = raw.get("x", 0), raw.get("y", 0), raw["w"], raw["h"]
        elif "width" in raw and "height" in raw:
            x, y = raw.get("x", raw.get("left", 0)), raw.get("y", raw.get("top", 0))
            w, h = raw["width"], raw["height"]
        elif "right" in raw and "bottom" in raw:
            try:
                left = float(raw.get("left", 0))
                top = float(raw.get("top", 0))
                right = float(raw["right"])
                bottom = float(raw["bottom"])
            except (TypeError, ValueError):
                return None
            x, y, w, h = left, top, right - left, bottom - top
    elif isinstance(raw, (list, tuple)) and len(raw) >= 4:
        a, b, c, d = raw[0], raw[1], raw[2], raw[3]
        # heuristic: if c > a and d > b and both look like coords, it may be x2/y2
        if c > a and d > b and (a + c) > c and image_size:
            # Ambiguous — pick x2y2 if c/d are within image bounds and > a/b
            iw, ih = image_size
            if c <= iw + 1 and d <= ih + 1 and (c - a) < iw and (d - b) < ih:
                x, y, w, h = a, b, c - a, d - b
            else:
                x, y, w, h = a, b, c, d
        else:
            x, y, w, h = a, b, c, d
    else:
        return None

    try:
        x, y, w, h = float(x), float(y), float(w), float(h)
    except (TypeError, ValueError):
        return None

    # Normalised → pixels
    if image_size and max(abs(x), abs(y), abs(w), abs(h)) <= 1.5:
        iw, ih = image_size
        x, w = x * iw, w * iw
        y, h = y * ih, h * ih

    return {"x": int(round(x)), "y": int(round(y)),
            "w": int(round(w)), "h": int(round(h))}


def _bbox_to_screen(bbox, offset):
    ox, oy = offset
    return {"x": bbox["x"] + ox, "y": bbox["y"] + oy,
            "w": bbox["w"], "h": bbox["h"]}


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

class ProviderError(RuntimeError):
    """Raised when a grounding provider cannot service the request."""


def _provider_aria(prompt, png_bytes, image_size, cfg):
    """Call the Aria-UI grounding endpoint.

    Aria-UI's public shape may evolve; we adapt to the two common response
    conventions ({elements:[{bbox, label, score}]} or {result:[...]}).
    Requires ARIA_API_KEY. Raises ProviderError on failure.
    """
    if not cfg["api_key"]:
        raise ProviderError("ARIA_API_KEY is not configured. Set the env var "
                            "or add 'aria_api_key' to grounding_config.json")

    endpoint = cfg["endpoint"] or _DEFAULT_ARIA_ENDPOINT
    payload = {
        "prompt": prompt,
        "image": base64.b64encode(png_bytes).decode("ascii"),
        "return_bbox": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
            "User-Agent": "HermesCoAgent-Grounding/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"Aria-UI HTTP {exc.code}: "
                            f"{exc.read()[:400].decode('utf-8', 'replace')}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"Aria-UI request failed: {exc.reason}") from exc
    except OSError as exc:
        raise ProviderError(f"Aria-UI I/O error: {exc}") from exc

    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderError(f"Aria-UI returned non-JSON: {exc}") from exc

    if isinstance(parsed, list):
        items = parsed
    else:
        items = (parsed.get("elements")
                 or parsed.get("result")
                 or parsed.get("boxes")
                 or [])
    if isinstance(items, dict):
        items = [items]

    out = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        bbox = _normalize_bbox(entry.get("bbox") or entry.get("box")
                               or entry.get("rect"), image_size)
        if bbox is None:
            continue
        label = (entry.get("label") or entry.get("text")
                 or entry.get("description") or prompt)
        confidence = entry.get("confidence", entry.get("score", 0.0))
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        out.append({"label": str(label), "bbox": bbox, "confidence": confidence})
    return out


def _provider_local_http(prompt, png_bytes, image_size, cfg, provider_name):
    """Shared implementation for local providers (Omniparser / Qwen2.5-VL).

    Both are expected to expose an HTTP endpoint accepting
    {prompt, image_b64} and returning a list of {bbox, label, confidence}.
    If the endpoint is not configured, raises ProviderError clearly.
    """
    if not cfg["endpoint"]:
        raise ProviderError(
            f"{provider_name} provider selected but GROUNDING_ENDPOINT is "
            f"not configured. Point it at your local model server, or set "
            f"GROUNDING_PROVIDER=aria to use the hosted default.")

    payload = {
        "prompt": prompt,
        "image_b64": base64.b64encode(png_bytes).decode("ascii"),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        cfg["endpoint"],
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"{provider_name} HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"{provider_name} unreachable: {exc.reason}") from exc
    except OSError as exc:
        raise ProviderError(f"{provider_name} I/O error: {exc}") from exc

    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderError(f"{provider_name} returned non-JSON: {exc}") from exc

    items = parsed if isinstance(parsed, list) else (
        parsed.get("elements") or parsed.get("result") or [])
    out = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        bbox = _normalize_bbox(entry.get("bbox") or entry.get("box"), image_size)
        if bbox is None:
            continue
        label = entry.get("label") or entry.get("text") or prompt
        try:
            confidence = float(entry.get("confidence", entry.get("score", 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append({"label": str(label), "bbox": bbox, "confidence": confidence})
    return out


def _dispatch(prompt, png_bytes, image_size, cfg):
    provider = cfg["provider"]
    if provider == "aria":
        return _provider_aria(prompt, png_bytes, image_size, cfg)
    if provider == "omniparser":
        return _provider_local_http(prompt, png_bytes, image_size, cfg, "Omniparser")
    if provider == "qwen":
        return _provider_local_http(prompt, png_bytes, image_size, cfg, "Qwen2.5-VL")
    raise ProviderError(f"Unknown grounding provider: {provider!r}. "
                        f"Supported: aria, omniparser, qwen")


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/ground/status", methods=["GET"])
    @require_auth
    def ground_status():
        """Report the active grounding provider and whether it is usable."""
        cfg = _load_config()
        provider = cfg["provider"]
        configured = False
        detail = ""
        if provider == "aria":
            configured = bool(cfg["api_key"])
            detail = ("ARIA_API_KEY set" if configured
                      else "ARIA_API_KEY missing — set env or grounding_config.json")
        elif provider in ("omniparser", "qwen"):
            configured = bool(cfg["endpoint"])
            detail = ("endpoint set" if configured
                      else "GROUNDING_ENDPOINT missing — point at local model server")
        else:
            detail = f"unknown provider {provider!r}"
        return jsonify({
            "ok": True,
            "provider": provider,
            "configured": configured,
            "endpoint": cfg["endpoint"] or None,
            "timeout": cfg["timeout"],
            "detail": detail,
            "supported": ["aria", "omniparser", "qwen"],
        })

    @app.route("/ground/find", methods=["POST"])
    @require_auth
    def ground_find():
        """Ground a natural-language prompt against a screenshot.

        Body:
          prompt              — natural-language description of the target
          image               — base64 PNG/JPEG (optional; else screen is grabbed)
          screenshot_source   — alias for 'image' (base64 data)
          region / window     — capture hints when 'image' is omitted

        Returns list of {label, bbox:{x,y,w,h}, confidence} in absolute screen
        coordinates (if the source was a screen capture) or image-relative
        coordinates (if the caller supplied 'image').
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "Missing required field: prompt"}), 400

        # Accept alternate key name
        if "image" not in body and "screenshot_source" in body:
            body["image"] = body["screenshot_source"]

        cfg = _load_config()
        t0 = time.time()

        try:
            png_bytes, image_size, offset = _resolve_image(body)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        try:
            elements = _dispatch(prompt, png_bytes, image_size, cfg)
        except ProviderError as exc:
            return jsonify({
                "ok": False,
                "provider": cfg["provider"],
                "error": str(exc),
                "code": "PROVIDER_UNAVAILABLE",
            }), 503

        screened = [
            {"label": el["label"],
             "bbox": _bbox_to_screen(el["bbox"], offset),
             "confidence": el["confidence"]}
            for el in elements
        ]

        return jsonify({
            "ok": True,
            "provider": cfg["provider"],
            "prompt": prompt,
            "count": len(screened),
            "elements": screened,
            "image_size": list(image_size) if image_size else None,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        })

    @app.route("/ground/click", methods=["POST"])
    @require_auth
    def ground_click():
        """Ground a prompt then click the highest-confidence element.

        Body: same as /ground/find, plus optional:
          button   — "left" (default), "right", "middle"
          index    — pick the Nth-ranked element (default 0)

        Returns {ok, clicked, click_point:{x,y}, element, ...}.
        Feeds the click through routes_mouse's mouse primitive so behavior
        matches other click endpoints (focus, retries, hooks).
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "Missing required field: prompt"}), 400

        if "image" not in body and "screenshot_source" in body:
            body["image"] = body["screenshot_source"]

        button = (body.get("button") or "left").strip().lower()
        try:
            pick = int(body.get("index", 0))
        except (TypeError, ValueError):
            pick = 0

        cfg = _load_config()
        t0 = time.time()

        try:
            png_bytes, image_size, offset = _resolve_image(body)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        try:
            elements = _dispatch(prompt, png_bytes, image_size, cfg)
        except ProviderError as exc:
            return jsonify({
                "ok": False,
                "provider": cfg["provider"],
                "error": str(exc),
                "code": "PROVIDER_UNAVAILABLE",
            }), 503

        if not elements:
            return jsonify({
                "ok": False,
                "clicked": False,
                "provider": cfg["provider"],
                "error": f"No element matched prompt: {prompt!r}",
                "code": "NOT_FOUND",
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }), 404

        elements.sort(key=lambda e: -e.get("confidence", 0.0))
        pick = max(0, min(pick, len(elements) - 1))
        best = elements[pick]
        screen_bbox = _bbox_to_screen(best["bbox"], offset)
        click_x = screen_bbox["x"] + screen_bbox["w"] // 2
        click_y = screen_bbox["y"] + screen_bbox["h"] // 2

        click_result = None
        click_ok = False
        try:
            from routes_mouse import _mouse_action  # local import: primitive
            click_response = _mouse_action("click", click_x, click_y, button,
                                           True, state)
            try:
                click_result = click_response.get_json(silent=True)
            except AttributeError:
                click_result = None
            click_ok = bool(click_result and click_result.get("status") == "ok")
        except ImportError:
            # Fall back to direct pyautogui / Win32 so /ground/click still works
            try:
                import pyautogui
                pyautogui.click(click_x, click_y, button=button)
                click_ok = True
                click_result = {"status": "ok", "fallback": "pyautogui"}
            except Exception as exc:
                click_result = {"status": "error", "error": str(exc)}

        return jsonify({
            "ok": click_ok,
            "clicked": click_ok,
            "provider": cfg["provider"],
            "prompt": prompt,
            "element": {"label": best["label"], "bbox": screen_bbox,
                        "confidence": best["confidence"]},
            "click_point": {"x": click_x, "y": click_y},
            "button": button,
            "candidates": len(elements),
            "click_result": click_result,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        })

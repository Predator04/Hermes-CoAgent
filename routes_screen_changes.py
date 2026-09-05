"""Incremental screen perception — changed-region deltas for the vision hot path.

Endpoints:
  POST /screen/changes       - baseline the current frame and start tracking
  GET  /screen/changes       - regions changed since the last call (empty when idle)
  GET  /screen/changes/full  - force a full frame (JPEG base64), reset baseline

Designed for computer-use agent loops: instead of re-shipping a full
screenshot to a VLM every step, only the pixels that changed are returned
(bounding boxes + optional cropped JPEG patches), cutting vision token/payload
cost by an order of magnitude when the screen is mostly idle.

Reuses the proven capture chain (routes_ocr._screen_img) and the changed-region
extraction already exercised by routes_diff (_find_regions).

Windows-only + third-party imports are wrapped in try/except so this file
imports cleanly under a Linux syntax check.
"""

import base64
import io
import threading
import time

from flask import jsonify, request

from shared import _json_body, _log

try:
    from PIL import Image, ImageChops
except ImportError:  # pragma: no cover - runtime only, PIL present on Windows
    Image = ImageChops = None


# --- module state ------------------------------------------------------------

_LOCK = threading.RLock()
_BASELINE = None       # PIL RGB image
_BASELINE_ID = None    # informational timestamp id
_LAST_FRAME = None     # previous frame for the delta call

_DEFAULT_THRESHOLD = 8   # ignore sub-threshold pixel noise (cursor blink, etc.)
_MAX_PATCHES = 20        # cap base64 patches per response
_MAX_PATCH_DIM = 800     # cap per-patch width/height (keep payload lean)


def _capture():
    """Grab the current frame through the canonical chain; fall back to mss."""
    try:
        from routes_ocr import _screen_img
        img = _screen_img(force=True)
        if img is not None:
            return img.convert("RGB")
    except Exception as exc:
        _log(f"[screen-changes] routes_ocr capture failed: {exc}")
    try:
        from routes_diff import _capture_image
        return _capture_image().convert("RGB")
    except Exception as exc:
        _log(f"[screen-changes] fallback capture failed: {exc}")
        return None


def _same_size(base, current):
    if base.size == current.size:
        return base, current
    w = max(base.size[0], current.size[0])
    h = max(base.size[1], current.size[1])
    base_canvas = Image.new("RGB", (w, h), "black")
    cur_canvas = Image.new("RGB", (w, h), "black")
    base_canvas.paste(base, (0, 0))
    cur_canvas.paste(current, (0, 0))
    return base_canvas, cur_canvas


def _diff_regions(base, current, threshold):
    base, current = _same_size(base, current)
    diff = ImageChops.difference(base, current)
    mask = diff.convert("L").point(lambda px: 255 if px >= threshold else 0)
    total = mask.size[0] * mask.size[1]
    hist = mask.histogram()
    changed_pixels = total - hist[0]
    percent = round((changed_pixels / total) * 100, 4) if total else 0
    try:
        from routes_diff import _find_regions
        regions = _find_regions(mask)
    except Exception as exc:
        _log(f"[screen-changes] region extraction failed: {exc}")
        regions = []
    return regions, changed_pixels, percent


def _patch_b64(img, region):
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    right = min(img.width, x + w)
    bottom = min(img.height, y + h)
    if right <= x or bottom <= y:
        return None
    crop = img.crop((x, y, right, bottom))
    if crop.width > _MAX_PATCH_DIM or crop.height > _MAX_PATCH_DIM:
        scale = _MAX_PATCH_DIM / max(crop.width, crop.height)
        crop = crop.resize((max(1, int(crop.width * scale)),
                            max(1, int(crop.height * scale))))
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def register_routes(app, state, require_auth):

    @app.route("/screen/changes", methods=["POST"])
    @require_auth
    def route_screen_changes_baseline():
        """Baseline the current frame and start tracking."""
        img = _capture()
        if img is None:
            return jsonify({"error": "screenshot unavailable"}), 500
        global _BASELINE, _BASELINE_ID, _LAST_FRAME
        with _LOCK:
            _BASELINE = img
            _BASELINE_ID = time.strftime("%Y%m%d_%H%M%S")
            _LAST_FRAME = img
        return jsonify({
            "baseline_id": _BASELINE_ID,
            "size": [img.width, img.height],
            "tracking": True,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    @app.route("/screen/changes", methods=["GET"])
    @require_auth
    def route_screen_changes_get():
        """Regions changed since the last call (empty list when idle).

        Query params:
          threshold  - pixel-change threshold 0-255 (default 8)
          patches    - "1" to include cropped JPEG base64 patches
        """
        try:
            threshold = int(request.args.get("threshold", _DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            threshold = _DEFAULT_THRESHOLD
        threshold = max(0, min(threshold, 255))
        include_patches = request.args.get("patches", "0") in ("1", "true", "yes")

        img = _capture()
        if img is None:
            return jsonify({"error": "screenshot unavailable"}), 500

        global _BASELINE, _LAST_FRAME
        with _LOCK:
            base = _BASELINE if _BASELINE is not None else _LAST_FRAME
            if base is None:
                base = img
            _LAST_FRAME = img

        regions, changed_pixels, percent = _diff_regions(base, img, threshold)

        result = {
            "changed": changed_pixels > 0,
            "changed_pixels": changed_pixels,
            "percent_changed": percent,
            "regions": regions,
            "region_count": len(regions),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if include_patches and changed_pixels > 0:
            patches = []
            for r in regions[:_MAX_PATCHES]:
                b64 = _patch_b64(img, r)
                if b64:
                    patches.append({
                        "x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"],
                        "mime": "image/jpeg", "base64": b64,
                    })
            result["patches"] = patches
            result["patch_count"] = len(patches)
        return jsonify(result)

    @app.route("/screen/changes/full", methods=["GET"])
    @require_auth
    def route_screen_changes_full():
        """Force a full frame (JPEG base64) and reset the baseline to it."""
        img = _capture()
        if img is None:
            return jsonify({"error": "screenshot unavailable"}), 500
        global _BASELINE, _LAST_FRAME
        with _LOCK:
            _BASELINE = img
            _LAST_FRAME = img
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return jsonify({
            "mime": "image/jpeg",
            "size": [img.width, img.height],
            "base64": b64,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

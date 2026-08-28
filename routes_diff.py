"""Before/after screenshot diff routes."""

import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from shared import COAGENT_DIR, _console, _json_body


DIFFS_DIR = COAGENT_DIR / "diffs"
MAX_RESULTS = 50
MAX_SNAPSHOTS = 50

_LOCK = threading.RLock()
_SNAPSHOTS = []
_RESULTS = []


def _new_id():
    return f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _capture_image():
    import mss as _mss_mod
    from PIL import Image as _PILImage

    image = None
    try:
        with _mss_mod.mss() as _sct:
            _mon = _sct.monitors[0]
            _sct_img = _sct.grab(_mon)
            image = _PILImage.frombytes("RGB", _sct_img.size, _sct_img.rgb)
    except TypeError:
        try:
            with _mss_mod.mss() as _sct:
                _mon = _sct.monitors[1] if len(_sct.monitors) > 1 else _sct.monitors[0]
                _sct_img = _sct.grab(_mon)
                image = _PILImage.frombytes("RGB", _sct_img.size, _sct_img.rgb)
        except Exception:
            pass
    except Exception:
        pass
    if image is None:
        try:
            from PIL import ImageGrab
            image = ImageGrab.grab()
        except Exception:
            pass
    if image is None:
        raise RuntimeError("All screenshot capture methods failed")
    return image.convert("RGB")


def _same_size(base, current):
    if base.size == current.size:
        return base, current
    from PIL import Image

    width = max(base.size[0], current.size[0])
    height = max(base.size[1], current.size[1])
    base_canvas = Image.new("RGB", (width, height), "black")
    current_canvas = Image.new("RGB", (width, height), "black")
    base_canvas.paste(base, (0, 0))
    current_canvas.paste(current, (0, 0))
    return base_canvas, current_canvas


def _find_regions(mask, max_regions=50):
    bbox = mask.getbbox()
    if not bbox:
        return []
    from PIL import Image

    width, height = mask.size
    tile = 8 if width * height <= 4_000_000 else 16
    small_w = max(1, (width + tile - 1) // tile)
    small_h = max(1, (height + tile - 1) // tile)
    resampling = getattr(getattr(Image, "Resampling", Image), "BOX", Image.BOX)
    small = mask.resize((small_w, small_h), resample=resampling)
    data = small.load()
    visited = set()
    regions = []

    for sy in range(small_h):
        for sx in range(small_w):
            if (sx, sy) in visited or not data[sx, sy]:
                continue
            queue = deque([(sx, sy)])
            visited.add((sx, sy))
            min_x = max_x = sx
            min_y = max_y = sy
            while queue:
                x, y = queue.popleft()
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= small_w or ny >= small_h:
                        continue
                    if (nx, ny) in visited or not data[nx, ny]:
                        continue
                    visited.add((nx, ny))
                    queue.append((nx, ny))
            x = min_x * tile
            y = min_y * tile
            w = min(width, (max_x + 1) * tile) - x
            h = min(height, (max_y + 1) * tile) - y
            if w > 0 and h > 0:
                regions.append({"x": x, "y": y, "w": w, "h": h})

    regions.sort(key=lambda r: r["w"] * r["h"], reverse=True)
    return regions[:max_regions]


def _snapshot_by_id(snapshot_id):
    with _LOCK:
        if snapshot_id:
            for snapshot in reversed(_SNAPSHOTS):
                if snapshot.get("snapshot_id") == snapshot_id:
                    return dict(snapshot)
            return None
        return dict(_SNAPSHOTS[-1]) if _SNAPSHOTS else None


def register_routes(app, state, require_auth):
    bp = Blueprint("diff", __name__)

    @bp.route("/diff/capture", methods=["POST"])
    @require_auth
    def route_diff_capture():
        data = _json_body()
        snapshot_id = _new_id()
        label = str(data.get("label") or snapshot_id)
        timestamp = datetime.now().isoformat(timespec="seconds")
        DIFFS_DIR.mkdir(parents=True, exist_ok=True)
        path = DIFFS_DIR / f"snapshot_{snapshot_id}.png"
        try:
            image = _capture_image()
            image.save(path, format="PNG")
        except Exception as exc:
            _console(f"[diff] baseline capture failed: {type(exc).__name__}: {exc}")
            return jsonify({"error": f"failed to capture screenshot: {exc}"}), 500

        snapshot = {
            "snapshot_id": snapshot_id,
            "label": label,
            "timestamp": timestamp,
            "path": str(path),
        }
        with _LOCK:
            _SNAPSHOTS.append(snapshot)
            if len(_SNAPSHOTS) > MAX_SNAPSHOTS:
                evicted = _SNAPSHOTS[:len(_SNAPSHOTS) - MAX_SNAPSHOTS]
                del _SNAPSHOTS[:len(_SNAPSHOTS) - MAX_SNAPSHOTS]
                for old in evicted:
                    try:
                        Path(old.get("path", "")).unlink(missing_ok=True)
                    except Exception:
                        pass
        return jsonify(snapshot)

    @bp.route("/diff/compare", methods=["POST"])
    @require_auth
    def route_diff_compare():
        data = _json_body()
        baseline = _snapshot_by_id(data.get("baseline_id"))
        if not baseline:
            return jsonify({"error": "baseline snapshot not found"}), 404

        try:
            from PIL import Image, ImageChops

            with Image.open(baseline["path"]) as _baseline_handle:
                baseline_image = _baseline_handle.convert("RGB")
            current_image = _capture_image()
            baseline_image, current_image = _same_size(baseline_image, current_image)
            diff = ImageChops.difference(baseline_image, current_image)
            mask = diff.convert("L").point(lambda px: 255 if px else 0)
            total_pixels = mask.size[0] * mask.size[1]
            histogram = mask.histogram()
            changed_pixels = total_pixels - histogram[0]
            percent_changed = round((changed_pixels / total_pixels) * 100, 4) if total_pixels else 0
            regions = _find_regions(mask)

            diff_id = _new_id()
            diff_path = DIFFS_DIR / f"diff_{diff_id}.png"
            white = Image.new("RGB", mask.size, "white")
            red = Image.new("RGB", mask.size, (255, 0, 0))
            white.paste(red, mask=mask)
            white.save(diff_path, format="PNG")
        except FileNotFoundError:
            return jsonify({"error": "baseline image file is missing", "path": baseline.get("path")}), 404
        except Exception as exc:
            _console(f"[diff] compare failed: {type(exc).__name__}: {exc}")
            return jsonify({"error": f"failed to compare screenshots: {exc}"}), 500

        result = {
            "diff_id": diff_id,
            "baseline_id": baseline["snapshot_id"],
            "changed": changed_pixels > 0,
            "changed_pixels": changed_pixels,
            "percent_changed": percent_changed,
            "diff_image_path": str(diff_path),
            "regions": regions,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        with _LOCK:
            _RESULTS.append(result)
            if len(_RESULTS) > MAX_RESULTS:
                evicted = _RESULTS[:len(_RESULTS) - MAX_RESULTS]
                del _RESULTS[:len(_RESULTS) - MAX_RESULTS]
                for old in evicted:
                    try:
                        Path(old.get("diff_image_path", "")).unlink(missing_ok=True)
                    except Exception:
                        pass
        return jsonify(result)

    @bp.route("/diff/results", methods=["GET"])
    @require_auth
    def route_diff_results():
        try:
            limit = int(request.args.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, MAX_RESULTS))
        with _LOCK:
            results = list(reversed(_RESULTS[-limit:]))
        return jsonify({"results": results, "count": len(results)})

    @bp.route("/diff/image/<diff_id>", methods=["GET"])
    @require_auth
    def route_diff_image(diff_id):
        with _LOCK:
            result = next((dict(item) for item in _RESULTS if item.get("diff_id") == diff_id), None)
        path = result.get("diff_image_path") if result else str(DIFFS_DIR / f"diff_{diff_id}.png")
        try:
            candidate = DIFFS_DIR / str(path).split("\\")[-1].split("/")[-1]
            if not candidate.exists() and result:
                candidate = DIFFS_DIR / str(result["diff_image_path"]).split("\\")[-1].split("/")[-1]
            if not candidate.exists():
                return jsonify({"error": "diff image not found"}), 404
            return send_file(candidate, mimetype="image/png", as_attachment=False)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    app.register_blueprint(bp)

"""Hermes CoAgent v8.2 — P-frame differential screenshot capture.

Captures the full screen on first call (key frame), then only sends
changed regions (diff frames) on subsequent calls to reduce token usage.
"""

import hashlib
import logging
import time
from io import BytesIO
from pathlib import Path

from flask import Blueprint, jsonify

_LOGGER = logging.getLogger(__name__)

try:
    from PIL import Image, ImageChops, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

diff_bp = Blueprint("diff_capture", __name__)

# State
_prev_frame = None
_prev_hash = None
_frame_count = 0
_stats = {"key_frames": 0, "diff_frames": 0, "total_bytes_saved": 0}


def _capture_screen():
    """Capture the full screen as a PIL Image."""
    try:
        from PIL import ImageGrab
        return ImageGrab.grab()
    except Exception as e:
        _LOGGER.error("Screen capture failed: %s", e)
        return None


def _compute_hash(img):
    """Compute a simple perceptual hash for change detection."""
    if img is None:
        return None
    small = img.resize((32, 32), Image.LANCZOS).convert("L")
    return hashlib.md5(small.tobytes()).hexdigest()


def _find_changed_regions(prev, curr, grid_size=8, threshold=30):
    """Divide screen into NxN grid and find changed cells."""
    w, h = curr.size
    cell_w = w // grid_size
    cell_h = h // grid_size
    changed = []

    for gx in range(grid_size):
        for gy in range(grid_size):
            left = gx * cell_w
            top = gy * cell_h
            right = left + cell_w if gx < grid_size - 1 else w
            bottom = top + cell_h if gy < grid_size - 1 else h

            prev_cell = prev.crop((left, top, right, bottom))
            curr_cell = curr.crop((left, top, right, bottom))

            diff = ImageChops.difference(prev_cell, curr_cell)
            hist = diff.histogram()
            # Sum of pixel differences across all channels
            diff_sum = sum(hist[i] * i for i in range(256)) / max(255 * w * h, 1)
            if diff_sum > threshold:
                changed.append((left, top, right - left, bottom - top))

    return changed


def capture():
    """Capture and diff. Returns dict with frame info."""
    global _prev_frame, _prev_hash, _frame_count, _stats

    if not HAS_PIL:
        return {"error": "Pillow not available"}

    curr = _capture_screen()
    if curr is None:
        return {"error": "Screen capture failed"}

    curr_hash = _compute_hash(curr)
    _frame_count += 1

    if _prev_frame is None or _prev_hash is None:
        # Key frame
        _prev_frame = curr.copy()
        _prev_hash = curr_hash
        _stats["key_frames"] += 1
        return {
            "full": True,
            "frame": _frame_count,
            "changed_regions": [],
            "total_changed_pct": 0.0,
            "width": curr.width,
            "height": curr.height,
        }

    if curr_hash == _prev_hash:
        # No change at all
        return {
            "full": False,
            "frame": _frame_count,
            "changed_regions": [],
            "total_changed_pct": 0.0,
            "no_change": True,
            "width": curr.width,
            "height": curr.height,
        }

    # Find changed regions
    regions = _find_changed_regions(_prev_frame, curr)
    total_pixels = curr.width * curr.height
    changed_pixels = sum(w * h for (x, y, w, h) in regions)
    changed_pct = round(changed_pixels / max(total_pixels, 1) * 100, 2)

    # If less than 60% changed, keep as diff frame
    is_full = changed_pct >= 60.0

    if is_full:
        _stats["key_frames"] += 1
        result = {"full": True}
    else:
        _stats["diff_frames"] += 1
        saved = total_pixels - changed_pixels
        _stats["total_bytes_saved"] += saved
        result = {"full": False}

    # Update prev state
    if is_full or _frame_count % 10 == 0:
        # Periodically refresh the reference frame to prevent drift
        _prev_frame = curr.copy()
        _prev_hash = curr_hash

    result.update({
        "frame": _frame_count,
        "changed_regions": regions,
        "total_changed_pct": changed_pct,
        "region_count": len(regions),
        "width": curr.width,
        "height": curr.height,
    })
    return result


def reset():
    """Force next capture to be a full key frame."""
    global _prev_frame, _prev_hash
    _prev_frame = None
    _prev_hash = None
    _LOGGER.info("Diff capture reset — next frame will be key frame")


def get_stats():
    """Return compression statistics."""
    total_frames = _stats["key_frames"] + _stats["diff_frames"]
    ratio = round(_stats["total_bytes_saved"] / max(1, total_frames), 0)
    return {
        "key_frames": _stats["key_frames"],
        "diff_frames": _stats["diff_frames"],
        "total_frames": total_frames,
        "avg_bytes_saved_per_frame": int(ratio),
        "compression_ratio": round(
            _stats["total_bytes_saved"] / max(1, _stats["key_frames"] * 1920 * 1080 * 3), 4
        ),
    }


# ── Flask endpoints ──────────────────────────────────────────────────────


@diff_bp.route("/screen/diff", methods=["GET"])
def api_capture():
    """GET /screen/diff — capture and return diff information."""
    result = capture()
    return jsonify(result)


@diff_bp.route("/screen/diff/reset", methods=["POST"])
def api_reset():
    """POST /screen/diff/reset — force next capture as key frame."""
    reset()
    return jsonify({"success": True, "message": "Diff capture reset"})


@diff_bp.route("/screen/diff/stats", methods=["GET"])
def api_stats():
    """GET /screen/diff/stats — compression statistics."""
    return jsonify(get_stats())

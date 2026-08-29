"""QR / barcode decoding routes.

Endpoints:
  POST /vision/qr        - decode QR/barcode from the live screen (full or region)
  POST /vision/qr/file   - decode from an image file path
  POST /vision/qr/data   - decode from base64 or raw image bytes

Decoding is done with OpenCV (cv2.QRCodeDetector), the same dependency the
template-matching module already relies on. OpenCV's optional barcode detector
(cv2.barcode_BarcodeDetector, opencv-contrib) is used when available, and pyzbar
is tried as a last resort so both 1D barcodes and 2D QR codes are supported.
cv2/numpy are imported lazily so the Linux syntax-check CI stays green and the
server still boots when OpenCV is absent; endpoints then return HTTP 501.
"""

import base64
import json
import os

from flask import jsonify

from shared import _json_body, _log, _missing_field


# ---------------------------------------------------------------------------
# OpenCV availability
# ---------------------------------------------------------------------------

def _require_cv2():
    try:
        import cv2  # noqa: F401
        import numpy as np  # noqa: F401
        return cv2, np
    except Exception:
        return None, None


def _grab_screen_cv2(region=None):
    """Return a BGR numpy array for the screen or a sub-region (x, y, w, h)."""
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            if region:
                x, y, w, h = region
                mon = {"left": int(x), "top": int(y),
                       "width": int(w), "height": int(h)}
            else:
                mon = sct.monitors[1]
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
    except Exception:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        if region:
            x, y, w, h = region
            img = img.crop((x, y, x + w, y + h))

    import cv2
    import numpy as np
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    return arr


def _decode_qr(cv2, arr):
    """Decode QR codes with cv2.QRCodeDetector. Returns list of detections."""
    detections = []
    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(arr)
    if data:
        pts = None
        if points is not None and len(points):
            try:
                pts = [[int(p[0]), int(p[1])] for p in points[0]]
            except Exception:
                pts = None
        detections.append({
            "type": "qr",
            "payload": data,
            "points": pts,
        })
    return detections


def _decode_barcode_cv2(cv2, arr):
    """Decode 1D barcodes with cv2.barcode_BarcodeDetector (opencv-contrib)."""
    if not hasattr(cv2, "barcode_BarcodeDetector"):
        return []
    detections = []
    try:
        detector = cv2.barcode_BarcodeDetector()
        ok, decoded_info, decoded_type, points = detector.detectAndDecode(arr)
        if not ok or decoded_info is None:
            return []
        infos = list(decoded_info) if isinstance(decoded_info, (tuple, list)) else [decoded_info]
        types = list(decoded_type) if isinstance(decoded_type, (tuple, list)) else [decoded_type]
        pt_lists = list(points) if isinstance(points, (tuple, list)) else [points]
        for i, info in enumerate(infos):
            btype = types[i] if i < len(types) else "barcode"
            if isinstance(btype, bytes):
                btype = btype.decode("utf-8", errors="replace")
            pts = None
            try:
                pts = [[int(float(c[0])), int(float(c[1]))] for c in pt_lists[i]]
            except Exception:
                pts = None
            detections.append({
                "type": "barcode",
                "payload": str(info),
                "points": pts,
            })
    except Exception:
        pass
    return detections


def _decode_pyzbar(arr):
    """Last-resort decode via pyzbar when installed."""
    try:
        from pyzbar import pyzbar
        from PIL import Image
    except Exception:
        return []
    import numpy as np
    try:
        pil = Image.fromarray(arr[:, :, ::-1])  # BGR -> RGB
        results = pyzbar.decode(pil)
    except Exception:
        return []
    detections = []
    for r in results:
        detections.append({
            "type": r.type.lower(),
            "payload": r.data.decode("utf-8", errors="replace"),
            "points": [[p.x, p.y] for p in r.polygon],
        })
    return detections


def _decode_array(arr):
    """Run every available decoder and return (detections, decoder_used)."""
    cv2, np = _require_cv2()
    if cv2 is None:
        return [], "opencv-unavailable"

    detections = []
    detections.extend(_decode_qr(cv2, arr))
    detections.extend(_decode_barcode_cv2(cv2, arr))
    used = "cv2"
    if not detections:
        detections = _decode_pyzbar(arr)
        if detections:
            used = "pyzbar"
    return detections, used


def _array_from_bytes(data):
    """Decode raw image bytes (any cv2-supported format) to a BGR array."""
    import cv2
    import numpy as np
    buf = np.frombuffer(data, dtype=np.uint8)
    arr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return arr


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/vision/qr", methods=["POST"])
    @require_auth
    def route_vision_qr():
        """Decode QR/barcodes from the live screen.

        Body (all optional): {"x","y","w","h"} region, {"window":"title hint"},
        or {} for the primary monitor.
        """
        cv2, _ = _require_cv2()
        if cv2 is None:
            return jsonify({"error": "OpenCV not available (install opencv-python)"}), 501

        d = _json_body()
        if not isinstance(d, dict):
            d = {}

        try:
            region = None
            x = d.get("x")
            y = d.get("y")
            w = d.get("w")
            h = d.get("h")
            if all(v is not None for v in (x, y, w, h)):
                region = (int(x), int(y), int(w), int(h))
            elif d.get("window"):
                region = _window_region(str(d["window"]))
                if region is None:
                    return jsonify({"error": f"No visible window matching '{d['window']}'"}), 404
            arr = _grab_screen_cv2(region)
        except Exception as exc:
            return jsonify({"error": f"screen capture failed: {exc}"}), 500

        detections, used = _decode_array(arr)
        _log(f"vision/qr screen: {len(detections)} code(s) via {used}")
        return jsonify({
            "status": "ok",
            "decoder": used,
            "count": len(detections),
            "codes": detections,
        })

    @app.route("/vision/qr/file", methods=["POST"])
    @require_auth
    def route_vision_qr_file():
        """Decode QR/barcodes from an image file. Body: {"path": "..."}"""
        cv2, _ = _require_cv2()
        if cv2 is None:
            return jsonify({"error": "OpenCV not available (install opencv-python)"}), 501

        d = _json_body()
        if not isinstance(d, dict):
            d = {}
        path = d.get("path")
        if not path:
            return _missing_field("path")

        if not os.path.isfile(path):
            return jsonify({"error": f"file not found: {path}"}), 404

        import cv2
        arr = cv2.imread(path, cv2.IMREAD_COLOR)
        if arr is None:
            return jsonify({"error": "could not decode image (unsupported format)"}), 400

        detections, used = _decode_array(arr)
        _log(f"vision/qr/file {path}: {len(detections)} code(s) via {used}")
        return jsonify({
            "status": "ok",
            "path": path,
            "decoder": used,
            "count": len(detections),
            "codes": detections,
        })

    @app.route("/vision/qr/data", methods=["POST"])
    @require_auth
    def route_vision_qr_data():
        """Decode QR/barcodes from base64 or raw image bytes. Body: {"data": ...}"""
        cv2, _ = _require_cv2()
        if cv2 is None:
            return jsonify({"error": "OpenCV not available (install opencv-python)"}), 501

        d = _json_body()
        if not isinstance(d, dict):
            d = {}
        raw = d.get("data")
        if raw is None:
            return _missing_field("data")

        try:
            if isinstance(raw, str):
                s = raw.strip()
                # strip a data URI prefix if present
                if s.startswith("data:") and "," in s:
                    s = s.split(",", 1)[1]
                if d.get("encoding") == "base64" or _looks_base64(s):
                    payload = base64.b64decode(s, validate=True)
                else:
                    payload = s.encode("utf-8")
            elif isinstance(raw, (bytes, bytearray)):
                payload = bytes(raw)
            else:
                return jsonify({"error": "data must be a string, base64, or bytes"}), 400
            arr = _array_from_bytes(payload)
        except Exception as exc:
            return jsonify({"error": f"failed to decode image data: {exc}"}), 400

        if arr is None:
            return jsonify({"error": "could not decode image (unsupported format)"}), 400

        detections, used = _decode_array(arr)
        _log(f"vision/qr/data: {len(detections)} code(s) via {used}")
        return jsonify({
            "status": "ok",
            "decoder": used,
            "count": len(detections),
            "codes": detections,
        })


# ---------------------------------------------------------------------------
# Helpers kept module-private (screen region lookup)
# ---------------------------------------------------------------------------

def _window_region(window_hint):
    """Return (x, y, w, h) screen rect for the first visible window whose title
    contains *window_hint* (case-insensitive). Returns None on failure."""
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        hint = str(window_hint).lower()
        result = [None]

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(hwnd, _lp):
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.IsIconic(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if hint in buf.value.lower():
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 0 and h > 0:
                    result[0] = (rect.left, rect.top, w, h)
                    return False
            return True

        user32.EnumWindows(_cb, 0)
        return result[0]
    except Exception:
        return None


def _looks_base64(s):
    """Heuristic: a string with no spaces, valid base64 chars, and padding."""
    if not s or len(s) < 4 or " " in s or "\n" in s:
        return False
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False

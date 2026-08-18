"""Fused element map (issue #73).

Combines the UIA accessibility tree with OCR results into a single flat list
of addressable elements. Each element carries:
  - id (stable within a snapshot)
  - source: "uia" | "ocr" | "fused" (both agreed)
  - center: {x, y}
  - bbox:  {x, y, w, h}
  - text:  best textual label available (UIA name / OCR text)
  - control_type: from UIA (if source is uia/fused)
  - confidence: 0..1 — 1.0 for UIA, OCR conf for ocr; averaged for fused

Fusing is done by center-in-rect overlap: an OCR word whose center lies inside
a UIA element's bounding rect is folded into that element (extending its text
if the UIA name was empty). Standalone OCR words become ocr-source elements.
"""
import sys
import threading
import time
import uuid

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log

_SNAPSHOTS = {}
_LOCK = threading.Lock()
_MAX_SNAPSHOTS = 16

# Lazy uia_engine import is serialized so concurrent requests can't interleave
# sys.path.insert(0, ...)/pop(0) and corrupt process-wide import resolution.
_UE_IMPORT_LOCK = threading.Lock()
_UE_ENGINE = None
_UE_ERROR = None


def _coord(rect, keys):
    """First key present with a non-None value in rect, else None.

    Uses explicit key presence (not truthiness) so a legitimate 0 coordinate
    is honored rather than treated as missing.
    """
    for k in keys:
        if k in rect and rect[k] is not None:
            return rect[k]
    return None


def _get_uia_engine():
    """Import uia_engine once, thread-safely; return (module_or_None, error_or_None)."""
    global _UE_ENGINE, _UE_ERROR
    with _UE_IMPORT_LOCK:
        if _UE_ENGINE is None and _UE_ERROR is None:
            try:
                sys.path.insert(0, str(COAGENT_DIR))
                try:
                    import uia_engine as ue
                finally:
                    sys.path.pop(0)
                _UE_ENGINE = ue
            except Exception as e:
                _UE_ERROR = f"uia_engine unavailable: {e}"
        return _UE_ENGINE, _UE_ERROR


def _uia_flat():
    """Return a flat list of UIA elements with (bbox, name, control_type)."""
    ue, err = _get_uia_engine()
    if ue is None:
        return None, err
    try:
        snap = ue.uia_snapshot(timeout=8) if hasattr(ue, "uia_snapshot") else {}
    except Exception as e:
        return None, f"uia snapshot failed: {e}"
    flat = []

    def _walk(node):
        if not isinstance(node, dict):
            return
        rect = node.get("rect") or node.get("bounding_rect")
        if isinstance(rect, dict):
            left = _coord(rect, ("left", "x"))
            top = _coord(rect, ("top", "y"))
            x = int(left) if left is not None else 0
            y = int(top) if top is not None else 0
            right = _coord(rect, ("right",))
            if right is None:
                width = _coord(rect, ("width",))
                right = x + (int(width) if width is not None else 0)
            else:
                right = int(right)
            bottom = _coord(rect, ("bottom",))
            if bottom is None:
                height = _coord(rect, ("height",))
                bottom = y + (int(height) if height is not None else 0)
            else:
                bottom = int(bottom)
            w, h = max(0, right - x), max(0, bottom - y)
            if w > 0 and h > 0:
                flat.append({
                    "bbox": {"x": x, "y": y, "w": w, "h": h},
                    "name": node.get("name") or node.get("title") or "",
                    "control_type": node.get("control_type") or node.get("class_name") or "",
                    "automation_id": node.get("automation_id"),
                })
        for child in (node.get("children") or []):
            _walk(child)

    windows = snap.get("windows") if isinstance(snap, dict) else None
    if isinstance(windows, list):
        for w in windows:
            _walk(w)
    else:
        _walk(snap)
    return flat, None


def _ocr_flat():
    """OCR the primary display, return list of {bbox, text, conf}."""
    try:
        import mss
        from PIL import Image
    except ImportError:
        return None, "mss/PIL not installed"
    with mss.mss() as sct:
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    # Try RapidOCR
    try:
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        engine = RapidOCR()
        result, _ = engine(np.array(img))
        words = []
        for det in (result or []):
            box, txt, conf = det[0], det[1], det[2]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append({
                "bbox": {"x": int(min(xs)), "y": int(min(ys)),
                         "w": int(max(xs) - min(xs)),
                         "h": int(max(ys) - min(ys))},
                "text": str(txt),
                "conf": float(conf),
            })
        return words, None
    except Exception:
        pass
    try:
        import pytesseract
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        words = []
        for i, t in enumerate(data.get("text", [])):
            if t and t.strip():
                words.append({
                    "bbox": {"x": int(data["left"][i]), "y": int(data["top"][i]),
                             "w": int(data["width"][i]), "h": int(data["height"][i])},
                    "text": t,
                    "conf": max(0.0, float(data["conf"][i] or 0)) / 100.0,
                })
        return words, None
    except Exception as e:
        return None, f"no OCR engine: {e}"


def _center(bbox):
    return {"x": int(bbox["x"] + bbox["w"] / 2), "y": int(bbox["y"] + bbox["h"] / 2)}


def _contains(rect, pt):
    return (rect["x"] <= pt["x"] < rect["x"] + rect["w"]) and \
           (rect["y"] <= pt["y"] < rect["y"] + rect["h"])


def _fuse(uia_els, ocr_words):
    elements = []
    ocr_used = set()
    for el in uia_els:
        entry = {
            "id": uuid.uuid4().hex[:8],
            "source": "uia",
            "bbox": el["bbox"],
            "center": _center(el["bbox"]),
            "text": el.get("name") or "",
            "control_type": el.get("control_type") or "",
            "automation_id": el.get("automation_id"),
            "confidence": 1.0,
        }
        # Absorb any OCR word whose center falls inside this bbox
        merged_texts, ocr_confs = [], []
        for i, w in enumerate(ocr_words):
            if i in ocr_used:
                continue
            if _contains(el["bbox"], _center(w["bbox"])):
                merged_texts.append(w["text"])
                ocr_confs.append(w["conf"])
                ocr_used.add(i)
        if merged_texts:
            merged_text = " ".join(merged_texts).strip()
            if not entry["text"]:
                entry["text"] = merged_text
            else:
                entry["ocr_text"] = merged_text
            entry["source"] = "fused"
            avg = sum(ocr_confs) / len(ocr_confs) if ocr_confs else 1.0
            entry["confidence"] = round((1.0 + avg) / 2.0, 3)
        elements.append(entry)
    for i, w in enumerate(ocr_words):
        if i in ocr_used:
            continue
        elements.append({
            "id": uuid.uuid4().hex[:8],
            "source": "ocr",
            "bbox": w["bbox"],
            "center": _center(w["bbox"]),
            "text": w["text"],
            "control_type": "",
            "confidence": round(float(w["conf"]), 3),
        })
    return elements


def _store_snapshot(snap):
    with _LOCK:
        _SNAPSHOTS[snap["id"]] = snap
        if len(_SNAPSHOTS) > _MAX_SNAPSHOTS:
            oldest = min(_SNAPSHOTS.keys(), key=lambda k: _SNAPSHOTS[k]["ts"])
            _SNAPSHOTS.pop(oldest, None)


def register_routes(app, state, require_auth):

    @app.route("/fused/snapshot", methods=["POST"])
    @require_auth
    def route_fused_snap():
        body = _json_body() or {}
        include_ocr = bool(body.get("include_ocr", True))
        include_uia = bool(body.get("include_uia", True))

        uia_els, uia_err = ([], None)
        if include_uia:
            uia_els, uia_err = _uia_flat()
            if uia_els is None:
                uia_els = []

        ocr_words, ocr_err = ([], None)
        if include_ocr:
            ocr_words, ocr_err = _ocr_flat()
            if ocr_words is None:
                ocr_words = []

        elements = _fuse(uia_els, ocr_words)
        snap = {
            "id": uuid.uuid4().hex[:12],
            "ts": time.time(),
            "counts": {"uia": len(uia_els), "ocr": len(ocr_words), "fused": len(elements)},
            "warnings": [w for w in (uia_err, ocr_err) if w],
            "elements": elements,
        }
        _store_snapshot(snap)
        return jsonify({"ok": True, "snapshot": snap})

    @app.route("/fused/latest", methods=["GET"])
    @require_auth
    def route_fused_latest():
        with _LOCK:
            if not _SNAPSHOTS:
                return jsonify({"ok": False, "error": "no snapshots"}), 404
            latest = max(_SNAPSHOTS.values(), key=lambda s: s["ts"])
        return jsonify({"ok": True, "snapshot": latest})

    @app.route("/fused/query", methods=["POST"])
    @require_auth
    def route_fused_query():
        """Body: {"snapshot_id": "..." (optional; latest if omitted),
                  "text_contains": "...", "control_type": "Button",
                  "min_confidence": 0.4, "limit": 25}"""
        body = _json_body() or {}
        with _LOCK:
            if body.get("snapshot_id"):
                snap = _SNAPSHOTS.get(body["snapshot_id"])
            else:
                snap = max(_SNAPSHOTS.values(), key=lambda s: s["ts"], default=None)
        if not snap:
            return jsonify({"ok": False, "error": "snapshot not found"}), 404
        text_q = (body.get("text_contains") or "").lower()
        type_q = (body.get("control_type") or "").lower()
        try:
            min_conf = float(body.get("min_confidence", 0.0))
            limit = max(1, min(500, int(body.get("limit", 100))))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "min_confidence must be a number and limit an integer"}), 400

        out = []
        for e in snap["elements"]:
            if text_q and text_q not in (e.get("text") or "").lower():
                continue
            if type_q and type_q not in (e.get("control_type") or "").lower():
                continue
            if e.get("confidence", 0) < min_conf:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return jsonify({"ok": True, "count": len(out), "matches": out,
                        "snapshot_id": snap["id"]})

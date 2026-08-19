"""PII Redaction Layer.

Before any screenshot leaves to a cloud LLM, OCR it locally and mask
sensitive areas (credit cards, SSNs, email addresses, phone numbers).
"""
import base64
import io
import logging
import re
import threading
from datetime import datetime

from flask import Blueprint, jsonify, request

_LOGGER = logging.getLogger(__name__)
pii_bp = Blueprint("pii_redact", __name__)

_PII_LOCK = threading.Lock()
_PII_CONFIG = {
    "patterns": {
        "credit_card": {"enabled": True, "regex": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"},
        "ssn": {"enabled": True, "regex": r"\b\d{3}-\d{2}-\d{4}\b"},
        "email": {"enabled": True, "regex": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"},
        "phone": {"enabled": True, "regex": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"},
        "custom": {"enabled": False, "regex": None},
    },
    "mask_char": "\u2588",  # Full block
}
_PII_STATS = {
    "images_processed": 0,
    "regions_masked": 0,
    "text_processed": 0,
    "last_redaction": None,
}


def _debug_failure(context, exc):
    _LOGGER.debug("pii_redact %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _find_pii_regions(text):
    """Find all PII matches in text with positions."""
    regions = []
    with _PII_LOCK:
        config = {k: dict(v) for k, v in _PII_CONFIG["patterns"].items()}
    for name, cfg in config.items():
        if not cfg.get("enabled") or not cfg.get("regex"):
            continue
        try:
            for match in re.finditer(cfg["regex"], text):
                regions.append({
                    "pattern": name,
                    "start": match.start(),
                    "end": match.end(),
                    "matched": match.group(),
                })
        except re.error as exc:
            _debug_failure(f"regex {name}", exc)
    return regions


def _redact_text(text):
    """Replace PII matches with mask characters."""
    regions = _find_pii_regions(text)
    if not regions:
        return text, 0
    # Sort by start position descending to avoid offset issues
    sorted_regions = sorted(regions, key=lambda r: -r["start"])
    result = text
    count = 0
    for region in sorted_regions:
        mask_len = region["end"] - region["start"]
        result = result[:region["start"]] + (_PII_CONFIG["mask_char"] * mask_len) + result[region["end"]:]
        count += 1
    return result, count


def _redact_image(base64_str):
    """Redact PII in an image by OCR-ing text and drawing black rectangles."""
    try:
        from PIL import Image, ImageDraw
        img_data = base64.b64decode(base64_str)
        img = Image.open(io.BytesIO(img_data))
        draw = ImageDraw.Draw(img)

        # Try to use pytesseract for OCR
        try:
            import pytesseract
            ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            regions_masked = []
            for i in range(len(ocr_data["text"])):
                text = ocr_data["text"][i]
                if not text or not text.strip():
                    continue
                pii_regions = _find_pii_regions(text)
                if pii_regions:
                    x, y, w, h = (ocr_data["left"][i], ocr_data["top"][i],
                                   ocr_data["width"][i], ocr_data["height"][i])
                    draw.rectangle([x, y, x + w, y + h], fill="black")
                    regions_masked.append({
                        "x": x, "y": y, "w": w, "h": h,
                        "matched": text[:20],
                    })

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result_base64 = base64.b64encode(buf.getvalue()).decode()
            return result_base64, regions_masked, len(regions_masked)
        except ImportError:
            _LOGGER.warning("pytesseract not installed — cannot redact image PII")
            return None, [], -1  # error indicator: caller must block
    except Exception as exc:
        _debug_failure("redact_image", exc)
        return None, [], -1  # error indicator: caller must block


@pii_bp.route("/pii/redact", methods=["POST"])
def _pii_redact():
    body = request.get_json(force=True, silent=True) or {}
    img_b64 = body.get("image_base64") or body.get("data")
    if not img_b64:
        return jsonify({"ok": False, "error": "missing image_base64"}), 400

    result_b64, regions, count = _redact_image(img_b64)
    if result_b64 is None:
        return jsonify({"ok": False, "error": "image redaction failed — image blocked for safety"}), 500
    with _PII_LOCK:
        _PII_STATS["images_processed"] += 1
        _PII_STATS["regions_masked"] += count
        _PII_STATS["last_redaction"] = datetime.now().isoformat()

    return jsonify({
        "ok": True,
        "redacted_base64": result_b64,
        "regions_masked": regions,
        "count": count,
    })


@pii_bp.route("/pii/redact-text", methods=["POST"])
def _pii_redact_text():
    body = request.get_json(force=True, silent=True) or {}
    text = body.get("text", "")
    if not text:
        return jsonify({"ok": False, "error": "missing text"}), 400

    redacted, count = _redact_text(text)
    with _PII_LOCK:
        _PII_STATS["text_processed"] += 1
        _PII_STATS["regions_masked"] += count
        _PII_STATS["last_redaction"] = datetime.now().isoformat()

    return jsonify({
        "ok": True,
        "redacted_text": redacted,
        "count": count,
    })


@pii_bp.route("/pii/status", methods=["GET"])
def _pii_status():
    with _PII_LOCK:
        return jsonify({"ok": True, "config": _PII_CONFIG, "stats": dict(_PII_STATS)})


@pii_bp.route("/pii/configure", methods=["POST"])
def _pii_configure():
    body = request.get_json(force=True, silent=True) or {}
    with _PII_LOCK:
        if "patterns" in body:
            for name, cfg in body["patterns"].items():
                if name in _PII_CONFIG["patterns"]:
                    if isinstance(cfg, dict):
                        # Validate regex before accepting
                        new_regex = cfg.get("regex")
                        if new_regex is not None and isinstance(new_regex, str):
                            if len(new_regex) > 500:
                                return jsonify({"ok": False, "error": "regex too long (max 500 chars)"}), 400
                            try:
                                re.compile(new_regex)
                            except re.error as e:
                                return jsonify({"ok": False, "error": f"invalid regex: {e}"}), 400
                        _PII_CONFIG["patterns"][name].update(cfg)
                    else:
                        _PII_CONFIG["patterns"][name]["enabled"] = bool(cfg)
        if "mask_char" in body:
            mask_char = body["mask_char"]
            if not isinstance(mask_char, str) or len(mask_char) != 1:
                return jsonify({"ok": False, "error": "mask_char must be a single character"}), 400
            _PII_CONFIG["mask_char"] = mask_char
    return jsonify({"ok": True, "config": _PII_CONFIG})


@pii_bp.route("/pii/test", methods=["POST"])
def _pii_test():
    body = request.get_json(force=True, silent=True) or {}
    text = body.get("text", "Default test: Email test@example.com, SSN 123-45-6789, card 4111-1111-1111-1111")
    regions = _find_pii_regions(text)
    redacted, count = _redact_text(text)
    return jsonify({
        "ok": True,
        "original": text,
        "redacted": redacted,
        "regions_found": regions,
        "count": count,
    })


def register_routes(app, state, require_auth):
    # Apply auth guard to all PII routes
    @pii_bp.before_request
    @require_auth
    def _pii_auth_guard():
        pass  # require_auth handles the actual check

    app.register_blueprint(pii_bp)
    _LOGGER.info("PII redaction routes registered")

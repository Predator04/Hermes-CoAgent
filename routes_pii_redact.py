"""PII Redaction Layer.

Before any screenshot leaves to a cloud LLM, OCR it locally and mask
sensitive areas (credit cards, SSNs, email addresses, phone numbers).
"""
import base64
import copy
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

# Refuse to decode/redact images larger than 50 megapixels — a small compressed
# PNG can decompress to a gigantic bitmap and exhaust memory (decompression bomb).
_MAX_IMAGE_PIXELS = 50_000_000
# Cap the base64 payload before decoding — b64decode runs ahead of the pixel
# guard, so a huge string would be expanded into memory (OOM) before any check.
_MAX_B64_CHARS = 100 * 1024 * 1024


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
    # Snapshot mask_char under lock so a concurrent /pii/configure can't race it.
    with _PII_LOCK:
        mask_char = _PII_CONFIG["mask_char"]
    result = text
    count = 0
    for region in sorted_regions:
        mask_len = region["end"] - region["start"]
        result = result[:region["start"]] + (mask_char * mask_len) + result[region["end"]:]
        count += 1
    return result, count


def _redact_image(base64_str):
    """Redact PII in an image by OCR-ing text and drawing black rectangles."""
    if not isinstance(base64_str, str) or len(base64_str) > _MAX_B64_CHARS:
        _LOGGER.warning("pii_redact: refusing oversized or non-string image payload")
        return None, [], -1
    try:
        from PIL import Image, ImageDraw
        img_data = base64.b64decode(base64_str)
        with Image.open(io.BytesIO(img_data)) as img:
            w, h = img.size
            if w * h > _MAX_IMAGE_PIXELS:
                _LOGGER.warning("image too large (%dx%d) — refusing to redact", w, h)
                return None, [], -1  # caller must block
            draw = ImageDraw.Draw(img)

            try:
                import pytesseract
                ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                regions_masked = []

                # Group words by (block, paragraph, line). The previous per-word
                # loop could never match multi-word PII like "4111 1111 1111 1111"
                # or a space-separated phone number, because each OCR word was
                # tested in isolation. Concatenate each line's words, run the
                # regexes over the full line, and mask the whole line's box.
                lines = {}
                for i in range(len(ocr_data["text"])):
                    text = ocr_data["text"][i]
                    if not text or not text.strip():
                        continue
                    key = (ocr_data["block_num"][i], ocr_data["par_num"][i],
                           ocr_data["line_num"][i])
                    lines.setdefault(key, []).append(i)

                for indices in lines.values():
                    line_text = " ".join(ocr_data["text"][i].strip() for i in indices)
                    if _find_pii_regions(line_text):
                        # Union of the bounding boxes for this line's words.
                        x0 = min(ocr_data["left"][i] for i in indices)
                        y0 = min(ocr_data["top"][i] for i in indices)
                        x1 = max(ocr_data["left"][i] + ocr_data["width"][i] for i in indices)
                        y1 = max(ocr_data["top"][i] + ocr_data["height"][i] for i in indices)
                        draw.rectangle([x0, y0, x1, y1], fill="black")
                        regions_masked.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})

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
    if not isinstance(text, str):
        return jsonify({"ok": False, "error": "text must be a string"}), 400

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
                        # Whitelist keys — never let arbitrary client keys pollute config.
                        for key in ("enabled", "regex"):
                            if key not in cfg:
                                continue
                            if key == "enabled" and not isinstance(cfg[key], bool):
                                continue
                            if key == "regex":
                                new_regex = cfg[key]
                                if new_regex is None:
                                    _PII_CONFIG["patterns"][name]["regex"] = None
                                    continue
                                if not isinstance(new_regex, str):
                                    continue
                                if len(new_regex) > 500:
                                    return jsonify({"ok": False, "error": "regex too long (max 500 chars)"}), 400
                                try:
                                    re.compile(new_regex)
                                except re.error as e:
                                    return jsonify({"ok": False, "error": f"invalid regex: {e}"}), 400
                            _PII_CONFIG["patterns"][name][key] = cfg[key]
                    else:
                        if isinstance(cfg, bool):
                            _PII_CONFIG["patterns"][name]["enabled"] = cfg
        if "mask_char" in body:
            mask_char = body["mask_char"]
            if not isinstance(mask_char, str) or len(mask_char) != 1:
                return jsonify({"ok": False, "error": "mask_char must be a single character"}), 400
            _PII_CONFIG["mask_char"] = mask_char
        # Serialize inside the lock so the returned config is a consistent snapshot.
        config_snapshot = copy.deepcopy(_PII_CONFIG)
    return jsonify({"ok": True, "config": config_snapshot})


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

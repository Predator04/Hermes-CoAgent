"""TOTP / 2FA code vault routes.

Endpoints:
  POST /totp/add      - store a TOTP secret {label, secret, issuer?}
  GET  /totp/list     - list stored TOTP labels (never the secrets)
  GET  /totp/code/<label> - current time-based code + seconds remaining
  POST /totp/delete   - remove a stored TOTP secret {label}

Secrets are stored encrypted at rest via the existing vault (routes_vault.py,
backed by Windows Credential Manager / DPAPI). No plaintext secret is ever
written to disk by this module, and the secret is never returned by any
endpoint — only the generated code.

The TOTP implementation is pure Python (RFC 6238 / RFC 4226, HMAC-SHA1,
base32) so it has zero third-party dependencies. Storage is Windows-only
(Credential Manager); on non-Windows hosts the storage endpoints return 501
to keep the Linux syntax-check CI green.
"""

import base64
import hmac
import hashlib
import struct
import time

from flask import jsonify

from shared import _json_body, _log, _missing_field

from routes_vault import (
    CRED_TYPE_GENERIC,
    _WINDOWS,
    _cred_api,
    _delete_credential,
    _enumerate_impl,
    _get_credential,
    _set_credential,
    _windows_only,
)

_TOTP_TARGET_PREFIX = "totp:"
_DEFAULT_PERIOD = 30
_DEFAULT_DIGITS = 6


# ---------------------------------------------------------------------------
# TOTP core (RFC 6238, pure Python)
# ---------------------------------------------------------------------------

def _normalize_secret(secret):
    """Normalize a user-supplied base32 secret: strip spaces/dashes, uppercase,
    and add the = padding that base64.b32decode requires (most authenticator
    apps export secrets unpadded)."""
    s = (secret or "").replace(" ", "").replace("-", "").upper().rstrip("=")
    s += "=" * ((8 - len(s) % 8) % 8)
    return s


def _generate_code(secret, period=_DEFAULT_PERIOD, digits=_DEFAULT_DIGITS):
    """Return (code, seconds_remaining) for the given base32 secret."""
    key = base64.b32decode(_normalize_secret(secret))
    counter = int(time.time() // period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    code = str(binary % (10 ** digits)).zfill(digits)
    remaining = period - (int(time.time()) % period)
    return code, remaining


def _validate_secret(secret):
    """Return (normalized, error). Empty error means valid."""
    if not secret or not isinstance(secret, str):
        return "", "secret is required (base32 string)"
    normalized = _normalize_secret(secret)
    if not normalized:
        return "", "secret is empty"
    try:
        base64.b32decode(normalized)
    except Exception:
        return "", "secret is not valid base32"
    return normalized, ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/totp/add", methods=["POST"])
    @require_auth
    def route_totp_add():
        if not _WINDOWS:
            return _windows_only()
        advapi32, CREDENTIAL, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        d = _json_body()
        if not isinstance(d, dict):
            d = {}
        raw = d.get("label")
        label = raw.strip() if isinstance(raw, str) else ""
        if not label:
            return _missing_field("label")
        normalized, err = _validate_secret(d.get("secret"))
        if err:
            return jsonify({"error": err}), 400
        issuer = str(d.get("issuer") or d.get("account") or "")
        target = _TOTP_TARGET_PREFIX + label
        try:
            _set_credential(advapi32, CREDENTIAL, target, issuer, normalized, CRED_TYPE_GENERIC)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        _log(f"totp/add label={label} (secret not logged)")
        return jsonify({"status": "ok", "label": label, "issuer": issuer})

    @app.route("/totp/list", methods=["GET"])
    @require_auth
    def route_totp_list():
        if not _WINDOWS:
            return _windows_only()
        advapi32, _, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        entries = _enumerate_impl(advapi32)
        if entries is None:
            return jsonify({"error": "CredEnumerateW failed"}), 500
        totp_entries = [
            {
                "label": e["target"][len(_TOTP_TARGET_PREFIX):],
                "issuer": e.get("username") or "",
                "has_secret": e.get("has_secret", False),
            }
            for e in entries
            if e.get("target", "").startswith(_TOTP_TARGET_PREFIX)
        ]
        return jsonify({"status": "ok", "count": len(totp_entries), "totp": totp_entries})

    @app.route("/totp/code/<label>", methods=["GET"])
    @require_auth
    def route_totp_code(label):
        if not _WINDOWS:
            return _windows_only()
        advapi32, CREDENTIAL, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        result = _get_credential(advapi32, CREDENTIAL, _TOTP_TARGET_PREFIX + label)
        if result is None:
            return jsonify({"error": f"totp '{label}' not found"}), 404
        secret = result.get("secret", "")
        normalized, err = _validate_secret(secret)
        if err:
            return jsonify({"error": f"stored secret for '{label}' is invalid: {err}"}), 500
        code, remaining = _generate_code(normalized)
        return jsonify({
            "status": "ok",
            "label": label,
            "issuer": result.get("username") or "",
            "code": code,
            "seconds_remaining": remaining,
            "period": _DEFAULT_PERIOD,
            "digits": _DEFAULT_DIGITS,
        })

    @app.route("/totp/delete", methods=["POST"])
    @require_auth
    def route_totp_delete():
        if not _WINDOWS:
            return _windows_only()
        advapi32, _, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        d = _json_body()
        raw = d.get("label") if isinstance(d, dict) else None
        label = raw.strip() if isinstance(raw, str) else ""
        if not label:
            return _missing_field("label")
        ok = _delete_credential(advapi32, _TOTP_TARGET_PREFIX + label)
        if not ok:
            return jsonify({"error": f"totp '{label}' not found or delete failed"}), 404
        _log(f"totp/delete label={label}")
        return jsonify({"status": "ok", "deleted": label})

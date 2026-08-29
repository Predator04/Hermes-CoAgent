"""Windows Credential Manager vault routes.

Endpoints:
  GET  /vault/list   - list stored credential targets (optionally filter by type)
  POST /vault/get    - read a credential {target} -> username + secret
  POST /vault/set    - write/update {target, username, secret, type}
  POST /vault/delete - remove a credential {target}

Backed by the Windows Credential Manager (advapi32 CredReadW/CredWriteW/
CredEnumerateW/CredDeleteW), which stores secrets encrypted at rest via DPAPI.
No plaintext is ever written to disk by this module. All endpoints are
auth-gated (via require_auth) and Windows-only: on non-Windows hosts they
return HTTP 501, and the ctypes structs are defined only when the platform
supports them so the Linux syntax-check CI stays green.
"""

import os

from flask import jsonify

from shared import _json_body, _log, _missing_field


CRED_TYPE_GENERIC = 1
CRED_TYPE_DOMAIN_PASSWORD = 2
CRED_TYPE_MAP = {
    "generic": CRED_TYPE_GENERIC,
    "domain_password": CRED_TYPE_DOMAIN_PASSWORD,
}
_CRED_TYPE_NAMES = {v: k for k, v in CRED_TYPE_MAP.items()}

_WINDOWS = os.name == "nt"


# ---------------------------------------------------------------------------
# ctypes bindings (Windows only)
# ---------------------------------------------------------------------------

_CRED_API_CACHE = None


def _cred_api():
    """Return (advapi32, CREDENTIAL, CREDENTIAL_ATTRIBUTE) or (None,)*3.

    Memoized so the ctypes Structure classes are created exactly once — the
    Cred*W prototypes bind to a single canonical pointer type, which matters
    because ctypes checks argtypes against the concrete class, not its layout.
    """
    global _CRED_API_CACHE
    if _CRED_API_CACHE is not None:
        return _CRED_API_CACHE
    if not _WINDOWS:
        _CRED_API_CACHE = (None, None, None)
        return _CRED_API_CACHE
    try:
        import ctypes
        from ctypes import wintypes

        class CREDENTIAL_ATTRIBUTE(ctypes.Structure):
            _fields_ = [
                ("Keyword", wintypes.LPWSTR),
                ("Flags", wintypes.DWORD),
                ("ValueSize", wintypes.DWORD),
                ("Value", wintypes.LPBYTE),
            ]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", wintypes.LPBYTE),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTE)),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        PCREDENTIAL = ctypes.POINTER(CREDENTIAL)

        advapi32 = ctypes.windll.advapi32
        advapi32.CredReadW.restype = wintypes.BOOL
        advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(PCREDENTIAL),
        ]
        advapi32.CredWriteW.restype = wintypes.BOOL
        advapi32.CredWriteW.argtypes = [PCREDENTIAL, wintypes.DWORD]
        advapi32.CredDeleteW.restype = wintypes.BOOL
        advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        advapi32.CredEnumerateW.restype = wintypes.BOOL
        advapi32.CredEnumerateW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.POINTER(PCREDENTIAL)),
        ]
        advapi32.CredFree.restype = None
        advapi32.CredFree.argtypes = [ctypes.c_void_p]

        _CRED_API_CACHE = (advapi32, CREDENTIAL, CREDENTIAL_ATTRIBUTE)
    except Exception as exc:
        _log(f"vault: ctypes bindings failed: {exc}")
        _CRED_API_CACHE = (None, None, None)
    return _CRED_API_CACHE


def _windows_only():
    return jsonify({"error": "Windows-only endpoint (Credential Manager unavailable)"}), 501


# ---------------------------------------------------------------------------
# Credential operations
# ---------------------------------------------------------------------------

def _enumerate_impl(advapi32):
    import ctypes
    from ctypes import wintypes
    _, CREDENTIAL, _ = _cred_api()
    PCREDENTIAL = ctypes.POINTER(CREDENTIAL)
    count = wintypes.DWORD(0)
    pcreds = ctypes.POINTER(PCREDENTIAL)()
    ok = advapi32.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(pcreds))
    if not ok:
        return None
    entries = []
    try:
        for i in range(count.value):
            cred = pcreds[i].contents
            target = cred.TargetName or ""
            entries.append({
                "target": target,
                "username": cred.UserName or "",
                "type": _CRED_TYPE_NAMES.get(cred.Type, str(cred.Type)),
                "persist": cred.Persist,
                "has_secret": cred.CredentialBlobSize > 0,
            })
    finally:
        advapi32.CredFree(pcreds)
    return entries


def _get_credential(advapi32, CREDENTIAL, target):
    import ctypes
    from ctypes import wintypes
    PCREDENTIAL = ctypes.POINTER(CREDENTIAL)
    pcred = PCREDENTIAL()
    # Probe generic first, then domain_password.
    for ctype in (CRED_TYPE_GENERIC, CRED_TYPE_DOMAIN_PASSWORD):
        ok = advapi32.CredReadW(target, ctype, 0, ctypes.byref(pcred))
        if ok and pcred:
            cred = pcred.contents
            secret = ""
            if cred.CredentialBlobSize and cred.CredentialBlob:
                try:
                    raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
                    secret = raw.decode("utf-16-le", errors="replace")
                except Exception:
                    secret = ""
            result = {
                "target": cred.TargetName or target,
                "username": cred.UserName or "",
                "type": _CRED_TYPE_NAMES.get(cred.Type, str(cred.Type)),
                "secret": secret,
            }
            advapi32.CredFree(pcred)
            return result
    return None


def _set_credential(advapi32, CREDENTIAL, target, username, secret, ctype):
    import ctypes
    from ctypes import wintypes

    blob = (secret or "").encode("utf-16-le")
    blob_buf = ctypes.create_string_buffer(blob, len(blob))
    user_buf = ctypes.create_unicode_buffer(username or "")

    cred = CREDENTIAL()
    cred.Flags = 0
    cred.Type = ctype
    cred.TargetName = target
    cred.Comment = "Managed by CoAgent vault"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(blob_buf, wintypes.LPBYTE)
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.UserName = ctypes.cast(user_buf, wintypes.LPWSTR)

    ok = advapi32.CredWriteW(ctypes.byref(cred), 0)
    if not ok:
        err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CredWriteW failed (error {err})")
    return True


def _delete_credential(advapi32, target):
    # Try both generic and domain_password; return True if either succeeded.
    ok = False
    for ctype in (CRED_TYPE_GENERIC, CRED_TYPE_DOMAIN_PASSWORD):
        if advapi32.CredDeleteW(target, ctype, 0):
            ok = True
    return ok


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/vault/list", methods=["GET"])
    @require_auth
    def route_vault_list():
        if not _WINDOWS:
            return _windows_only()
        advapi32, _, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        entries = _enumerate_impl(advapi32)
        if entries is None:
            return jsonify({"error": "CredEnumerateW failed"}), 500
        return jsonify({"status": "ok", "count": len(entries), "credentials": entries})

    @app.route("/vault/get", methods=["POST"])
    @require_auth
    def route_vault_get():
        if not _WINDOWS:
            return _windows_only()
        advapi32, CREDENTIAL, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        d = _json_body()
        raw = d.get("target") if isinstance(d, dict) else None
        target = raw.strip() if isinstance(raw, str) else ""
        if not target:
            return _missing_field("target")
        result = _get_credential(advapi32, CREDENTIAL, target)
        if result is None:
            return jsonify({"error": f"credential '{target}' not found"}), 404
        return jsonify({"status": "ok", **result})

    @app.route("/vault/set", methods=["POST"])
    @require_auth
    def route_vault_set():
        if not _WINDOWS:
            return _windows_only()
        advapi32, CREDENTIAL, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        d = _json_body()
        if not isinstance(d, dict):
            d = {}
        raw = d.get("target")
        target = raw.strip() if isinstance(raw, str) else ""
        if not target:
            return _missing_field("target")
        secret = d.get("secret")
        if secret is None:
            return _missing_field("secret")
        username = d.get("username", "")
        type_name = str(d.get("type", "generic")).lower()
        if type_name not in CRED_TYPE_MAP:
            return jsonify({"error": f"unknown credential type '{type_name}' (use 'generic' or 'domain_password')"}), 400
        ctype = CRED_TYPE_MAP[type_name]
        try:
            _set_credential(advapi32, CREDENTIAL, target, username, str(secret), ctype)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        _log(f"vault/set target={target} type={type_name}")
        return jsonify({"status": "ok", "target": target, "type": type_name})

    @app.route("/vault/delete", methods=["POST"])
    @require_auth
    def route_vault_delete():
        if not _WINDOWS:
            return _windows_only()
        advapi32, _, _ = _cred_api()
        if advapi32 is None:
            return _windows_only()
        d = _json_body()
        raw = d.get("target") if isinstance(d, dict) else None
        target = raw.strip() if isinstance(raw, str) else ""
        if not target:
            return _missing_field("target")
        ok = _delete_credential(advapi32, target)
        if not ok:
            return jsonify({"error": f"credential '{target}' not found or delete failed"}), 404
        _log(f"vault/delete target={target}")
        return jsonify({"status": "ok", "deleted": target})

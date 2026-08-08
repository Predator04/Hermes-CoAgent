"""
Hermes CoAgent - Security module
==================================
Token-based Bearer auth for CoAgent HTTP endpoints.
CSRF protection for browser-based requests.

Features:
  --secure            Generates & persists a random 64-char hex token
  --token=KEY         Uses a specific token (or HERMES_COAGENT_TOKEN env var)
  GET /auth/token     Returns current token info (view/regen)
  POST /auth/token    Regenerates token (requires current token)
  GET /csrf-token     Returns a CSRF token for browser forms

Token is saved to COAGENT_DIR/.token on first --secure launch (or when --token=KEY is specified).
Subsequent --secure launches read the saved token.
When HERMES_COAGENT_TOKEN env var is used with --secure, the token is NOT persisted to disk.
"""
import os, sys, secrets, functools, hashlib, time, threading
from flask import jsonify, request

AUTH_TOKEN = None
AUTH_ENABLED = False
_AUTH_LOCK = threading.Lock()
COAGENT_DIR = None

# CSRF token store — maps token_hash -> expiry timestamp
_CSRF_TOKENS: dict[str, float] = {}
_CSRF_LOCK = threading.Lock()
_CSRF_CLEANUP_INTERVAL = 300  # seconds between stale cleanup
_CSRF_TTL = 3600  # 1 hour
_DASHBOARD_HANDOFFS: dict[str, tuple[str, float]] = {}
_DASHBOARD_HANDOFF_LOCK = threading.Lock()
_DASHBOARD_HANDOFF_TTL = 60


def csrf_token_store():
    """Get or initialize the CSRF token store, cleaning stale entries."""
    global _CSRF_TOKENS
    now = time.time()
    with _CSRF_LOCK:
        # Purge stale tokens inline
        stale = [k for k, v in list(_CSRF_TOKENS.items()) if v < now]
        for k in stale:
            _CSRF_TOKENS.pop(k, None)
        token = secrets.token_urlsafe(32)
        _CSRF_TOKENS[hashlib.sha256(token.encode()).hexdigest()] = now + _CSRF_TTL
    return token


def _prune_dashboard_handoffs(now=None):
    now = time.time() if now is None else now
    stale = [code for code, (_token, expires_at) in _DASHBOARD_HANDOFFS.items() if expires_at < now]
    for code in stale:
        _DASHBOARD_HANDOFFS.pop(code, None)


def csrf_check():
    """Check CSRF token from X-CSRF-Token header.

    Atomically pops the token from the store to avoid TOCTOU race where
    two concurrent requests could both pass the same check.
    """
    token = request.headers.get("X-CSRF-Token") or ""
    if not token:
        return False
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    # Atomic check-and-remove: pop returns expiry or None
    with _CSRF_LOCK:
        expiry = _CSRF_TOKENS.pop(token_hash, None)
    return expiry is not None and expiry > time.time()


def csrf_protect(f):
    """Decorator for CSRF-sensitive endpoints. Checks X-CSRF-Token header."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # GET/HEAD/OPTIONS are safe
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return f(*args, **kwargs)
        # Allow Bearer token auth (already protects CSRF)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and AUTH_TOKEN:
            return f(*args, **kwargs)
        # CSRF token check
        if csrf_check():
            return f(*args, **kwargs)
        return jsonify({"error": "CSRF token required or missing. Provide X-CSRF-Token header."}), 403
    return wrapper


def _token_path():
    global COAGENT_DIR
    if COAGENT_DIR:
        return COAGENT_DIR / ".token"
    return None


def _load_token():
    tp = _token_path()
    if tp and tp.exists():
        return tp.read_text(encoding="utf-8").strip()
    return None


def _save_token(token):
    """Persist token to disk atomically to avoid corruption on crash."""
    tp = _token_path()
    if not tp:
        return
    # Write to temp file in same dir, then atomic rename
    tmp = tp.with_suffix(".tmp")
    tmp.write_text(token, encoding="utf-8")
    try:
        if os.name != "nt":
            os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, tp)  # atomic on both Windows and POSIX
    old_suffix = tp.with_suffix(".token_tok")
    if old_suffix.exists():
        old_suffix.unlink()


def generate_token():
    """Generate and persist a new bearer token."""
    token = secrets.token_hex(32)
    _save_token(token)
    return token


def _token_from_password(password):
    salt = secrets.token_hex(16)
    material = f"{salt}:{password}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def init_auth(port=9123, coag_dir=None):
    global AUTH_TOKEN, AUTH_ENABLED, COAGENT_DIR
    COAGENT_DIR = coag_dir
    if COAGENT_DIR:
        old_suffix = COAGENT_DIR / ".token_tok"
        if old_suffix.exists():
            old_suffix.unlink()

    token = None
    token_from_arg = False
    for arg in sys.argv:
        if arg.startswith("--token="):
            token = arg.split("=", 1)[1]
            token_from_arg = bool(token)
            break
    if not token:
        token = os.environ.get("HERMES_COAGENT_TOKEN", "")

    secure = "--secure" in sys.argv
    allow_external = "--allow-external" in sys.argv

    if secure:
        if not token:
            saved = _load_token()
            if saved:
                token = saved
            else:
                token = generate_token()
                print(f"[Auth] Generated token and saved it to {_token_path()}")
        else:
            # Only persist to disk when token came from --token= arg, not env
            if token_from_arg:
                _save_token(token)
            else:
                print(f"[Auth] --secure with env-provided token: not persisting to disk")
        AUTH_ENABLED = True
        AUTH_TOKEN = token
    elif token:
        AUTH_ENABLED = True
        AUTH_TOKEN = token

    # Enforce --allow-external requires --secure
    if allow_external and not (secure and AUTH_ENABLED):
        print("[Auth] FATAL: --allow-external requires --secure. Refusing to start.")
        sys.exit(1)

    if AUTH_ENABLED:
        print("[Auth] Auth enabled")
        return

    print("[Auth] WARNING: No authentication configured!")
    print("[Auth]   Your desktop is controllable by anyone on your network.")
    print("[Auth]   Pass --secure or --token=KEY to enable protection.")
    print("[Auth]   Recommendation: use --secure to generate a random token.")


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not AUTH_ENABLED:
            return f(*args, **kwargs)
        # Fail closed if auth is enabled but token is empty
        if not AUTH_TOKEN:
            return jsonify({"error": "Server auth misconfigured (empty token)"}), 500
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized - provide Bearer token"}), 401
        provided = auth_header[7:]
        if not secrets.compare_digest(provided, AUTH_TOKEN or ""):
            return jsonify({"error": "Invalid token"}), 403
        return f(*args, **kwargs)
    wrapper._hermes_auth_wrapped = True
    return wrapper


def register_auth_routes(app):
    """Register /auth/token endpoints for viewing/regenerating the token."""

    @app.route("/setup-status", methods=["GET"])
    def setup_status():
        configured = bool(_load_token())
        return jsonify({
            "configured": configured,
            "auth": AUTH_ENABLED,
        })

    @app.route("/setup", methods=["POST"])
    def setup_first_boot():
        """Configure the first token from a user-chosen password."""
        global AUTH_TOKEN, AUTH_ENABLED
        # Reject if auth is already enabled (including env-provided tokens)
        if AUTH_ENABLED:
            return jsonify({"error": "Already configured"}), 403
        if _load_token():
            return jsonify({"error": "Already configured"}), 403
        data = request.get_json(silent=True) or {}
        password = data.get("password")
        if not isinstance(password, str) or not password:
            return jsonify({"error": "password is required"}), 400
        token = _token_from_password(password)
        with _AUTH_LOCK:
            # Re-check under lock to prevent TOCTOU race
            if AUTH_ENABLED or _load_token():
                return jsonify({"error": "Already configured"}), 403
            _save_token(token)
            AUTH_TOKEN = token
            AUTH_ENABLED = True
        return jsonify({
            "status": "configured",
            "token": token,
            "message": "Save this token - it won't be shown again",
        })

    @app.route("/auth/token", methods=["GET"])
    @require_auth
    def auth_token_info():
        """Show current token status (never leaks full token)."""
        if not AUTH_ENABLED:
            return jsonify({"auth": False, "message": "Auth not enabled"})
        pre = AUTH_TOKEN[:16]
        suf = AUTH_TOKEN[-8:]
        return jsonify({
            "auth": True,
            "token_preview": f"{pre}...{suf}",
            "saved": _token_path().exists() if _token_path() else False,
        })


    @app.route('/auth/token/show', methods=['GET'])
    @require_auth
    def auth_token_show():
        """Return full token (requires auth). Use sparingly — leaks full token in response."""
        if not AUTH_ENABLED:
            return jsonify({'error': 'Auth not enabled'}), 400
        with _AUTH_LOCK:
            token = AUTH_TOKEN
        if not token:
            return jsonify({'error': 'No token set'}), 500
        return jsonify({
            'auth': True,
            'token': token,
        })

    @app.route('/auth/token/reset', methods=['POST'])
    @require_auth
    def auth_token_reset():
        """Reset token from saved file. Requires current bearer token."""
        global AUTH_TOKEN, AUTH_ENABLED
        if not AUTH_ENABLED or not AUTH_TOKEN:
            return jsonify({'error': 'Auth not enabled'}), 400
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized - provide Bearer token'}), 401
        provided = auth_header[7:]
        if not secrets.compare_digest(provided, AUTH_TOKEN):
            return jsonify({'error': 'Invalid token'}), 403
        tp = _token_path()
        if not tp or not tp.exists():
            return jsonify({'error': 'No saved token file found'}), 404
        saved = tp.read_text(encoding='utf-8').strip()
        if saved:
            AUTH_TOKEN = saved
            AUTH_ENABLED = True
            pre = saved[:16]
            suf = saved[-8:]
            return jsonify({
                'message': 'Token reset from saved file',
                'token_preview': f'{pre}...{suf}',
            })
        return jsonify({'error': 'Token file is empty'}), 500

    @app.route("/auth/token", methods=["POST"])
    @require_auth
    def auth_token_regen():
        """Regenerate token. Requires current token in Authorization header."""
        global AUTH_TOKEN
        if not AUTH_ENABLED:
            return jsonify({"error": "Auth not enabled"}), 400
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Provide current token to regenerate"}), 401
        provided = auth_header[7:]
        if not secrets.compare_digest(provided, AUTH_TOKEN):
            return jsonify({"error": "Invalid token"}), 403

        new_token = secrets.token_hex(32)
        with _AUTH_LOCK:
            AUTH_TOKEN = new_token
        _save_token(new_token)

        pre = new_token[:16]
        suf = new_token[-8:]
        return jsonify({
            "message": "Token regenerated successfully",
            "token": new_token,
            "token_preview": f"{pre}...{suf}",
        })

    @app.route("/auth/dashboard-handoff", methods=["POST"])
    @require_auth
    def auth_dashboard_handoff_create():
        """Create a short-lived one-time dashboard token handoff code."""
        if not AUTH_ENABLED or not AUTH_TOKEN:
            return jsonify({"error": "Auth not enabled"}), 400
        now = time.time()
        code = secrets.token_urlsafe(24)
        with _DASHBOARD_HANDOFF_LOCK:
            _prune_dashboard_handoffs(now)
            _DASHBOARD_HANDOFFS[code] = (AUTH_TOKEN, now + _DASHBOARD_HANDOFF_TTL)
        return jsonify({"code": code, "expires_in": _DASHBOARD_HANDOFF_TTL})

    @app.route("/auth/dashboard-handoff/exchange", methods=["POST"])
    def auth_dashboard_handoff_exchange():
        """Exchange a dashboard handoff code once, then discard it."""
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "").strip()
        if not code:
            return jsonify({"error": "code is required"}), 400
        now = time.time()
        with _DASHBOARD_HANDOFF_LOCK:
            _prune_dashboard_handoffs(now)
            entry = _DASHBOARD_HANDOFFS.pop(code, None)
        if not entry:
            return jsonify({"error": "Invalid or expired handoff code"}), 404
        token, expires_at = entry
        if expires_at < now:
            return jsonify({"error": "Invalid or expired handoff code"}), 404
        return jsonify({"token": token})

    @app.route("/csrf-token", methods=["GET"])
    @require_auth
    def route_csrf_token():
        """Return a CSRF token for browser-based form submissions."""
        token = csrf_token_store()
        return jsonify({"csrf_token": token})

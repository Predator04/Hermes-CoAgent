"""
Hermes CoAgent - Security module
==================================
Token-based Bearer auth for CoAgent HTTP endpoints.

Features:
  --secure            Generates & persists a random 64-char hex token
  --token=KEY         Uses a specific token (or HERMES_COAGENT_TOKEN env var)
  GET /auth/token     Returns current token info (view/regen)
  POST /auth/token    Regenerates token (requires current token)

Token is saved to COAGENT_DIR/.token on first --secure launch.
Subsequent --secure launches read the saved token.
"""
import os, sys, secrets, functools, hashlib
from flask import request, jsonify
from pathlib import Path

AUTH_TOKEN = None
AUTH_ENABLED = False
SETUP_REQUIRED = False
COAGENT_DIR = None


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
    tp = _token_path()
    if tp:
        tp.write_text(token, encoding="utf-8")
        try:
            os.chmod(tp, 0o600)
        except OSError:
            pass
        old_suffix = tp.with_suffix(".token_tok")
        if old_suffix.exists():
            old_suffix.unlink()


def _token_from_password(password):
    salt = secrets.token_hex(16)
    material = f"{salt}:{password}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def init_auth(port=9123, coag_dir=None):
    global AUTH_TOKEN, AUTH_ENABLED, SETUP_REQUIRED, COAGENT_DIR
    COAGENT_DIR = coag_dir
    SETUP_REQUIRED = False
    if COAGENT_DIR:
        old_suffix = COAGENT_DIR / ".token_tok"
        if old_suffix.exists():
            old_suffix.unlink()

    token = None
    for arg in sys.argv:
        if arg.startswith("--token="):
            token = arg.split("=", 1)[1]
            break
    if not token:
        token = os.environ.get("HERMES_COAGENT_TOKEN", "")

    if "--secure" in sys.argv:
        if not token:
            saved = _load_token()
            if saved:
                token = saved
            else:
                SETUP_REQUIRED = True
                AUTH_ENABLED = False
                AUTH_TOKEN = None
                print("[Auth] First time? POST /setup with {'password':'yourpassword'}")
                return
        else:
            _save_token(token)
        AUTH_ENABLED = True
        AUTH_TOKEN = token
    elif token:
        AUTH_ENABLED = True
        AUTH_TOKEN = token

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
            if SETUP_REQUIRED:
                return jsonify({"error": "Setup required", "setup": "/setup"}), 403
            return f(*args, **kwargs)
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
            "setup_required": SETUP_REQUIRED,
        })

    @app.route("/setup", methods=["POST"])
    def setup_first_boot():
        """Configure the first token from a user-chosen password."""
        global AUTH_TOKEN, AUTH_ENABLED, SETUP_REQUIRED
        if _load_token():
            return jsonify({"error": "Already configured"}), 403
        data = request.get_json(silent=True) or {}
        password = data.get("password")
        if not isinstance(password, str) or not password:
            return jsonify({"error": "password is required"}), 400
        token = _token_from_password(password)
        _save_token(token)
        AUTH_TOKEN = token
        AUTH_ENABLED = True
        SETUP_REQUIRED = False
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
    def auth_token_show():
        """Return full token (requires auth)."""
        global AUTH_TOKEN
        if not AUTH_ENABLED or not AUTH_TOKEN:
            return jsonify({'error': 'Auth not enabled'}), 400
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized - provide Bearer token'}), 401
        provided = auth_header[7:]
        if not secrets.compare_digest(provided, AUTH_TOKEN):
            return jsonify({'error': 'Invalid token'}), 403
        return jsonify({
            'auth': True,
            'token': AUTH_TOKEN,
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
        AUTH_TOKEN = new_token
        _save_token(new_token)

        pre = new_token[:16]
        suf = new_token[-8:]
        return jsonify({
            "message": "Token regenerated successfully",
            "token": new_token,
            "token_preview": f"{pre}...{suf}",
        })

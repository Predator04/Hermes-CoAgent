"""Google Workspace routes using the Google API Python client."""

import base64
import os
import threading
from datetime import datetime, timezone
from email.mime.text import MIMEText

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import COAGENT_DIR, _log, _wrap_registered_blueprint_routes


google_bp = Blueprint("google", __name__)
_CREDENTIALS_LOCK = threading.Lock()
_CREDENTIALS_CACHE = None

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]
CREDENTIALS_FILE = COAGENT_DIR / "google_credentials.json"
TOKEN_FILE = COAGENT_DIR / "google_token.json"


def _error(message: str, status: int = 400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _not_configured(detail=None):
    payload = {
        "error": "Google Workspace not configured",
        "instructions": (
            f"Place OAuth client credentials at {CREDENTIALS_FILE}, then call a Google endpoint "
            f"to complete OAuth. Tokens are stored at {TOKEN_FILE}."
        ),
    }
    if detail:
        payload["detail"] = str(detail)[:500]
    return jsonify(payload), 501


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def _load_google_libs():
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        return GoogleRequest, Credentials, InstalledAppFlow, build, None
    except ImportError as e:
        return None, None, None, None, _not_configured(
            f"Missing Google dependency: {e}. Install google-api-python-client google-auth-oauthlib google-auth-httplib2."
        )


def _save_oauth_token(creds):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = TOKEN_FILE.with_suffix(".tmp")
    data = creds.to_json()
    try:
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(str(tmp_path), str(TOKEN_FILE))
    except OSError:
        # Fallback: write directly, still with restrictive permissions (never world-readable).
        try:
            fd = os.open(str(TOKEN_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
        except OSError:
            pass
    finally:
        # Always clean up the temp file (also covers non-OSError exceptions).
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    _log("OAuth token saved with restricted permissions")


def _credentials():
    global _CREDENTIALS_CACHE
    if not CREDENTIALS_FILE.exists():
        return None, _not_configured("google_credentials.json not found")
    GoogleRequest, Credentials, InstalledAppFlow, _build, missing = _load_google_libs()
    if missing:
        return None, missing
    with _CREDENTIALS_LOCK:
        if _CREDENTIALS_CACHE is not None:
            creds = _CREDENTIALS_CACHE
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(GoogleRequest())
                    _save_oauth_token(creds)
                except Exception:
                    _CREDENTIALS_CACHE = None
                    return None, _not_configured("token refresh failed — re-auth required")
            if creds and creds.valid:
                return creds, None
        try:
            creds = None
            if TOKEN_FILE.exists():
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(GoogleRequest())
            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(host="127.0.0.1", port=0)
            _save_oauth_token(creds)
            _CREDENTIALS_CACHE = creds
            return creds, None
        except Exception as e:
            _CREDENTIALS_CACHE = None
            return None, _not_configured(e)


def _service(name, version):
    creds, error = _credentials()
    if error:
        return None, error
    _GoogleRequest, _Credentials, _Flow, build, missing = _load_google_libs()
    if missing:
        return None, missing
    try:
        return build(name, version, credentials=creds), None
    except Exception as e:
        return None, _not_configured(e)


def _clamp_int(value, default, minimum, maximum):
    try:
        number = int(value if value is not None else default)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _header(headers, name):
    wanted = name.lower()
    for item in headers:
        if item.get("name", "").lower() == wanted:
            return item.get("value", "")
    return ""


@google_bp.route("/google", methods=["GET"])
def route_google_index():
    return jsonify({
        "configured": CREDENTIALS_FILE.exists(),
        "credentials_file": str(CREDENTIALS_FILE),
        "token_file": str(TOKEN_FILE),
        "endpoints": [
            {"path": "/google", "method": "GET", "desc": "List Google endpoints"},
            {"path": "/google/gmail/list", "method": "POST", "desc": "List recent Gmail messages"},
            {"path": "/google/gmail/send", "method": "POST", "desc": "Send Gmail message"},
            {"path": "/google/calendar/events", "method": "POST", "desc": "List calendar events"},
            {"path": "/google/calendar/create", "method": "POST", "desc": "Create calendar event"},
        ],
    })


@google_bp.route("/google/gmail/list", methods=["POST"])
def route_google_gmail_list():
    service, error = _service("gmail", "v1")
    if error:
        return error
    data = _json_payload()
    max_results = _clamp_int(data.get("max_results"), 10, 1, 100)
    query = data.get("query")
    try:
        request = service.users().messages().list(userId="me", maxResults=max_results, q=query)
        result = request.execute()
        messages = []
        for item in result.get("messages", []):
            msg = service.users().messages().get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = msg.get("payload", {}).get("headers", [])
            messages.append({
                "id": msg.get("id"),
                "thread_id": msg.get("threadId"),
                "from": _header(headers, "From"),
                "subject": _header(headers, "Subject"),
                "date": _header(headers, "Date"),
                "snippet": msg.get("snippet", ""),
            })
        return jsonify({"messages": messages, "count": len(messages), "query": query})
    except Exception as e:
        return _not_configured(e)


@google_bp.route("/google/gmail/send", methods=["POST"])
def route_google_gmail_send():
    service, error = _service("gmail", "v1")
    if error:
        return error
    data = _json_payload()
    to_addr = data.get("to")
    subject = data.get("subject")
    body = data.get("body")
    if not isinstance(to_addr, str) or not to_addr:
        return _error("to is required")
    if not isinstance(subject, str):
        return _error("subject is required")
    if not isinstance(body, str):
        return _error("body is required")
    try:
        message = MIMEText(body)
        message["to"] = to_addr
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return jsonify({"status": "sent", "id": sent.get("id"), "thread_id": sent.get("threadId")})
    except Exception as e:
        return _not_configured(e)


@google_bp.route("/google/calendar/events", methods=["POST"])
def route_google_calendar_events():
    service, error = _service("calendar", "v3")
    if error:
        return error
    data = _json_payload()
    max_results = _clamp_int(data.get("max_results"), 10, 1, 100)
    time_min = data.get("time_min")
    if not isinstance(time_min, str) or not time_min:
        time_min = datetime.now(timezone.utc).isoformat()
    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return jsonify({"events": result.get("items", []), "count": len(result.get("items", []))})
    except Exception as e:
        return _not_configured(e)


@google_bp.route("/google/calendar/create", methods=["POST"])
def route_google_calendar_create():
    service, error = _service("calendar", "v3")
    if error:
        return error
    data = _json_payload()
    summary = data.get("summary")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    description = data.get("description", "")
    if not isinstance(summary, str) or not summary:
        return _error("summary is required")
    if not isinstance(start_time, str) or not start_time:
        return _error("start_time is required")
    if not isinstance(end_time, str) or not end_time:
        return _error("end_time is required")
    if not isinstance(description, str):
        return _error("description must be a string")
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
    }
    try:
        created = service.events().insert(calendarId="primary", body=event).execute()
        return jsonify({"status": "created", "event": created})
    except Exception as e:
        return _not_configured(e)


def register_routes(app, state, require_auth):
    app.register_blueprint(google_bp)
    _wrap_registered_blueprint_routes(app, google_bp.name, require_auth)

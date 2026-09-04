"""Provider-agnostic email (SMTP/IMAP) — issue #1356.

Send and receive email for ANY mailbox over standard SMTP/IMAP — custom
domains, transactional relays, Yahoo, Zoho, on-prem Exchange — independent of
the Gmail OAuth bridge (/google) and the Outlook COM automation (#972).

Endpoints:
    POST   /email/accounts   — register/update a mailbox config
    GET    /email/accounts   — list accounts (passwords masked)
    DELETE /email/accounts   — remove an account
    POST   /email/send       — SMTP send (to/cc/bcc, subject, plain/HTML body,
                               attachments, {placeholders} templating)
    POST   /email/receive    — IMAP fetch messages from a folder
    GET    /email/folders    — list IMAP folders for an account

Security: passwords are encrypted at rest with Windows DPAPI (CryptProtectData,
bound to the running user) and stored in <COAGENT_DIR>/email_accounts.json.
Non-Windows hosts get a clear error. Stdlib only (smtplib / imaplib / email).
"""

import base64
import imaplib
import json
import os
import smtplib
import threading
import traceback
from email import encoders
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.policy import default as email_policy
from email.utils import formataddr, getaddresses

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log, _missing_field

_IS_WINDOWS = os.name == "nt"
_STORE_PATH = os.path.join(str(COAGENT_DIR), "email_accounts.json")
_LOCK = threading.Lock()


# ── DPAPI at-rest encryption (Windows only) ───────────────────────────────
def _dpapi_blob(data):
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))


def _dpapi_encrypt(plaintext):
    import ctypes
    in_blob = _dpapi_blob(plaintext.encode("utf-16le"))
    out_blob = type(in_blob)()  # NULL-initialized; the API allocates the output
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), "CoAgent Email", None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptProtectData failed")
    enc = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return base64.b64encode(enc).decode("ascii")


def _dpapi_decrypt(payload):
    import ctypes
    raw = base64.b64decode(payload)
    in_blob = _dpapi_blob(raw)
    out_blob = type(in_blob)()  # NULL-initialized; the API allocates the output
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("CryptUnprotectData failed")
    plain = ctypes.wstring_at(out_blob.pbData, out_blob.cbData // 2)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return plain


# ── Account store ─────────────────────────────────────────────────────────
def _load_accounts():
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        accounts = data.get("accounts") if isinstance(data, dict) else None
        return accounts if isinstance(accounts, list) else []
    except FileNotFoundError:
        return []
    except Exception as exc:
        _log(f"email: failed to load accounts: {type(exc).__name__}: {exc}")
        return []


def _save_accounts(accounts):
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"accounts": accounts}, fh, indent=2)
    os.replace(tmp, _STORE_PATH)


def _decrypt_password(acct):
    enc = acct.get("password_enc") or ""
    if not enc:
        return ""
    if not _IS_WINDOWS:
        raise OSError("DPAPI requires Windows; passwords cannot be decrypted here")
    return _dpapi_decrypt(enc)


def _find_account(accounts, account_id):
    for acct in accounts:
        if acct.get("id") == account_id:
            return acct
    return None


# ── Message building / parsing ────────────────────────────────────────────
def _apply_placeholders(text, placeholders):
    if not text or not isinstance(placeholders, dict):
        return text
    try:
        return text.format_map(_SafeDict(placeholders))
    except Exception:
        # Leave unknown/missing placeholders literally rather than failing the send.
        for key, value in placeholders.items():
            text = text.replace("{" + key + "}", str(value))
        return text


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _coerce_recipients(value):
    if isinstance(value, str):
        return [r.strip() for r in value.split(",") if r.strip()]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_coerce_recipients(item))
        return out
    return []


def _add_attachment(msg, att):
    name = att.get("name") or att.get("filename") or "attachment"
    content_type = att.get("content_type") or "application/octet-stream"
    data_b64 = att.get("data") or att.get("content") or ""
    path = att.get("path") or ""

    if data_b64:
        try:
            payload = base64.b64decode(data_b64)
        except Exception as exc:
            raise ValueError(f"attachment '{name}': invalid base64: {exc}")
    elif path:
        with open(path, "rb") as fh:
            payload = fh.read()
    else:
        raise ValueError(f"attachment '{name}' has neither data nor path")

    maintype, subtype = (content_type.split("/", 1) + ["octet-stream"])[:2]
    part = MIMEBase(maintype, subtype)
    part.set_payload(payload)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", name))
    msg.attach(part)


def _build_message(d, acct):
    subject = _apply_placeholders(d.get("subject") or "", d.get("placeholders"))
    body = _apply_placeholders(d.get("body") or d.get("text") or "", d.get("placeholders"))
    html = _apply_placeholders(d.get("html") or "", d.get("placeholders"))
    attachments = d.get("attachments") or []

    from_addr = d.get("from") or acct.get("from_addr") or acct.get("username") or ""
    from_name = d.get("from_name") or acct.get("from_name") or ""
    sender = formataddr((from_name, from_addr)) if from_name else from_addr

    if attachments:
        root = MIMEMultipart("mixed")
        if html:
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(body or " ", "plain", "utf-8"))
            alt.attach(MIMEText(html, "html", "utf-8"))
        else:
            alt = MIMEText(body or " ", "plain", "utf-8")
        root.attach(alt)
        for att in attachments:
            _add_attachment(root, att)
        msg = root
    elif html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body or " ", "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(body or " ", "plain", "utf-8")

    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(_coerce_recipients(d.get("to")))
    cc = _coerce_recipients(d.get("cc"))
    bcc = _coerce_recipients(d.get("bcc"))
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    return msg


def _header_text(value):
    if value is None:
        return ""
    try:
        parts = decode_header(value)
        chunks = []
        for raw, charset in parts:
            if isinstance(raw, bytes):
                chunks.append(raw.decode(charset or "utf-8", "replace"))
            else:
                chunks.append(str(raw))
        return " ".join(chunks)
    except Exception:
        return str(value)


def _parse_message(raw_bytes):
    msg = BytesParser(policy=email_policy).parsebytes(raw_bytes)
    text_parts = []
    html_parts = []
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            filename = part.get_filename()
            if disposition.startswith("attachment") or (filename and ctype != "message/rfc822"):
                payload = part.get_payload(decode=True)
                attachments.append({
                    "filename": filename or "attachment",
                    "content_type": ctype,
                    "size": len(payload) if payload else 0,
                    "data": base64.b64encode(payload or b"").decode("ascii"),
                })
            elif ctype == "text/plain":
                text_parts.append(part.get_content())
            elif ctype == "text/html":
                html_parts.append(part.get_content())
    else:
        if msg.get_content_type() == "text/html":
            html_parts.append(msg.get_content())
        else:
            text_parts.append(msg.get_content())

    return {
        "subject": _header_text(msg.get("Subject")),
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "cc": msg.get("Cc", ""),
        "date": msg.get("Date", ""),
        "message_id": msg.get("Message-ID", ""),
        "text": "\n\n".join(t for t in text_parts if t).strip(),
        "html": "\n\n".join(h for h in html_parts if h).strip(),
        "attachments": attachments,
    }


def _send_via_smtp(acct, msg):
    host = acct.get("smtp_host") or acct.get("host") or ""
    port = int(acct.get("smtp_port") or acct.get("port") or 587)
    use_ssl = bool(acct.get("smtp_ssl"))
    starttls = bool(acct.get("starttls", True))
    username = acct.get("username") or ""
    password = _decrypt_password(acct)

    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    try:
        server.ehlo()
        if starttls and not use_ssl:
            server.starttls()
            server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(msg)
        return True
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _receive_via_imap(acct, folder, search, limit, mark_read):
    host = acct.get("imap_host") or acct.get("host") or ""
    port = int(acct.get("imap_port") or acct.get("port") or 993)
    use_ssl = bool(acct.get("imap_ssl", True))
    username = acct.get("username") or ""
    password = _decrypt_password(acct)

    cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    mbox = cls(host, port)
    try:
        mbox.login(username, password)
        folder = folder or "INBOX"
        criteria = search or "ALL"
        for val in (folder, criteria):
            if any(ch in val for ch in ("\r", "\n", "\x00")):
                return {"error": "invalid control characters in IMAP argument"}
        mbox.select(folder, readonly=not mark_read)
        typ, data = mbox.search(None, criteria)
        if typ != "OK":
            return {"error": f"IMAP search failed: {data}"}
        ids = data[0].split()
        # Newest first, capped; clamp negative/zero and oversized limits.
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 20
        ids = ids[-limit:]
        messages = []
        for num in reversed(ids):
            try:
                typ, msg_data = mbox.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                messages.append(_parse_message(raw))
            except Exception as exc:
                _log(f"email: failed to fetch message {num}: {type(exc).__name__}: {exc}")
        return {"count": len(messages), "messages": messages}
    finally:
        try:
            mbox.logout()
        except Exception:
            pass


def _list_folders(acct):
    host = acct.get("imap_host") or acct.get("host") or ""
    port = int(acct.get("imap_port") or acct.get("port") or 993)
    use_ssl = bool(acct.get("imap_ssl", True))
    username = acct.get("username") or ""
    password = _decrypt_password(acct)

    cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    mbox = cls(host, port)
    try:
        mbox.login(username, password)
        typ, boxes = mbox.list()
        folders = []
        for box in boxes or []:
            raw = box.decode("utf-8", "replace") if isinstance(box, bytes) else str(box)
            # IMAP LIST lines look like: (\HasNoChildren) "/" "INBOX.Sent"
            parts = raw.split('"')
            if len(parts) >= 3:
                folders.append(parts[-2])
        return folders
    finally:
        try:
            mbox.logout()
        except Exception:
            pass


# ── Routes ────────────────────────────────────────────────────────────────
def register_routes(app, state, require_auth):

    @app.route("/email/accounts", methods=["POST"])
    @require_auth
    def route_email_accounts_create():
        d = _json_body()
        acct_id = (d.get("id") or d.get("name") or "").strip()
        if not acct_id:
            return _missing_field("id")
        if not _IS_WINDOWS:
            return jsonify({"error": "DPAPI credential encryption requires Windows"}), 400

        password = d.get("password") or ""
        entry = {
            "id": acct_id,
            "name": d.get("name") or acct_id,
            "smtp_host": (d.get("smtp_host") or d.get("host") or "").strip(),
            "smtp_port": d.get("smtp_port") or d.get("port") or 587,
            "smtp_ssl": bool(d.get("smtp_ssl")),
            "starttls": bool(d.get("starttls", True)),
            "imap_host": (d.get("imap_host") or "").strip(),
            "imap_port": d.get("imap_port") or d.get("port") or 993,
            "imap_ssl": bool(d.get("imap_ssl", True)),
            "username": (d.get("username") or "").strip(),
            "from_addr": (d.get("from_addr") or d.get("username") or "").strip(),
            "from_name": (d.get("from_name") or "").strip(),
        }
        if password:
            entry["password_enc"] = _dpapi_encrypt(password)

        with _LOCK:
            accounts = _load_accounts()
            existing = _find_account(accounts, acct_id)
            if existing:
                accounts.remove(existing)
            accounts.append(entry)
            _save_accounts(accounts)
        return jsonify({"status": "ok", "id": acct_id, "created": existing is None})

    @app.route("/email/accounts", methods=["GET"])
    @require_auth
    def route_email_accounts_list():
        accounts = _load_accounts()
        safe = []
        for acct in accounts:
            copy = dict(acct)
            copy["password_enc"] = "•••" if copy.get("password_enc") else ""
            safe.append(copy)
        return jsonify({"status": "ok", "count": len(safe), "accounts": safe})

    @app.route("/email/accounts", methods=["DELETE"])
    @require_auth
    def route_email_accounts_delete():
        d = _json_body()
        acct_id = (d.get("id") or "").strip()
        if not acct_id:
            return _missing_field("id")
        with _LOCK:
            accounts = _load_accounts()
            existing = _find_account(accounts, acct_id)
            if existing:
                accounts.remove(existing)
                _save_accounts(accounts)
                return jsonify({"status": "ok", "id": acct_id, "deleted": True})
        return jsonify({"error": f"account '{acct_id}' not found"}), 404

    @app.route("/email/send", methods=["POST"])
    @require_auth
    def route_email_send():
        d = _json_body()
        acct_id = (d.get("account") or d.get("id") or "").strip()
        if not acct_id:
            return _missing_field("account")
        to = _coerce_recipients(d.get("to"))
        if not to:
            return _missing_field("to")
        if not (d.get("subject") or d.get("body") or d.get("text") or d.get("html")):
            return jsonify({"error": "Missing required field: subject or body"}), 400

        with _LOCK:
            accounts = _load_accounts()
        acct = _find_account(accounts, acct_id)
        if not acct:
            return jsonify({"error": f"account '{acct_id}' not found"}), 404
        if not (acct.get("smtp_host") or acct.get("host")):
            return jsonify({"error": "account has no smtp_host"}), 400

        try:
            msg = _build_message(d, acct)
            _send_via_smtp(acct, msg)
            return jsonify({"status": "ok", "to": to, "cc": _coerce_recipients(d.get("cc")),
                            "bcc": _coerce_recipients(d.get("bcc")), "account": acct_id})
        except Exception as exc:
            _log(f"email send failed: {type(exc).__name__}: {exc}")
            return jsonify({"error": f"SMTP send failed: {type(exc).__name__}: {exc}"}), 502

    @app.route("/email/receive", methods=["POST"])
    @require_auth
    def route_email_receive():
        d = _json_body()
        acct_id = (d.get("account") or d.get("id") or "").strip()
        if not acct_id:
            return _missing_field("account")
        with _LOCK:
            accounts = _load_accounts()
        acct = _find_account(accounts, acct_id)
        if not acct:
            return jsonify({"error": f"account '{acct_id}' not found"}), 404
        if not (acct.get("imap_host") or acct.get("host")):
            return jsonify({"error": "account has no imap_host"}), 400

        try:
            result = _receive_via_imap(
                acct,
                folder=d.get("folder") or "INBOX",
                search=d.get("search"),
                limit=int(d.get("limit") or 20),
                mark_read=bool(d.get("mark_read")),
            )
            if isinstance(result, dict) and result.get("error"):
                return jsonify(result), 502
            return jsonify({"status": "ok", "account": acct_id, **result})
        except Exception as exc:
            _log(f"email receive failed: {type(exc).__name__}: {exc}")
            return jsonify({"error": f"IMAP receive failed: {type(exc).__name__}: {exc}"}), 502

    @app.route("/email/folders", methods=["POST"])
    @require_auth
    def route_email_folders():
        d = _json_body()
        acct_id = (d.get("account") or d.get("id") or "").strip()
        if not acct_id:
            return _missing_field("account")
        with _LOCK:
            accounts = _load_accounts()
        acct = _find_account(accounts, acct_id)
        if not acct:
            return jsonify({"error": f"account '{acct_id}' not found"}), 404
        try:
            folders = _list_folders(acct)
            return jsonify({"status": "ok", "account": acct_id, "folders": folders})
        except Exception as exc:
            return jsonify({"error": f"IMAP folders failed: {type(exc).__name__}: {exc}"}), 502

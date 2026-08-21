"""Obsidian vault bridge routes."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import jsonify

from shared import _json_body


DEFAULT_VAULT = os.path.join(
    os.environ.get("USERPROFILE") or os.environ.get("HOME") or "C:\\Users\\Default",
    "Desktop",
    "Obsidian",
)
REST_URL = os.environ.get("OBSIDIAN_REST_URL", "http://127.0.0.1:27123").rstrip("/")
REST_TOKEN = os.environ.get("OBSIDIAN_REST_API_KEY", "")


def _vault():
    return Path(os.environ.get("OBSIDIAN_VAULT", DEFAULT_VAULT)).expanduser().resolve()


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _inside_vault(path):
    vault = _vault()
    try:
        path.resolve().relative_to(vault)
        return True
    except ValueError:
        return False


def _normalize_note_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("note is required")
    name = name.strip().replace("\\", "/").lstrip("/")
    if not name.lower().endswith(".md"):
        name += ".md"
    if ".." in Path(name).parts:
        raise ValueError("note path may not contain ..")
    return name


def _resolve_note(name, must_exist=False):
    vault = _vault()
    note = _normalize_note_name(name)
    direct = (vault / note).resolve()
    if not _inside_vault(direct):
        raise ValueError("note path escapes vault")
    if direct.exists():
        return direct
    if not must_exist:
        return direct
    # Fallback: case-insensitive search within vault
    note_path = Path(note)
    wanted_name = note_path.name.lower()
    has_dir = len(note_path.parts) > 1
    wanted_rel = note.lower().replace("\\", "/")
    for path in vault.rglob("*.md"):
        if path.name.lower() != wanted_name:
            continue
        resolved = path.resolve()
        if not _inside_vault(resolved):
            continue  # skip symlinks escaping vault
        if has_dir:
            rel = resolved.relative_to(vault).as_posix().lower()
            if rel != wanted_rel:
                continue
        return resolved
    raise FileNotFoundError(note)


def _rest_request(method, path, body=None, timeout=3):
    url = REST_URL + path
    data = None
    headers = {"Accept": "application/json"}
    if REST_TOKEN:
        headers["Authorization"] = f"Bearer {REST_TOKEN}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "body": parsed}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "body": e.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}"}


def _coerce_int(value, default, lo, hi):
    try:
        n = int(value or default)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(n, hi))


def _note_record(path):
    stat = path.stat()
    return {
        "name": path.stem,
        "path": str(path),
        "relative": str(path.resolve().relative_to(_vault())).replace("\\", "/"),
        "bytes": stat.st_size,
        "mtime": stat.st_mtime,
    }


def register_routes(app, state, require_auth):
    @app.route("/obsidian/list", methods=["POST", "GET"])
    @require_auth
    def route_obsidian_list():
        data = _json_body()
        vault = _vault()
        if not vault.exists():
            return _error("vault not found", 404, vault=str(vault))
        limit = _coerce_int(data.get("limit", 1000), 1000, 1, 10000)
        notes = [_note_record(path) for path in sorted(vault.rglob("*.md"))[:limit]]
        return jsonify({"vault": str(vault), "notes": notes, "count": len(notes)})

    @app.route("/obsidian/search", methods=["POST"])
    @require_auth
    def route_obsidian_search():
        data = _json_body()
        query = data.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return _error("query is required")
        if data.get("rest"):
            rest = _rest_request("POST", "/search/simple/", {"query": query, "contextLength": _coerce_int(data.get("context", 120), 120, 1, 100000)})
            if rest.get("ok"):
                return jsonify({"source": "rest", "rest": rest})
        vault = _vault()
        if not vault.exists():
            return _error("vault not found", 404, vault=str(vault))
        needle = query.lower()
        limit = _coerce_int(data.get("limit", 100), 100, 1, 1000)
        matches = []
        for path in sorted(vault.rglob("*.md")):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for idx, line in enumerate(lines, start=1):
                if needle in line.lower():
                    matches.append({
                        "note": path.stem,
                        "relative": str(path.resolve().relative_to(vault)).replace("\\", "/"),
                        "line": idx,
                        "preview": line[:300],
                    })
                    if len(matches) >= limit:
                        return jsonify({"source": "vault", "vault": str(vault), "matches": matches, "count": len(matches)})
        return jsonify({"source": "vault", "vault": str(vault), "matches": matches, "count": len(matches)})

    @app.route("/obsidian/read", methods=["POST"])
    @require_auth
    def route_obsidian_read():
        data = _json_body()
        try:
            path = _resolve_note(data.get("note") or data.get("name") or data.get("path"), must_exist=True)
        except FileNotFoundError as e:
            return _error("note not found", 404, note=str(e))
        except ValueError as e:
            return _error(str(e))
        content = path.read_text(encoding="utf-8", errors="replace")
        return jsonify({"note": path.stem, "path": str(path), "relative": str(path.relative_to(_vault())).replace("\\", "/"), "content": content})

    @app.route("/obsidian/write", methods=["POST"])
    @require_auth
    def route_obsidian_write():
        data = _json_body()
        content = data.get("content")
        if not isinstance(content, str):
            return _error("content must be a string")
        try:
            path = _resolve_note(data.get("note") or data.get("name") or data.get("path"), must_exist=False)
        except ValueError as e:
            return _error(str(e))
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = str(data.get("mode", "overwrite") or "overwrite").strip().lower()
        if mode not in ("append", "overwrite"):
            return _error("mode must be 'append' or 'overwrite'")
        if mode == "append" and path.exists():
            with path.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            path.write_text(content, encoding="utf-8")
        return jsonify({"status": "written", "note": path.stem, "path": str(path), "bytes": path.stat().st_size})

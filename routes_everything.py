"""Instant whole-disk filename search via Everything (es.exe).

Endpoint:
  GET/POST /search/everything - filename search across all local drives.

Primary backend is voidtools' Everything command-line client (es.exe), which
returns results in a few milliseconds by querying the resident NTFS index.
When es.exe is not installed we fall back to the Windows Search index via
the Search.CollatorDSO OLE DB provider (ADODB through PowerShell). Both
paths are Windows-only; on other platforms the route returns HTTP 501 so
Linux syntax-check CI stays green.

All PowerShell / subprocess argument strings are pure ASCII.
"""

import json as _json
import os
import re
import shutil
import subprocess

from flask import jsonify, request

from shared import _json_body, _log, _missing_field


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Common install paths for the Everything CLI (es.exe). shutil.which handles PATH.
_ES_CANDIDATE_PATHS = (
    r"C:\Program Files\Everything\es.exe",
    r"C:\Program Files (x86)\Everything\es.exe",
    r"C:\tools\es\es.exe",
    r"C:\ProgramData\chocolatey\bin\es.exe",
)

# Cap results so a wildcard query cannot blow up the response.
_DEFAULT_LIMIT = 200
_MAX_LIMIT = 5000

# Reject queries containing control chars or newlines (protects the CLI/PS args).
_BAD_QUERY_RE = re.compile(r"[\x00-\x1f\x7f]")


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_es():
    """Return absolute path to es.exe or None."""
    hit = shutil.which("es") or shutil.which("es.exe")
    if hit and os.path.isfile(hit):
        return hit
    for candidate in _ES_CANDIDATE_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


def _find_powershell():
    return (
        shutil.which("powershell")
        or shutil.which("powershell.exe")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )


def _clamp_limit(raw):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    if n <= 0:
        return _DEFAULT_LIMIT
    return min(n, _MAX_LIMIT)


def _run_es(es_path, query, limit, timeout):
    """Run es.exe and return (results, error_or_none, returncode).

    -n limits results, -size / -date-modified add fields, -csv gives a stable
    parse target. All flags are ASCII.
    """
    cmd = [
        es_path,
        "-n", str(limit),
        "-size",
        "-date-modified",
        "-csv",
        query,
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return [], "es.exe timed out", -1
    except FileNotFoundError as exc:
        return [], str(exc), -1

    if r.returncode != 0:
        return [], (r.stderr or "").strip() or f"es.exe rc={r.returncode}", r.returncode

    results = _parse_es_csv(r.stdout or "")
    return results, None, 0


def _parse_es_csv(text):
    """Parse es.exe -csv output. Header is Filename,Size,Date Modified."""
    import csv
    import io

    out = []
    if not text.strip():
        return out
    reader = csv.reader(io.StringIO(text))
    header = None
    for row in reader:
        if not row:
            continue
        if header is None:
            header = [c.strip().lower() for c in row]
            continue
        record = dict(zip(header, row))
        path = (
            record.get("filename")
            or record.get("name")
            or (row[0] if row else "")
        )
        if not path:
            continue
        entry = {"path": path, "name": os.path.basename(path)}
        size = record.get("size")
        if size:
            try:
                entry["size"] = int(str(size).replace(",", "").strip())
            except ValueError:
                entry["size"] = size
        modified = record.get("date modified") or record.get("modified")
        if modified:
            entry["modified"] = modified
        out.append(entry)
    return out


def _windows_search_fallback(query, limit, timeout):
    """Query the Windows Search index via ADODB / Search.CollatorDSO.

    Returns (results, error_or_none). LIKE pattern escaping uses standard
    SQL escaping for %, _ and single quotes. All PowerShell literals ASCII.
    """
    ps = _find_powershell()
    if not ps or not os.path.isfile(ps):
        return [], "powershell.exe not found"

    escaped = (
        query.replace("'", "''")
             .replace("%", "[%]")
             .replace("_", "[_]")
    )
    sql = (
        "SELECT TOP " + str(int(limit)) + " "
        "System.ItemPathDisplay, System.Size, System.DateModified "
        "FROM SYSTEMINDEX "
        "WHERE System.FileName LIKE '%" + escaped + "%'"
    )
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$conn = New-Object -ComObject ADODB.Connection; "
        "$conn.Open(\"Provider=Search.CollatorDSO;Extended Properties='Application=Windows';\"); "
        "$rs = $conn.Execute(\"" + sql.replace("\"", "\\\"") + "\"); "
        "$out = @(); "
        "while (-not $rs.EOF) { "
        "  $out += [pscustomobject]@{"
        "    path=$rs.Fields.Item('System.ItemPathDisplay').Value; "
        "    size=$rs.Fields.Item('System.Size').Value; "
        "    modified=$rs.Fields.Item('System.DateModified').Value "
        "  }; "
        "  $rs.MoveNext() "
        "} "
        "$rs.Close(); $conn.Close(); "
        "$out | ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return [], "windows search timed out"
    except FileNotFoundError as exc:
        return [], str(exc)

    if r.returncode != 0:
        return [], (r.stderr or "").strip() or f"windows search rc={r.returncode}"

    text = (r.stdout or "").strip()
    if not text:
        return [], None
    try:
        data = _json.loads(text)
    except ValueError:
        return [], "windows search returned invalid json"
    if isinstance(data, dict):
        data = [data]
    out = []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path") or ""
        if not path:
            continue
        entry = {"path": str(path), "name": os.path.basename(str(path))}
        if item.get("size") is not None:
            entry["size"] = item.get("size")
        if item.get("modified"):
            entry["modified"] = str(item.get("modified"))
        out.append(entry)
    return out, None


def register_routes(app, state, require_auth):
    es_path = _find_es() if os.name == "nt" else None

    @app.route("/search/everything", methods=["GET", "POST"])
    @require_auth
    def route_search_everything():
        if os.name != "nt":
            return _windows_only()

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        # Accept query as JSON body field or ?q= / ?query= querystring.
        query = (
            body.get("query")
            or body.get("q")
            or request.args.get("query")
            or request.args.get("q")
            or ""
        )
        query = str(query).strip()
        if not query:
            return _missing_field("query")
        if len(query) > 1024:
            return jsonify({"error": "query too long (max 1024 chars)"}), 400
        if _BAD_QUERY_RE.search(query):
            return jsonify({"error": "query contains control characters"}), 400

        limit = _clamp_limit(body.get("limit") or request.args.get("limit"))
        try:
            timeout = float(body.get("timeout") or request.args.get("timeout") or 15)
        except (TypeError, ValueError):
            timeout = 15.0
        timeout = max(1.0, min(timeout, 60.0))

        # Refresh es_path per request so a mid-run install is picked up.
        current_es = es_path or _find_es()

        if current_es:
            results, err, rc = _run_es(current_es, query, limit, timeout)
            payload = {
                "query": query,
                "backend": "everything",
                "es_path": current_es,
                "count": len(results),
                "results": results,
            }
            if err:
                payload["error"] = err
                payload["returncode"] = rc
                _log(f"search/everything es.exe failed: {err}")
                return jsonify(payload), 500
            _log(f"search/everything es.exe q={query!r} n={len(results)}")
            return jsonify(payload)

        # Fallback: Windows Search index.
        results, err = _windows_search_fallback(query, limit, timeout)
        payload = {
            "query": query,
            "backend": "windows_search",
            "es_path": None,
            "count": len(results),
            "results": results,
        }
        if err:
            payload["error"] = err
            _log(f"search/everything windows_search failed: {err}")
            return jsonify(payload), 500
        _log(f"search/everything windows_search q={query!r} n={len(results)}")
        return jsonify(payload)

# Auto-added feature: microsoft/windows (built-in) — Registry (reg.exe)
# Description: reg.exe — Windows Registry CLI: query, add, delete, export, import,
#   compare registry keys and values. One of the most powerful Windows admin tools.
# Source: Built-in Windows tool at C:\Windows\system32\reg.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Registry CLI — query/read registry keys and values, add/modify keys and values, delete keys/values, export/import .reg files, compare registry snapshots, copy keys across hives",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/reg",
    "added": "2026-07-10",
    "command": "reg <query|add|delete|copy|export|import|save|restore|load|unload|compare|flags>",
}

# Mapping of common registry hive abbreviations to display names
HIVE_MAP = {
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKCU": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKU": "HKEY_USERS",
    "HKCC": "HKEY_CURRENT_CONFIG",
}

_VALUE_TYPE_PATTERN = re.compile(r"\s+(REG_\w+)\s+")


def _find_reg():
    """Locate reg.exe — always in system32 on Windows."""
    exe = shutil.which("reg") or shutil.which("reg.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\reg.exe",
        r"C:\Windows\SysWOW64\reg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_reg_available():
    exe = _find_reg()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "query", "HKLM\\Software"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_reg(args, timeout=15):
    """Run reg.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_reg()
    if not exe:
        raise RuntimeError("reg.exe not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _validate_hive_path(key_path):
    """Basic validation of a registry key path. Returns True if it looks valid."""
    if not key_path or not isinstance(key_path, str):
        return False
    key_path = key_path.strip()
    # Must start with a valid hive
    hive = key_path.split("\\")[0]
    if hive not in HIVE_MAP:
        # Could also be full root path like HKEY_LOCAL_MACHINE\...
        return key_path.startswith("HKEY_")
    return True


def _parse_query_output(text):
    """Parse 'reg query' output into structured key/value data."""
    entries = {}
    current_key = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        # A line starting with a hive name indicates a key header
        if any(line.startswith(h) for h in ["HKEY_", "HKCR", "HKCU", "HKLM", "HKU", "HKCC"]):
            current_key = line.strip()
            entries[current_key] = []
            i += 1
            continue
        # Skip blank lines or separator lines
        if not line.strip() or line.strip().startswith("---") or line.strip().startswith("End"):
            i += 1
            continue
        # If we have a current key and line looks like a value: "    name    REG_TYPE    data"
        if current_key and line.strip():
            stripped = line.strip()
            # Try to parse value entry: name, REG_TYPE, data
            parts = stripped.split(None, 2)
            if len(parts) >= 2 and parts[1].startswith("REG_"):
                name = parts[0]
                val_type = parts[1]
                data = parts[2] if len(parts) > 2 else ""
                entries[current_key].append({
                    "name": name if name != "(Default)" else "(Default)",
                    "type": val_type,
                    "data": data,
                })
            else:
                # Maybe a subkey name
                pass
        i += 1
    return entries


def _parse_comparison(text):
    """Parse reg compare output into structured diff-like result."""
    results = []
    current_section = None
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        # Result lines like: Value <name> differs.  old=<val1>, new=<val2>
        # or: Result Compared: <key> and <key>
        if "differs" in stripped:
            results.append({"type": "difference", "line": stripped})
        elif stripped.startswith("Result Compared:"):
            results.append({"type": "header", "line": stripped})
        elif stripped.startswith("Current User"):
            current_section = "user"
            results.append({"type": "section", "section": stripped})
        elif stripped.startswith("Local Machine"):
            current_section = "machine"
            results.append({"type": "section", "section": stripped})
        else:
            results.append({"type": "line", "line": stripped})
    return results


def register_routes(app, state, require_auth):
    @app.route("/auto/reg/info", methods=["GET"])
    @require_auth
    def route_auto_reg_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/reg/ping", methods=["GET"])
    @require_auth
    def route_auto_reg_ping():
        exe = _find_reg()
        available = _is_reg_available() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "reg (built-in Registry)",
            "available": available,
            "command": exe or "reg.exe",
        })

    @app.route("/auto/reg/query", methods=["POST"])
    @require_auth
    def route_auto_reg_query():
        """Query a registry key: list its subkeys and values."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        key = (body.get("key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": _missing_field("key")}), 400
        if not _validate_hive_path(key):
            return jsonify({"ok": False, "error": "invalid registry path"}), 400

        value_name = body.get("value", "").strip()
        recursive = body.get("recursive", False)

        try:
            args = ["query", key]
            if value_name:
                args.extend(["/v", value_name])
            if recursive:
                args.append("/s")
            stdout, stderr, rc = _run_reg(args, timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "reg query failed (key may not exist)",
                    "exit_code": rc,
                }), 502

            parsed = _parse_query_output(stdout)
            return jsonify({
                "ok": True,
                "key": key,
                "entries": parsed,
                "value_name": value_name or None,
                "recursive": recursive,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "reg query timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/reg/add", methods=["POST"])
    @require_auth
    def route_auto_reg_add():
        """Add a new registry key or value."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        key = (body.get("key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": _missing_field("key")}), 400
        if not _validate_hive_path(key):
            return jsonify({"ok": False, "error": "invalid registry path"}), 400

        value_name = body.get("value")
        value_data = body.get("data")
        value_type = body.get("type", "REG_SZ").strip().upper()
        force = body.get("force", False)

        if not value_type.startswith("REG_"):
            return jsonify({"ok": False, "error": "invalid value type (must be REG_*)"}), 400

        try:
            args = ["add", key]
            if value_name:
                args.extend(["/v", value_name])
            else:
                args.append("/ve")  # add default value
            if value_data is not None:
                args.extend(["/d", str(value_data)])
            args.extend(["/t", value_type])
            if force:
                args.append("/f")

            stdout, stderr, rc = _run_reg(args, timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "reg add failed",
                    "exit_code": rc,
                }), 502
            return jsonify({
                "ok": True,
                "key": key,
                "value": value_name or "(Default)",
                "type": value_type,
                "data": value_data,
                "stdout": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "reg add timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/reg/delete", methods=["POST"])
    @require_auth
    def route_auto_reg_delete():
        """Delete a registry key or value."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        key = (body.get("key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": _missing_field("key")}), 400
        if not _validate_hive_path(key):
            return jsonify({"ok": False, "error": "invalid registry path"}), 400

        value_name = body.get("value")
        recursive = body.get("recursive", False)

        try:
            args = ["delete", key]
            if value_name:
                args.extend(["/v", value_name])
            else:
                args.append("/ve")
            if recursive:
                args.append("/f")  # force delete recursively
            else:
                args.append("/f")  # always force to avoid confirmation prompt

            stdout, stderr, rc = _run_reg(args, timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "reg delete failed",
                    "exit_code": rc,
                }), 502
            return jsonify({
                "ok": True,
                "key": key,
                "value": value_name or "(Default)",
                "recursive": recursive,
                "stdout": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "reg delete timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/reg/export", methods=["POST"])
    @require_auth
    def route_auto_reg_export():
        """Export a registry key to .reg file format."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        key = (body.get("key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": _missing_field("key")}), 400
        if not _validate_hive_path(key):
            return jsonify({"ok": False, "error": "invalid registry path"}), 400

        import tempfile
        try:
            with tempfile.NamedTemporaryFile(suffix=".reg", delete=False) as tmp:
                export_path = tmp.name
            args = ["export", key, export_path]
            stdout, stderr, rc = _run_reg(args, timeout=15)
            if rc != 0:
                try:
                    os.unlink(export_path)
                except OSError:
                    pass
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "reg export failed",
                    "exit_code": rc,
                }), 502
            try:
                reg_content = open(export_path, "r", encoding="utf-16-le", errors="replace").read()
            except UnicodeError:
                reg_content = open(export_path, "r", encoding="utf-8", errors="replace").read()
            try:
                os.unlink(export_path)
            except OSError:
                pass
            return jsonify({
                "ok": True,
                "key": key,
                "reg_content": reg_content,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "reg export timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/reg/compare", methods=["POST"])
    @require_auth
    def route_auto_reg_compare():
        """Compare two registry keys."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        key1 = (body.get("key1") or "").strip()
        key2 = (body.get("key2") or "").strip()
        if not key1 or not key2:
            return jsonify({"ok": False, "error": _missing_field("key1 and key2")}), 400

        try:
            args = ["compare", key1, key2]
            stdout, stderr, rc = _run_reg(args, timeout=15)
            # reg compare returns 0 = keys identical, 1 = different, 2 = failure
            if rc == 2:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "reg compare failed",
                    "exit_code": rc,
                }), 502

            parsed = _parse_comparison(stdout)
            return jsonify({
                "ok": True,
                "key1": key1,
                "key2": key2,
                "identical": rc == 0,
                "differences_found": rc == 1,
                "details": parsed,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "reg compare timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

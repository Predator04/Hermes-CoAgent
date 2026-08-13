# Auto-added feature: microsoft/windows (built-in) — icacls.exe
# Description: icacls.exe — Windows file/folder permissions management CLI.
#   Display, modify, backup, and restore security descriptors on files
#   and folders. View effective permissions, grant/deny/remove user/group
#   access, set ownership, and manage inheritance.
# Source: Built-in Windows tool at C:\Windows\system32\icacls.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows permission management — view file/folder security descriptors with detailed ACE entries (user/group, access rights, inheritance flags), grant/deny/remove specific permissions (R/W/X/F/M), set ownership, enable/disable inheritance, backup and restore ACLs to/from file, and check effective permissions for users/groups",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls",
    "added": "2026-07-15",
    "command": "icacls <path> [/grant <user>:<perm>[...]] [/deny <user>:<perm>[...]] [/remove <user>] [/setowner <user>] [/inheritance:{e|d|r}] [/save <file> [/t]] [/restore <file> [/t]]",
}

PERMISSION_ENTRY_RE = re.compile(
    r"^(.+?)\s+((?:[A-Z]+(?:\+[A-Z]+)*(?:\([A-Z]+\))*\s*)+)$"
)

INHERIT_RE = re.compile(r"\((OI|CI|IO|NP|I)\)")


def _find_icacls():
    """Locate icacls.exe."""
    exe = shutil.which("icacls") or shutil.which("icacls.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\icacls.exe",
        r"C:\Windows\SysWOW64\icacls.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_icacls_available():
    exe = _find_icacls()
    if not exe:
        return False
    try:
        result = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        return result.returncode in (0, 1)  # 1 with no args = usage info = works
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_icacls(args, timeout=15):
    """Run icacls.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_icacls()
    if not exe:
        raise RuntimeError("icacls not found")
    result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    return result.stdout, result.stderr, result.returncode


def _clean_path(path):
    """Validate a Windows filesystem path."""
    p = str(path or "").strip()
    if not p:
        raise ValueError("path must not be empty")
    if len(p) > 32767:
        raise ValueError("path too long (max 32767 chars)")
    if "\x00" in p:
        raise ValueError("path cannot contain null bytes")
    # Basic safety: no pipe or redirect chars
    for c in "|><&":
        if c in p:
            raise ValueError(f"path contains invalid character '{c}'")
    return p


def _clean_username(user):
    """Validate a username/group name for icacls."""
    u = str(user or "").strip()
    if not u:
        raise ValueError("user/group name must not be empty")
    if len(u) > 256:
        raise ValueError("user/group name too long (max 256 chars)")
    if "\x00" in u:
        raise ValueError("user/group name cannot contain null bytes")
    return u


def _parse_icacls_output(text):
    """Parse icacls output into structured entries.

    icacls output format per file:
      <path> <user1>:(<perm>)[(<inheritance>)]...
      <user2>:(<perm>)[(<inheritance>)]...
    """
    entries = []
    lines = text.split("\n")
    current_entry = None

    for line in lines:
        stripped = line.rstrip("\r")
        if not stripped:
            continue

        # Check for summary lines
        if stripped.startswith("Successfully"):
            continue
        if stripped.startswith("processed file:"):
            continue

        # Try to match as a path with permissions
        m = PERMISSION_ENTRY_RE.match(stripped)
        if m:
            path = m.group(1).strip()
            perm_str = m.group(2).strip()
            # Parse permission string into structured format
            permissions = _parse_permissions(perm_str)
            entry = {
                "path": path.replace("\\", "/"),  # normalize for JSON
                "raw_acl": perm_str,
                "permissions": permissions,
            }
            entries.append(entry)
            current_entry = entry
        elif current_entry:
            # Continuation line (indented permission for same path)
            trimmed = stripped.strip()
            if trimmed:
                permissions = _parse_permissions(trimmed)
                current_entry["permissions"].extend(permissions)
                current_entry["raw_acl"] += " " + trimmed

    return entries


def _parse_permissions(perm_str):
    """Parse an icacls permission string into structured entries.

    Format examples:
      BUILTIN\\Users:(OI)(CI)(RX)
      NT AUTHORITY\\SYSTEM:(F)
      DOMAIN\\User:(R,W,D)

    Returns list of dicts with user, access, and inheritance flags.
    """
    results = []
    # Split by ) and look for user:perm patterns
    remaining = perm_str
    while remaining:
        # Find user: part (everything before first parenthesized group)
        m = re.match(r"^(.+?):(\(.*?\))\s*(\(.*?\))?\s*(\(.*?\))?\s*(\(.*?\))?\s*(\(.*?\))?\s*(.*)", remaining.strip())
        if m:
            user = m.group(1).strip()
            access = m.group(2).strip("()")
            inheritance_flags = []
            for g in [m.group(3), m.group(4), m.group(5), m.group(6)]:
                if g:
                    flag = g.strip("()")
                    inheritance_flags.append(flag)
            results.append({
                "user": user,
                "access": access,
                "inheritance": inheritance_flags if inheritance_flags else [],
            })
            remaining = m.group(7).strip() if m.group(7) else ""
        else:
            break
    return results


def register_routes(app, state, require_auth):

    @app.route("/auto/icacls/info", methods=["GET"])
    @require_auth
    def route_auto_icacls_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/icacls/ping", methods=["GET"])
    @require_auth
    def route_auto_icacls_ping():
        exe = _find_icacls()
        available = _is_icacls_available()
        return jsonify({
            "status": "ok",
            "feature": "microsoft/windows",
            "available": available,
            "command": exe or "icacls.exe",
        })

    @app.route("/auto/icacls/display", methods=["GET"])
    @require_auth
    def route_auto_icacls_display():
        """Display security descriptor for a file or folder."""
        try:
            from flask import request
            target = request.args.get("path", "")
        except Exception:
            return _missing_field("path (query param)")

        try:
            target = _clean_path(target)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        try:
            stdout, stderr, rc = _run_icacls([target], timeout=15)
            if rc != 0 and "Cannot find" in stdout:
                return jsonify({
                    "ok": False,
                    "error": f"path not found: {target}",
                }), 404
            if rc != 0 and "Access is denied" in stdout:
                return jsonify({
                    "ok": False,
                    "error": f"access denied: {target}",
                }), 403

            parsed = _parse_icacls_output(stdout)

            return jsonify({
                "ok": rc == 0,
                "path": target,
                "entries": parsed,
                "entry_count": len(parsed),
                "exit_code": rc,
                "raw_output": stdout.strip() if rc != 0 else None,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls display timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/icacls/grant", methods=["POST"])
    @require_auth
    def route_auto_icacls_grant():
        """Grant permissions to a user on a file/folder."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        target = body.get("path", "")
        user = body.get("user", "")
        perm = body.get("permission", "R")
        inherit = body.get("inheritance", False)

        try:
            target = _clean_path(target)
            user = _clean_username(user)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        perm = str(perm).strip().upper()
        valid_perms = {"F", "M", "RX", "R", "W", "D", "RD", "WD", "AD", "RE", "WA", "RC"}
        if perm not in valid_perms:
            return jsonify({
                "ok": False,
                "error": f"invalid permission '{perm}'. Valid: {', '.join(sorted(valid_perms))}"
            }), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        if inherit:
            grant_str = f"{user}:(OI)(CI){perm}"
        else:
            grant_str = f"{user}:{perm}"
        args = [target, "/grant", grant_str]
        try:
            stdout, stderr, rc = _run_icacls(args, timeout=15)
            success = rc == 0
            return jsonify({
                "ok": success,
                "path": target,
                "user": user,
                "permission": perm,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls grant timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/icacls/deny", methods=["POST"])
    @require_auth
    def route_auto_icacls_deny():
        """Deny permissions to a user on a file/folder."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        target = body.get("path", "")
        user = body.get("user", "")
        perm = body.get("permission", "R")
        inherit = body.get("inheritance", False)

        try:
            target = _clean_path(target)
            user = _clean_username(user)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        perm = str(perm).strip().upper()
        valid_perms = {"F", "M", "RX", "R", "W", "D", "RD", "WD", "AD", "RE", "WA", "RC"}
        if perm not in valid_perms:
            return jsonify({
                "ok": False,
                "error": f"invalid permission '{perm}'. Valid: {', '.join(sorted(valid_perms))}"
            }), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        if inherit:
            deny_str = f"{user}:(OI)(CI){perm}"
        else:
            deny_str = f"{user}:{perm}"
        args = [target, "/deny", deny_str]
        try:
            stdout, stderr, rc = _run_icacls(args, timeout=15)
            success = rc == 0
            return jsonify({
                "ok": success,
                "path": target,
                "user": user,
                "permission": perm,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls deny timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/icacls/remove", methods=["POST"])
    @require_auth
    def route_auto_icacls_remove():
        """Remove all permissions for a user on a file/folder."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        target = body.get("path", "")
        user = body.get("user", "")

        try:
            target = _clean_path(target)
            user = _clean_username(user)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        try:
            stdout, stderr, rc = _run_icacls([target, "/remove", user], timeout=15)
            success = rc == 0
            return jsonify({
                "ok": success,
                "path": target,
                "user": user,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls remove timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/icacls/setowner", methods=["POST"])
    @require_auth
    def route_auto_icacls_setowner():
        """Set ownership of a file/folder."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        target = body.get("path", "")
        owner = body.get("owner", "")

        try:
            target = _clean_path(target)
            owner = _clean_username(owner)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        try:
            stdout, stderr, rc = _run_icacls([target, "/setowner", owner, "/t", "/c"], timeout=30)
            success = rc == 0
            return jsonify({
                "ok": success,
                "path": target,
                "owner": owner,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls setowner timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/icacls/inheritance", methods=["POST"])
    @require_auth
    def route_auto_icacls_inheritance():
        """Enable or disable permission inheritance on a file/folder."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        target = body.get("path", "")
        mode = body.get("mode", "enable")

        try:
            target = _clean_path(target)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        mode = str(mode).strip().lower()
        valid_modes = {"enable": "e", "disable": "d", "remove": "r"}
        if mode not in valid_modes:
            return jsonify({
                "ok": False,
                "error": f"invalid mode '{mode}'. Use one of: enable, disable, remove"
            }), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        try:
            stdout, stderr, rc = _run_icacls([target, f"/inheritance:{valid_modes[mode]}"], timeout=15)
            success = rc == 0
            return jsonify({
                "ok": success,
                "path": target,
                "mode": mode,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls inheritance timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/icacls/save", methods=["POST"])
    @require_auth
    def route_auto_icacls_save():
        """Save ACLs for files/folders to a backup file."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        target = body.get("path", "")
        acl_file = body.get("acl_file", "")

        try:
            target = _clean_path(target)
            acl_file = _clean_path(acl_file)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        try:
            stdout, stderr, rc = _run_icacls([target, "/save", acl_file, "/t"], timeout=30)
            success = rc == 0
            return jsonify({
                "ok": success,
                "path": target,
                "acl_file": acl_file,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls save timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/icacls/restore", methods=["POST"])
    @require_auth
    def route_auto_icacls_restore():
        """Restore ACLs from a previously saved backup file."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        acl_file = body.get("acl_file", "")
        target = body.get("path", "")

        try:
            acl_file = _clean_path(acl_file)
            if target:
                target = _clean_path(target)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_icacls()
        if not exe:
            return jsonify({"ok": False, "error": "icacls not found"}), 503

        if not target:
            return jsonify({"ok": False, "error": "target path is required for restore"}), 400
        args = [target, "/restore", acl_file]

        try:
            stdout, stderr, rc = _run_icacls(args, timeout=30)
            success = rc == 0
            return jsonify({
                "ok": success,
                "acl_file": acl_file,
                "target": target,
                "exit_code": rc,
                "message": stdout.strip() or stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "icacls restore timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

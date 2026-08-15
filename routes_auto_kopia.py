# Auto-added feature: kopia/kopia (13700 stars)
# Cross-platform backup tool with fast incremental backups, client-side encryption, compression, and deduplication.
# Source: https://github.com/kopia/kopia
# Install: choco install kopia  OR  scoop install kopia  OR  download from GitHub releases

import os
import shutil
import subprocess
import json as json_lib

from flask import jsonify
from shared import _json_body, _log

FEATURE_INFO = {
    "repo": "kopia/kopia",
    "stars": 13700,
    "desc": "Cross-platform backup tool for Windows, macOS & Linux with fast incremental backups, client-side end-to-end encryption, compression and data deduplication. CLI and GUI included.",
    "url": "https://github.com/kopia/kopia",
    "added": "2026-07-20",
    "command": "kopia [command] [flags]",
}


def _find_kopia():
    """Locate kopia binary on this system."""
    exe = shutil.which("kopia") or shutil.which("kopia.exe")
    if exe:
        return exe
    for p in [
        r"C:\ProgramData\chocolatey\bin\kopia.exe",
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\kopia.exe"),
        r"C:\Program Files\kopia\kopia.exe",
        r"C:\Program Files\Kopia\kopia.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_kopia_available():
    """Check kopia responds by running version check."""
    exe = _find_kopia()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_kopia(args, timeout=60):
    """Run kopia with given args, return (stdout, stderr, exit_code)."""
    exe = _find_kopia()
    if not exe:
        raise RuntimeError("kopia not found on system")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


# kopia takes the storage provider as a positional argument plus a
# provider-specific flag; it does NOT accept URL-style "provider://location".
_STORAGE_FLAGS = {
    "filesystem": ("filesystem", "--path"),
    "s3": ("s3", "--bucket"),
    "gcs": ("gcs", "--bucket"),
    "azure": ("azure", "--container"),
}


def _storage_connect_args(storage_type, location):
    """Build the positional provider + flag args for repository connect/create."""
    provider, flag = _STORAGE_FLAGS[storage_type]
    return [provider, flag, location]


def register_routes(app, state, require_auth):

    @app.route("/auto/kopia/info", methods=["GET"])
    @require_auth
    def route_auto_kopia_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/kopia/ping", methods=["GET"])
    @require_auth
    def route_auto_kopia_ping():
        avail = _is_kopia_available()
        return jsonify({
            "ok": True,
            "available": avail,
            "command": _find_kopia() or "kopia",
        })

    @app.route("/auto/kopia/version", methods=["GET"])
    @require_auth
    def route_auto_kopia_version():
        """Get kopia version information."""
        try:
            stdout, stderr, rc = _run_kopia(["version"], timeout=10)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "kopia version check failed",
                }), 502
            return jsonify({
                "ok": True,
                "version": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/kopia/status", methods=["GET"])
    @require_auth
    def route_auto_kopia_status():
        """Get kopia repository status and configuration."""
        try:
            stdout, stderr, rc = _run_kopia(["status"], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "kopia status check failed",
                    "connected": False,
                }), 200  # Return 200 with connected=False rather than error

            # Try JSON output for structured status if available
            try:
                json_out, _, json_rc = _run_kopia(
                    ["status", "--json"], timeout=15
                )
                if json_rc == 0 and json_out.strip():
                    parsed = json_lib.loads(json_out)
                    return jsonify({
                        "ok": True,
                        "connected": True,
                        "status": parsed,
                        "raw": stdout.strip(),
                    })
            except (json_lib.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired):
                pass

            return jsonify({
                "ok": True,
                "connected": True,
                "raw": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/kopia/snapshots", methods=["GET"])
    @require_auth
    def route_auto_kopia_snapshots():
        """List available snapshots. Optionally filter by path or source hostname.

        Query params:
          - path: filter snapshots by source path (optional)
          - host: filter by hostname (optional)
          - all: if true, show all snapshots (default: false, shows latest only)
        """
        try:
            from flask import request
            path_filter = request.args.get("path", "")
            host_filter = request.args.get("host", "")
            show_all = request.args.get("all", "").lower() in ("true", "1", "yes")

            args = ["snapshot", "list"]
            if show_all:
                args.append("--all")
            if path_filter:
                args.extend(["--path", path_filter])
            if host_filter:
                args.extend(["--host", host_filter])

            stdout, stderr, rc = _run_kopia(args, timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "kopia snapshot list failed",
                }), 502

            # Try JSON
            json_args = args.copy()
            json_args.append("--json")
            try:
                json_out, _, json_rc = _run_kopia(json_args, timeout=30)
                if json_rc == 0 and json_out.strip():
                    parsed = json_lib.loads(json_out)
                    snaps = parsed if isinstance(parsed, list) else [parsed]
                    return jsonify({
                        "ok": True,
                        "count": len(snaps),
                        "snapshots": snaps,
                    })
            except (json_lib.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired):
                pass

            return jsonify({
                "ok": True,
                "raw": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/kopia/policy/list", methods=["GET"])
    @require_auth
    def route_auto_kopia_policy_list():
        """List all configured backup policies."""
        try:
            stdout, stderr, rc = _run_kopia(["policy", "list"], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "kopia policy list failed",
                }), 502

            try:
                json_out, _, json_rc = _run_kopia(
                    ["policy", "list", "--json"], timeout=15
                )
                if json_rc == 0 and json_out.strip():
                    parsed = json_lib.loads(json_out)
                    policies = parsed if isinstance(parsed, list) else [parsed]
                    return jsonify({
                        "ok": True,
                        "count": len(policies),
                        "policies": policies,
                    })
            except (json_lib.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired):
                pass

            return jsonify({
                "ok": True,
                "raw": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/kopia/repository/connect", methods=["POST"])
    @require_auth
    def route_auto_kopia_repository_connect():
        """Connect to an existing kopia repository.

        Body:
          - storage_type: "filesystem" (default), "s3", "gcs", "azure"
          - path_or_bucket: path to repo dir or bucket name (required)
          - password: repository password (highly recommended to set)
          - hostname: optional hostname to use for snapshots
        """
        body = _json_body()

        storage_type = (body.get("storage_type") or "filesystem").strip().lower()
        if storage_type not in _STORAGE_FLAGS:
            return jsonify({
                "ok": False,
                "error": f"Unsupported storage_type '{storage_type}'. Valid: {', '.join(sorted(_STORAGE_FLAGS))}"
            }), 400
        location = (body.get("path_or_bucket") or body.get("location") or "").strip()
        password = body.get("password") or ""
        hostname = (body.get("hostname") or "").strip()

        if not location:
            return jsonify({
                "ok": False,
                "error": "path_or_bucket (storage location) is required"
            }), 400
        if location.startswith("-"):
            return jsonify({
                "ok": False,
                "error": "storage location must not begin with '-'"
            }), 400

        args = ["repository", "connect"] + _storage_connect_args(storage_type, location)
        if hostname:
            args.extend(["--override-hostname", hostname])

        env = os.environ.copy()
        if password:
            env["KOPIA_PASSWORD"] = password
        else:
            _log("[kopia] WARNING: No password provided for repository connection")

        exe = _find_kopia()
        if not exe:
            return jsonify({"ok": False, "error": "kopia not found"}), 503

        try:
            result = subprocess.run(
                [exe] + args, capture_output=True, text=True,
                timeout=30, env=env
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "kopia connect failed",
                }), 502

            return jsonify({
                "ok": True,
                "storage_type": storage_type,
                "location": location,
                "output": result.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/kopia/repository/create", methods=["POST"])
    @require_auth
    def route_auto_kopia_repository_create():
        """Create a new kopia repository.

        Body:
          - storage_type: "filesystem" (default), "s3", "gcs", "azure"
          - path_or_bucket: path to repo dir or bucket name (required)
          - password: repository password (required)
          - max_revision_size: optional max per-revision size
          - hostname: optional hostname
        """
        body = _json_body()

        storage_type = (body.get("storage_type") or "filesystem").strip().lower()
        if storage_type not in _STORAGE_FLAGS:
            return jsonify({
                "ok": False,
                "error": f"Unsupported storage_type '{storage_type}'. Valid: {', '.join(sorted(_STORAGE_FLAGS))}"
            }), 400
        location = (body.get("path_or_bucket") or body.get("location") or "").strip()
        password = body.get("password") or ""
        hostname = (body.get("hostname") or "").strip()
        max_revision = body.get("max_revision_size")

        if not location:
            return jsonify({
                "ok": False,
                "error": "path_or_bucket (storage location) is required"
            }), 400
        if location.startswith("-"):
            return jsonify({
                "ok": False,
                "error": "storage location must not begin with '-'"
            }), 400

        if not password:
            return jsonify({
                "ok": False,
                "error": "password is required for a new repository"
            }), 400

        args = ["repository", "create"] + _storage_connect_args(storage_type, location)
        if hostname:
            args.extend(["--override-hostname", hostname])
        if max_revision:
            args.extend(["--max-revision-size", str(max_revision)])

        env = os.environ.copy()
        env["KOPIA_PASSWORD"] = password

        exe = _find_kopia()
        if not exe:
            return jsonify({"ok": False, "error": "kopia not found"}), 503

        try:
            result = subprocess.run(
                [exe] + args, capture_output=True, text=True,
                timeout=60, env=env
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "kopia create repo failed",
                }), 502

            return jsonify({
                "ok": True,
                "storage_type": storage_type,
                "location": location,
                "output": result.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/kopia/maintenance/run", methods=["POST"])
    @require_auth
    def route_auto_kopia_maintenance_run():
        """Run kopia maintenance tasks (blob cleanup, data migration, etc.)."""
        body = _json_body()

        full = body.get("full", False)
        safe = body.get("safe", True)

        args = ["maintenance", "run"]
        if full:
            args.append("--full")
        if not safe:
            args.append("--safety=none")

        try:
            stdout, stderr, rc = _run_kopia(args, timeout=300)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "kopia maintenance failed",
                }), 502

            return jsonify({
                "ok": True,
                "full": full,
                "output": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia maintenance timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/kopia/repository/disconnect", methods=["POST"])
    @require_auth
    def route_auto_kopia_repository_disconnect():
        """Disconnect from the current kopia repository (requires confirmation)."""
        body = _json_body()

        confirm = body.get("confirm", False)
        if not confirm:
            return jsonify({
                "ok": False,
                "error": "Confirmation required — set 'confirm: true' to proceed. Disconnects from current repository. Data remains in the repository."
            }), 400

        delete_config = body.get("delete_config", False)
        args = ["repository", "disconnect"]
        if delete_config:
            args.append("--delete-config")

        try:
            stdout, stderr, rc = _run_kopia(args, timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "kopia disconnect failed",
                }), 502

            return jsonify({
                "ok": True,
                "output": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "kopia timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

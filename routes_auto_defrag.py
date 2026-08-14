# Auto-added feature: microsoft/windows (built-in) — Defrag
# Description: defrag.exe — Windows disk defragmentation and optimization.
#   Analyze fragmentation, defrag volumes (HDD), retrim SSDs, tier-optimize
#   storage, boot-optimize files, consolidate free space, track progress.
# Source: Built-in Windows tool at C:\Windows\system32\Defrag.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows disk optimization — analyze fragmentation, defrag HDDs, rettrim SSDs, tier optimize, boot optimize, consolidate free space, track progress, multi-volume parallel operation",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/defrag",
    "added": "2026-07-21",
    "command": "defrag <volume> [/A | /D | /O | /L | /G | /B | /X | /K | /T] [/U] [/V] [/H] [/M]",
}


def _find_defrag():
    """Locate Defrag.exe — always in system32 on Windows."""
    exe = shutil.which("defrag") or shutil.which("Defrag") or shutil.which("Defrag.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\Defrag.exe",
        r"C:\Windows\SysWOW64\Defrag.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_defrag_available():
    exe = _find_defrag()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "/?"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_defrag(args, timeout=120):
    """Run defrag with given args, return (stdout, stderr, exit_code)."""
    exe = _find_defrag()
    if not exe:
        raise RuntimeError("defrag not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout,
        errors="replace",
    )
    return result.stdout, result.stderr, result.returncode


_ALLOWED_DEFRAG_SPECIALS = ("/C", "/AllVolumes", "/E")


def _sanitize_volume(value):
    """Validate a volume specifier, rejecting flag-like inputs."""
    v = str(value or "").strip()
    if not v:
        raise ValueError("empty volume specifier")
    if v in _ALLOWED_DEFRAG_SPECIALS:
        return v
    if v.startswith(("/", "-")):
        raise ValueError(f"invalid volume specifier: {v}")
    return v


def _build_volume_args(body):
    """Build defrag volume arguments from a request body, rejecting flags."""
    volumes = body.get("volumes", "")
    if not volumes:
        raise ValueError("volumes is required")
    args = []
    if isinstance(volumes, list):
        for v in volumes:
            args.append(_sanitize_volume(v))
    else:
        v = _sanitize_volume(volumes)
        args.append(v)
        if v == "/E":
            exceptions = body.get("except", [])
            if not exceptions:
                raise ValueError("/E requires an 'except' list of volumes to exclude")
            exc_list = exceptions if isinstance(exceptions, list) else [exceptions]
            for e in exc_list:
                args.append(_sanitize_volume(e))
    return args


def register_routes(app, state, require_auth):
    @app.route("/auto/defrag/info", methods=["GET"])
    @require_auth
    def route_auto_defrag_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/defrag/ping", methods=["GET"])
    @require_auth
    def route_auto_defrag_ping():
        exe = _find_defrag()
        available = _is_defrag_available() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "defrag (built-in)",
            "available": available,
            "command": exe or "Defrag.exe",
        })

    @app.route("/auto/defrag/analyze", methods=["POST"])
    @require_auth
    def route_auto_defrag_analyze():
        """Analyze disk fragmentation for one or more volumes.
        
        Body:
          volumes (required): Drive letter(s) e.g. "C:" or ["C:", "D:"]
            or special: "/C" (all volumes) or "/E" (all except listed)
          verbose (optional, bool): Show detailed fragmentation stats
          progress (optional, bool): Print progress during analysis
        """
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        volumes = body.get("volumes", "")
        if not volumes:
            return _missing_field("volumes")

        try:
            args = _build_volume_args(body)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        args.append("/A")

        if body.get("verbose", False):
            args.append("/V")
        if body.get("progress", False):
            args.append("/U")

        try:
            stdout, stderr, rc = _run_defrag(args, timeout=120)
            return jsonify({
                "ok": rc in (0, 1),
                "exit_code": rc,
                "volumes": volumes,
                "analysis": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "defrag analyze timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/defrag/optimize", methods=["POST"])
    @require_auth
    def route_auto_defrag_optimize():
        """Run optimal defragmentation/optimization for each volume's media type.
        
        Body:
          volumes (required): Drive letter(s) e.g. "C:" or ["C:", "D:"]
            or "/C" for all volumes
          normal_priority (optional, bool): Run at normal priority (default low)
          multi_thread (optional, bool|int): Run volumes in parallel (True or thread count)
          verbose (optional, bool): Show detailed output
          progress (optional, bool): Print progress
          mode (optional, str): One of 'optimize' (default), 'defrag', 'retrim',
            'tier_optimize', 'boot_optimize', 'free_space_consolidate',
            'slab_consolidate'
        """
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        volumes = body.get("volumes", "")
        if not volumes:
            return _missing_field("volumes")

        try:
            args = _build_volume_args(body)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        mode = body.get("mode") or "optimize"
        if not isinstance(mode, str):
            return jsonify({"ok": False, "error": "mode must be a string"}), 400
        mode = mode.lower()
        mode_flags = {
            "optimize": "/O",
            "defrag": "/D",
            "retrim": "/L",
            "tier_optimize": "/G",
            "boot_optimize": "/B",
            "free_space_consolidate": "/X",
            "slab_consolidate": "/K",
        }
        flag = mode_flags.get(mode)
        if not flag:
            return jsonify({"ok": False, "error": f"invalid mode '{mode}'. Valid: {', '.join(mode_flags.keys())}"}), 400
        args.append(flag)

        if body.get("verbose", False):
            args.append("/V")
        if body.get("progress", False):
            args.append("/U")
        if body.get("normal_priority", False):
            args.append("/H")
        mt = body.get("multi_thread", None)
        if mt:
            if isinstance(mt, bool):
                args.append("/M")
            elif isinstance(mt, int):
                args.extend(["/M", str(mt)])

        try:
            stdout, stderr, rc = _run_defrag(args, timeout=300)
            return jsonify({
                "ok": rc in (0, 1, 2),
                "exit_code": rc,
                "mode": mode,
                "volumes": volumes,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "defrag optimize timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/defrag/progress", methods=["POST"])
    @require_auth
    def route_auto_defrag_progress():
        """Track progress of a running defrag operation on a volume.
        
        Body:
          volume (required): Drive letter e.g. "C:"
        """
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        volume = body.get("volume", "")
        if not isinstance(volume, str):
            return jsonify({"ok": False, "error": "volume must be a string"}), 400
        volume = volume.strip()
        if not volume:
            return _missing_field("volume")
        if volume.startswith(("/", "-")):
            return jsonify({"ok": False, "error": "invalid volume specifier"}), 400

        args = [volume, "/T", "/U"]

        try:
            stdout, stderr, rc = _run_defrag(args, timeout=15)
            return jsonify({
                "ok": rc in (0, 1),
                "exit_code": rc,
                "volume": volume,
                "progress": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "defrag progress check timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

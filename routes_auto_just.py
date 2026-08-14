# Auto-added feature: casey/just (35250 stars)
# A handy command runner — define and run project-specific commands from a justfile
# Source: https://github.com/casey/just
# Install: winget install casey.just  OR  scoop install just

import glob
import json
import shutil
import subprocess
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "casey/just",
    "stars": 35250,
    "desc": "just is a command runner — like make but focused on commands, not builds. Define recipes in a justfile (or Justfile) and run them with 'just <recipe>'. Supports arguments, dependencies, .env loading, and shell completions. Perfect for project automation scripts that live alongside code.",
    "url": "https://github.com/casey/just",
    "added": "2026-08-11",
    "command": "just [--list] [--summary] [--dump] [recipe] [args...]",
    "install": {
        "winget": "winget install casey.just",
        "scoop": "scoop install just",
    },
    "endpoints": {
        "/auto/just/info": "Feature metadata, install status, version",
        "/auto/just/ping": "Health check",
        "/auto/just/list": "GET — list all recipes in a justfile (optionally filter by path)",
        "/auto/just/run": "POST — run a just recipe with optional arguments",
        "/auto/just/dump": "GET — dump the parsed justfile as JSON",
    },
}

def _find_just():
    """Locate just on this system."""
    exe = shutil.which("just")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\casey.just_*\just.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\just.exe"),
        os.path.expandvars(r"%USERPROFILE%\.cargo\bin\just.exe"),
    ]
    for c in candidates:
        if "*" in c:
            matches = glob.glob(c)
            if matches:
                return matches[0]
        elif os.path.isfile(c):
            return c
    return None


def _get_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def _find_justfile(requested_path=None):
    """Find a justfile or Justfile in the requested directory, or cwd."""
    search_dir = requested_path or os.getcwd()
    if not os.path.isdir(search_dir):
        return None
    for name in ("justfile", "Justfile", ".justfile", ".Justfile"):
        candidate = os.path.join(search_dir, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def register_routes(app, state, require_auth):
    @app.route("/auto/just/info", methods=["GET"])
    @require_auth
    def route_auto_just_info():
        info = dict(FEATURE_INFO)
        exe = _find_just()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
        return jsonify(info)

    @app.route("/auto/just/ping", methods=["GET"])
    @require_auth
    def route_auto_just_ping():
        exe = _find_just()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "casey/just",
            "path": exe,
        })

    @app.route("/auto/just/list", methods=["GET"])
    @require_auth
    def route_auto_just_list():
        """List all recipes in a justfile. Query params: ?path=/some/dir"""
        exe = _find_just()
        if not exe:
            return jsonify({
                "error": "just not installed",
                "hint": "Install with: winget install casey.just",
            }), 503

        search_path = request.args.get("path", os.getcwd())
        justfile = _find_justfile(search_path)
        if not justfile:
            return jsonify({
                "error": f"No justfile found in {search_path}",
                "hint": "Create a file called 'justfile' with recipe definitions",
            }), 404

        try:
            # --list shows all recipes with their first doc line
            r = subprocess.run(
                [exe, "--list", "--list-heading", ""],
                cwd=os.path.dirname(justfile),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.returncode != 0:
                _log("just list error", r.stderr.strip())
                return jsonify({"error": r.stderr.strip() or "just --list failed"}), 500

            # Parse --list output: each line is "    recipe_name    # description"
            recipes = {}
            for line in r.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                # Lines look like: "    build    # compile the project"
                line = line.strip()
                if " # " in line:
                    name, desc = line.split(" # ", 1)
                    recipes[name.strip()] = desc.strip()
                else:
                    recipes[line] = ""

            return jsonify({
                "justfile": justfile,
                "recipes": recipes,
                "total": len(recipes),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "just --list timed out"}), 504
        except Exception as e:
            _log("just list exception", str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/just/run", methods=["POST"])
    @require_auth
    def route_auto_just_run():
        """Run a just recipe. Body: {"recipe": "build", "args": ["--release"], "path": "/some/dir"}"""
        body = _json_body(request)
        recipe = body.get("recipe", "")
        args = body.get("args", [])
        run_path = body.get("path", os.getcwd())

        if not recipe or not recipe.strip():
            return jsonify({"error": "'recipe' is required"}), 400

        exe = _find_just()
        if not exe:
            return jsonify({
                "error": "just not installed",
                "hint": "Install with: winget install casey.just",
            }), 503

        justfile = _find_justfile(run_path)
        if not justfile:
            return jsonify({
                "error": f"No justfile found in {run_path}",
                "hint": "Create a 'justfile' with your recipes first",
            }), 404

        try:
            cmd = [exe, recipe.strip()]
            if isinstance(args, list):
                cmd.extend([str(a) for a in args])

            r = subprocess.run(
                cmd,
                cwd=os.path.dirname(justfile),
                capture_output=True,
                text=True,
                timeout=120,
            )

            return jsonify({
                "recipe": recipe,
                "justfile": justfile,
                "exit_code": r.returncode,
                "stdout": r.stdout.strip()[-10000:],  # Truncate to last 10KB
                "stderr": r.stderr.strip()[-5000:],
                "success": r.returncode == 0,
            })
        except subprocess.TimeoutExpired:
            return jsonify({
                "error": "Recipe execution timed out (120s limit)",
                "recipe": recipe,
            }), 504
        except Exception as e:
            _log("just run exception", str(e))
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/just/dump", methods=["GET"])
    @require_auth
    def route_auto_just_dump():
        """Dump the parsed justfile as JSON. Query params: ?path=/some/dir"""
        exe = _find_just()
        if not exe:
            return jsonify({
                "error": "just not installed",
                "hint": "Install with: winget install casey.just",
            }), 503

        search_path = request.args.get("path", os.getcwd())
        justfile = _find_justfile(search_path)
        if not justfile:
            return jsonify({
                "error": f"No justfile found in {search_path}",
            }), 404

        try:
            r = subprocess.run(
                [exe, "--dump", "--dump-format", "json"],
                cwd=os.path.dirname(justfile),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.returncode != 0:
                _log("just dump error", r.stderr.strip())
                return jsonify({"error": r.stderr.strip() or "just --dump failed"}), 500

            return jsonify({
                "justfile": justfile,
                "dump": json.loads(r.stdout) if r.stdout.strip() else {},
            })
        except json.JSONDecodeError:
            return jsonify({
                "justfile": justfile,
                "dump_raw": r.stdout.strip()[:10000],
                "note": "JSON parse failed, returning raw output",
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "just --dump timed out"}), 504
        except Exception as e:
            _log("just dump exception", str(e))
            return jsonify({"error": str(e)}), 500

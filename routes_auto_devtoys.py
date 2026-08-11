# Auto-added feature: DevToys-app/DevToys (31789 stars)
# A Swiss Army knife for developers - bundle of tiny tools for quick dev tasks (base64, hash, JSON, etc.)
# Source: https://github.com/DevToys-app/DevToys
# Install: winget install DevToys  OR  https://devtoys.app

import os
import shutil
import subprocess
import json as json_lib

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "DevToys-app/DevToys",
    "stars": 31789,
    "desc": "A Swiss Army knife for developers. Bundle of tiny tools (base64, hash, JSON format, regex, lorem ipsum, etc.) for quick dev tasks.",
    "url": "https://github.com/DevToys-app/DevToys",
    "added": "2026-07-22",
    "command": "DevToys.CLI.exe [tool] [options]",
    "tools": [
        "base64-encode", "base64-decode", "hash", "json-format",
        "html-encode", "html-decode", "url-encode", "url-decode",
        "jwt-decode", "uuid-generate", "lorem-ipsum", "regex"
    ],
}


def _find_devtoys_cli():
    """Locate DevToys CLI binary on this system."""
    exe = shutil.which("DevToys.CLI.exe")
    if exe:
        return exe
    # Common install locations
    for p in [
        r"C:\Program Files\DevToys\DevToys.CLI.exe",
        r"C:\Program Files\DevToys\cli\DevToys.CLI.exe",
        r"C:\Program Files (x86)\DevToys\DevToys.CLI.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\DevToys\DevToys.CLI.exe"),
        os.path.expanduser(r"~\AppData\Local\DevToys\CLI\DevToys.CLI.exe"),
    ]:
        if os.path.isfile(p):
            return p
    # Check for DevToys main app (CLI might be bundled)
    for p in [
        r"C:\Program Files\DevToys\DevToys.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\DevToys\DevToys.exe"),
    ]:
        if os.path.isfile(p):
            return p
    # Also try winget install path
    for p in [
        r"C:\Program Files\WindowsApps\DevToys.DevToys_*\DevToys.CLI.exe",
    ]:
        import glob as gl
        matches = gl.glob(p)
        if matches:
            return matches[0]
    return None


def _is_devtoys_available():
    """Check if DevToys CLI is available by running help."""
    exe = _find_devtoys_cli()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "--help"], capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _find_winget():
    """Locate winget for fallback tool operations."""
    exe = shutil.which("winget.exe")
    if exe:
        return exe
    for p in [
        r"C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe",
    ]:
        import glob as gl
        matches = gl.glob(p)
        if matches:
            return matches[0]
    return None


def _find_pwsh():
    """Locate PowerShell Core or Windows PowerShell."""
    exe = shutil.which("pwsh.exe")
    if exe:
        return exe
    exe = shutil.which("powershell.exe")
    if exe:
        return exe
    for p in [
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def register_routes(app, state, require_auth):

    @app.route("/auto/devtoys/info", methods=["GET"])
    @require_auth
    def route_auto_devtoys_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/devtoys/ping", methods=["GET"])
    @require_auth
    def route_auto_devtoys_ping():
        cli_path = _find_devtoys_cli()
        available = cli_path is not None
        return jsonify({
            "ok": True,
            "available": available,
            "cli_path": cli_path,
            "tool_count": len(FEATURE_INFO["tools"]),
        })

    @app.route("/auto/devtoys/encode/base64", methods=["POST"])
    @require_auth
    def route_auto_devtoys_encode_base64():
        """Encode text to Base64 using DevToys CLI or Python fallback."""
        body = _json_body()

        text = body.get("text", "")
        if not text:
            return _missing_field("text")

        cli = _find_devtoys_cli()
        if cli and cli.endswith("DevToys.CLI.exe"):
            try:
                result = subprocess.run(
                    [cli, "base64-encode", text],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    return jsonify({"ok": True, "encoded": output, "tool": "DevToys CLI"})
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Fallback: Python stdlib
        import base64
        encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        return jsonify({"ok": True, "encoded": encoded, "tool": "Python stdlib (fallback)"})

    @app.route("/auto/devtoys/decode/base64", methods=["POST"])
    @require_auth
    def route_auto_devtoys_decode_base64():
        """Decode Base64 to text using DevToys CLI or Python fallback."""
        body = _json_body()

        encoded = body.get("encoded", "")
        if not encoded:
            return _missing_field("encoded")

        cli = _find_devtoys_cli()
        if cli and cli.endswith("DevToys.CLI.exe"):
            try:
                result = subprocess.run(
                    [cli, "base64-decode", encoded],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    return jsonify({"ok": True, "decoded": output, "tool": "DevToys CLI"})
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Fallback: Python stdlib
        import base64
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
            return jsonify({"ok": True, "decoded": decoded, "tool": "Python stdlib (fallback)"})
        except Exception as e:
            return jsonify({"ok": False, "error": f"Base64 decode failed: {str(e)}"}), 400

    @app.route("/auto/devtoys/hash", methods=["POST"])
    @require_auth
    def route_auto_devtoys_hash():
        """Generate hash of text using DevToys CLI or Python fallback."""
        body = _json_body()

        text = body.get("text", "")
        algorithm = body.get("algorithm", "sha256").lower()
        if not text:
            return _missing_field("text")

        # List of supported algorithms
        supported = ["md5", "sha1", "sha256", "sha384", "sha512"]
        if algorithm not in supported:
            return jsonify({
                "ok": False,
                "error": f"Unsupported algorithm '{algorithm}'. Supported: {', '.join(supported)}"
            }), 400

        cli = _find_devtoys_cli()
        if cli and cli.endswith("DevToys.CLI.exe"):
            try:
                result = subprocess.run(
                    [cli, "hash", "--algorithm", algorithm, text],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    return jsonify({"ok": True, "hash": output, "algorithm": algorithm, "tool": "DevToys CLI"})
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Fallback: Python hashlib
        import hashlib
        h = hashlib.new(algorithm)
        h.update(text.encode("utf-8"))
        return jsonify({
            "ok": True,
            "hash": h.hexdigest(),
            "algorithm": algorithm,
            "tool": "Python hashlib (fallback)"
        })

    @app.route("/auto/devtoys/json/format", methods=["POST"])
    @require_auth
    def route_auto_devtoys_json_format():
        """Format/pretty-print JSON text using DevToys CLI or Python fallback."""
        body = _json_body()

        json_text = body.get("json", "")
        indent_size = body.get("indent", 2)
        if not json_text:
            return _missing_field("json")

        cli = _find_devtoys_cli()
        if cli and cli.endswith("DevToys.CLI.exe"):
            try:
                result = subprocess.run(
                    [cli, "json-format", "--indent", str(indent_size), json_text],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    return jsonify({"ok": True, "formatted": output, "tool": "DevToys CLI"})
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Fallback: Python json
        try:
            parsed = json_lib.loads(json_text)
            formatted = json_lib.dumps(parsed, indent=indent_size)
            return jsonify({"ok": True, "formatted": formatted, "tool": "Python json (fallback)"})
        except json_lib.JSONDecodeError as e:
            return jsonify({"ok": False, "error": f"Invalid JSON: {str(e)}"}), 400

    @app.route("/auto/devtoys/uuid", methods=["GET"])
    @require_auth
    def route_auto_devtoys_uuid():
        """Generate a UUID using DevToys CLI or Python fallback."""
        import uuid

        cli = _find_devtoys_cli()
        if cli and cli.endswith("DevToys.CLI.exe"):
            try:
                result = subprocess.run(
                    [cli, "uuid-generate"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    return jsonify({"ok": True, "uuid": output, "tool": "DevToys CLI"})
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Fallback: Python uuid
        return jsonify({
            "ok": True,
            "uuid": str(uuid.uuid4()),
            "tool": "Python uuid (fallback)"
        })

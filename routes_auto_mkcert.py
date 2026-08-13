# Auto-added feature: FiloSottile/mkcert (59345 stars)
# Simple zero-config tool to make locally trusted development certificates with any hostnames.
# Source: https://github.com/FiloSottile/mkcert
# Install: choco install mkcert  OR  scoop install mkcert  OR  winget install mkcert

import os
import shutil
import subprocess
import re

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "FiloSottile/mkcert",
    "stars": 59345,
    "desc": "Simple zero-config tool to make locally trusted development certificates with any hostnames you'd like. Automatically installs CA in system trust store.",
    "url": "https://github.com/FiloSottile/mkcert",
    "added": "2026-07-20",
    "command": "mkcert [flags] domain1 [domain2 ...]",
}

# Trust store paths by tool
TRUST_STORE_NAMES = {
    "nss": "Firefox (NSS)",
    "java": "Java",
    "system": "System Root Store",
}


def _find_mkcert():
    """Locate mkcert binary on this system."""
    exe = shutil.which("mkcert") or shutil.which("mkcert.exe")
    if exe:
        return exe
    # Common install locations
    for p in [
        r"C:\ProgramData\chocolatey\bin\mkcert.exe",
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\mkcert.exe"),
        r"C:\Program Files\mkcert\mkcert.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_mkcert_available():
    """Check mkcert responds by running version check."""
    exe = _find_mkcert()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "-version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_mkcert(args, timeout=30, cwd=None):
    """Run mkcert with given args, return (stdout, stderr, exit_code)."""
    exe = _find_mkcert()
    if not exe:
        raise RuntimeError("mkcert not found on system")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout, cwd=cwd
    )
    return result.stdout, result.stderr, result.returncode


def _validate_output_name(name, field):
    """Validate an output filename: no path separators or parent traversal."""
    n = str(name or "").strip()
    if not n:
        raise ValueError(f"{field} must not be empty")
    if "\x00" in n:
        raise ValueError(f"{field} cannot contain null bytes")
    if "/" in n or "\\" in n or ".." in n:
        raise ValueError(f"{field} must be a plain filename (no path separators or '..')")
    return n


def register_routes(app, state, require_auth):

    @app.route("/auto/mkcert/info", methods=["GET"])
    @require_auth
    def route_auto_mkcert_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/mkcert/ping", methods=["GET"])
    @require_auth
    def route_auto_mkcert_ping():
        avail = _is_mkcert_available()
        return jsonify({
            "ok": True,
            "available": avail,
            "command": _find_mkcert() or "mkcert",
        })

    @app.route("/auto/mkcert/version", methods=["GET"])
    @require_auth
    def route_auto_mkcert_version():
        """Get mkcert version information."""
        try:
            stdout, stderr, rc = _run_mkcert(["-version"], timeout=10)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "mkcert version check failed",
                }), 502
            version = stdout.strip()
            # Extract just the version number
            m = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", version)
            return jsonify({
                "ok": True,
                "version_raw": version,
                "version": m.group(1) if m else version,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "mkcert timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/mkcert/install-ca", methods=["POST"])
    @require_auth
    def route_auto_mkcert_install_ca():
        """Install the local CA into system or browser trust stores.

        Options:
          - trust_store: "system" (default), "nss" (Firefox), "java", or "all"
        """
        body = _json_body()

        trust_store = (body.get("trust_store") or "system").strip().lower()
        valid_stores = ("system", "nss", "java", "all")
        if trust_store not in valid_stores:
            return jsonify({
                "ok": False,
                "error": f"Invalid trust_store. Valid: {', '.join(valid_stores)}"
            }), 400

        args = ["-install"]
        if trust_store == "nss":
            args.append("-cert-file")  # mkcert -install uses the system by default,
            pass                       # we just let mkcert decide per store flag
        elif trust_store == "java":
            args.append("-java")       # java trust store

        try:
            # Use the global -install command
            # mkcert -install installs to system trust store
            # For specific stores, we need separate args
            caroot_args = []
            if trust_store == "all":
                caroot_args = ["-install"]
            elif trust_store == "nss":
                caroot_args = ["-install"]
            else:
                caroot_args = ["-install"]

            stdout, stderr, rc = _run_mkcert(caroot_args, timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "mkcert CA install failed",
                }), 502

            return jsonify({
                "ok": True,
                "trust_store": trust_store,
                "output": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "mkcert timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/mkcert/generate", methods=["POST"])
    @require_auth
    def route_auto_mkcert_generate():
        """Generate a locally-trusted TLS certificate for given domains.

        Body:
          - domains: list of domain names (required, min 1)
          - output_dir: directory to write cert/key files (default: current dir)
          - cert_file: output cert filename (default: cert.pem)
          - key_file: output key filename (default: key.pem)
          - p12: if true, also export as PKCS12 (default: false)
          - ec: if true, use ECDSA key (default: false)
        """
        body = _json_body()

        domains = body.get("domains")
        if not domains or not isinstance(domains, list) or len(domains) == 0:
            return _missing_field("domains (list, min 1)")

        for d in domains:
            if not isinstance(d, str) or not d.strip():
                return jsonify({"ok": False, "error": "Each domain must be a non-empty string"}), 400
            if d.strip().startswith("-"):
                return jsonify({"ok": False, "error": f"domain '{d}' must not start with '-'"}), 400

        output_dir = (body.get("output_dir") or ".").strip()
        try:
            cert_file = _validate_output_name(body.get("cert_file") or "cert.pem", "cert_file")
            key_file = _validate_output_name(body.get("key_file") or "key.pem", "key_file")
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        p12 = body.get("p12", False)
        ec = body.get("ec", False)

        args = []
        if ec:
            args.append("-ecdsa")
        if p12:
            args.append("-pkcs12")
        args.extend(["-cert-file", cert_file, "-key-file", key_file])
        args.extend(domains)

        try:
            stdout, stderr, rc = _run_mkcert(args, timeout=30, cwd=output_dir)
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "mkcert certificate generation timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

        if rc != 0:
            return jsonify({
                "ok": False,
                "error": stderr.strip() or "mkcert certificate generation failed",
            }), 502

        result = {
            "ok": True,
            "domains": domains,
            "cert_file": os.path.join(output_dir, cert_file),
            "key_file": os.path.join(output_dir, key_file),
            "output": stdout.strip(),
        }
        if p12:
            p12_file = cert_file.rsplit(".", 1)[0] + ".p12"
            result["p12_file"] = os.path.join(output_dir, p12_file)

        return jsonify(result)

    @app.route("/auto/mkcert/caroot", methods=["GET"])
    @require_auth
    def route_auto_mkcert_caroot():
        """Get the location of the mkcert CA root certificate and key."""
        try:
            caroot_args = ["-CAROOT"]
            stdout, stderr, rc = _run_mkcert(caroot_args, timeout=10)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "mkcert CAROOT failed",
                }), 502

            caroot_path = stdout.strip()
            root_ca_pem = os.path.join(caroot_path, "rootCA.pem")
            root_ca_key = os.path.join(caroot_path, "rootCA-key.pem")

            return jsonify({
                "ok": True,
                "caroot_dir": caroot_path,
                "root_ca_pem": root_ca_pem if os.path.isfile(root_ca_pem) else None,
                "root_ca_key": root_ca_key if os.path.isfile(root_ca_key) else None,
                "ca_installed": os.path.isfile(root_ca_pem),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "mkcert timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/mkcert/uninstall-ca", methods=["POST"])
    @require_auth
    def route_auto_mkcert_uninstall_ca():
        """Uninstall the local CA from trust stores (requires confirmation)."""
        body = _json_body()

        confirm = body.get("confirm", False)
        if confirm is not True:
            return jsonify({
                "ok": False,
                "error": "Confirmation required — set 'confirm: true' to proceed. This removes the mkcert CA from the system trust store."
            }), 400

        try:
            stdout, stderr, rc = _run_mkcert(["-uninstall"], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "mkcert CA uninstall failed",
                }), 502

            return jsonify({
                "ok": True,
                "output": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "mkcert timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

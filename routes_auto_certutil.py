# Auto-added feature: microsoft/windows (built-in) — CertUtil
# Description: certutil.exe — Windows Certificate Services utility.
#   File hashing (MD5, SHA1, SHA256), certificate management,
#   Base64 encode/decode, CRL management, and more.
# Source: Built-in Windows tool at C:\Windows\system32\certutil.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Certificate Services utility — compute file hashes (MD5/SHA1/SHA256), encode/decode Base64, manage certificates and CRLs, dump certificate stores, generate certificate templates",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/certutil",
    "added": "2026-07-10",
    "command": "certutil <hashfile|-encode|-decode|-store|-cat|-viewstore|-dump|-verifystore|-repairstore>",
}

# Valid hash algorithms for certutil -hashfile
HASH_ALGOS = ["MD5", "SHA1", "SHA256", "SHA384", "SHA512", "SM3"]


def _find_certutil():
    """Locate certutil.exe — always in system32 on Windows."""
    exe = shutil.which("certutil") or shutil.which("certutil.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\certutil.exe",
        r"C:\Windows\SysWOW64\certutil.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_certutil_available():
    exe = _find_certutil()
    if not exe:
        return False
    try:
        # `certutil` with no args prints usage to stdout and exits non-zero;
        # use a benign verb and accept usage exit codes (0 or 1).
        result = subprocess.run([exe, "-?"], capture_output=True, text=True, timeout=10)
        return result.returncode in (0, 1)
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_certutil(args, timeout=30):
    """Run certutil.exe with given args, return (stdout, stderr, exit_code)."""
    exe = _find_certutil()
    if not exe:
        raise RuntimeError("certutil.exe not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _parse_hash_output(output):
    """Parse certutil -hashfile output into structured result."""
    lines = output.strip().splitlines()
    if len(lines) >= 2:
        # First line: "SHA256 hash of file <path>:" — take the leading algorithm token
        algo_line = lines[0].strip().split()[0] if lines[0].strip() else ""
        hash_value = lines[1].strip()
        return algo_line, hash_value
    return None, output.strip()


def _parse_store_output(output):
    """Parse certutil -store output into certificate listing."""
    certs = []
    current_cert = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "====" in stripped:
            if current_cert:
                certs.append(current_cert)
                current_cert = {}
            continue
        if stripped.startswith("Subject:"):
            current_cert["subject"] = stripped[8:].strip()
        elif stripped.startswith("Issuer:"):
            current_cert["issuer"] = stripped[7:].strip()
        elif stripped.startswith("Serial Number:"):
            current_cert["serial"] = stripped[14:].strip()
        elif stripped.startswith("NotBefore:"):
            current_cert["not_before"] = stripped[10:].strip()
        elif stripped.startswith("NotAfter:"):
            current_cert["not_after"] = stripped[9:].strip()
        elif "=" in stripped:
            key, val = stripped.split("=", 1)
            current_cert[key.strip()] = val.strip()
    if current_cert:
        certs.append(current_cert)
    return certs


def register_routes(app, state, require_auth):
    @app.route("/auto/certutil/info", methods=["GET"])
    @require_auth
    def route_auto_certutil_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/certutil/ping", methods=["GET"])
    @require_auth
    def route_auto_certutil_ping():
        exe = _find_certutil()
        available = _is_certutil_available() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "certutil (built-in)",
            "available": available,
            "command": exe or "certutil.exe",
        })

    @app.route("/auto/certutil/hash", methods=["POST"])
    @require_auth
    def route_auto_certutil_hash():
        """Compute file hash using certutil -hashfile."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        filepath = (body.get("file") or "").strip()
        algorithm = (body.get("algorithm") or "SHA256").strip().upper()

        if not filepath:
            return _missing_field("file")
        if algorithm not in HASH_ALGOS:
            return jsonify({
                "ok": False,
                "error": f"unsupported hash algorithm '{algorithm}'. Supported: {', '.join(HASH_ALGOS)}",
            }), 400

        # Verify file exists (on the original path, before WSL→Windows conversion)
        if not os.path.isfile(filepath):
            return jsonify({"ok": False, "error": f"file not found: {filepath}"}), 404

        # Convert WSL path to Windows path if needed (for certutil.exe)
        if filepath.startswith("/mnt/"):
            parts = filepath.split("/")
            if len(parts) >= 3 and len(parts[2]) == 1:
                drive = parts[2].upper()
                win_path = f"{drive}:\\" + "\\".join(parts[3:])
                filepath = win_path

        try:
            stdout, stderr, rc = _run_certutil(["-hashfile", filepath, algorithm], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "certutil hashfile failed",
                    "exit_code": rc,
                }), 502

            algo, hash_val = _parse_hash_output(stdout)
            return jsonify({
                "ok": True,
                "file": filepath,
                "algorithm": algo or algorithm,
                "hash": hash_val,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "certutil hash timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/certutil/encode", methods=["POST"])
    @require_auth
    def route_auto_certutil_encode():
        """Encode a file to Base64 using certutil -encode."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        filepath = (body.get("file") or "").strip()
        if not filepath:
            return _missing_field("file")

        # Convert WSL path to Windows path if needed
        if filepath.startswith("/mnt/"):
            parts = filepath.split("/")
            if len(parts) >= 3 and len(parts[2]) == 1:
                drive = parts[2].upper()
                win_path = f"{drive}:\\" + "\\".join(parts[3:])
                filepath = win_path

        # certutil encodes to a temp .b64 file
        import tempfile
        fd, tmpfile = tempfile.mkstemp(suffix=".b64")
        os.close(fd)  # certutil opens the path itself

        try:
            stdout, stderr, rc = _run_certutil(["-encode", filepath, tmpfile], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "certutil encode failed",
                    "exit_code": rc,
                }), 502

            # Read the encoded file
            if os.path.isfile(tmpfile):
                with open(tmpfile, 'r') as f:
                    encoded = f.read()
            else:
                encoded = ""

            return jsonify({
                "ok": True,
                "file": filepath,
                "encoded": encoded,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "certutil encode timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        finally:
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    @app.route("/auto/certutil/decode", methods=["POST"])
    @require_auth
    def route_auto_certutil_decode():
        """Decode a Base64 file using certutil -decode."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        encoded_file = (body.get("encoded_file") or "").strip()
        if not encoded_file:
            return _missing_field("encoded_file")

        output_file = (body.get("output_file") or "").strip()
        auto_generated = False
        if not output_file:
            # Auto-generate output filename
            import tempfile
            fd, output_file = tempfile.mkstemp(suffix=".decoded")
            os.close(fd)  # certutil opens the path itself
            auto_generated = True

        keep_output = False
        try:
            stdout, stderr, rc = _run_certutil(["-decode", encoded_file, output_file], timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "certutil decode failed",
                    "exit_code": rc,
                }), 502

            # Check output file size
            file_size = os.path.getsize(output_file) if os.path.isfile(output_file) else 0
            keep_output = True

            return jsonify({
                "ok": True,
                "input": encoded_file,
                "output": output_file,
                "size_bytes": file_size,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "certutil decode timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        finally:
            if auto_generated and not keep_output:
                try:
                    os.unlink(output_file)
                except OSError:
                    pass

    @app.route("/auto/certutil/store", methods=["GET"])
    @require_auth
    def route_auto_certutil_store():
        """List certificates in a store (default: MY/CurrentUser)."""
        from flask import request

        store_name = request.args.get("store", "My")
        store_location = request.args.get("location", "CurrentUser")

        try:
            stdout, stderr, rc = _run_certutil(["-store", store_location, store_name], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "certutil store query failed",
                    "exit_code": rc,
                }), 502

            certs = _parse_store_output(stdout)
            return jsonify({
                "ok": True,
                "store": f"{store_location}\\{store_name}",
                "certificates": certs,
                "count": len(certs),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "certutil store query timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/certutil/csr", methods=["POST"])
    @require_auth
    def route_auto_certutil_csr():
        """Generate a certificate signing request (CSR) using an existing INF file."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        inf_file = (body.get("inf_file") or "").strip()
        output_file = (body.get("output_file") or "").strip()

        if not inf_file:
            return _missing_field("inf_file")

        args = ["-newreq"]
        if output_file:
            args.extend([output_file, inf_file])
        else:
            args.append(inf_file)

        try:
            stdout, stderr, rc = _run_certutil(args, timeout=30)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "certutil -newreq failed",
                    "exit_code": rc,
                }), 502
            return jsonify({
                "ok": True,
                "inf_file": inf_file,
                "output_file": output_file or "(auto-generated)",
                "stdout": stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "certutil CSR generation timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

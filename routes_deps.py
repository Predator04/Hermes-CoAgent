"""Dependency inspection and installation routes."""

import importlib
import re
import subprocess
import sys
from importlib import metadata

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import SERVER_LOG, _wrap_registered_blueprint_routes


deps_bp = Blueprint("deps", __name__)

PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.\-\[\],=<>!~]+$")
PACKAGE_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
NO_MODULE_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")

ALLOWED_PACKAGES = {
    "flask",
    "waitress",
    "mss",
    "pywinauto",
    "pytesseract",
    "pillow",
    "pyautogui",
    "pygetwindow",
    "pyperclip",
    "pystray",
    "psutil",
    "dxcam",
    "playwright",
    "google-api-python-client",
    "google-auth-oauthlib",
    "google-auth-httplib2",
    "win11toast",
    "flask-sock",
    "opencv-python",
    "numpy",
}

TRACKED_DEPS = [
    {"module": "flask", "package": "flask"},
    {"module": "waitress", "package": "waitress"},
    {"module": "mss", "package": "mss"},
    {"module": "pywinauto", "package": "pywinauto"},
    {"module": "psutil", "package": "psutil"},
    {"module": "PIL", "package": "pillow"},
    {"module": "pyautogui", "package": "pyautogui"},
    {"module": "win11toast", "package": "win11toast"},
    {"module": "dxcam", "package": "dxcam", "lazy": True},
    {"module": "playwright", "package": "playwright"},
    {"module": "googleapiclient", "package": "google-api-python-client"},
    {"module": "google_auth_oauthlib", "package": "google-auth-oauthlib"},
    {"module": "google.auth", "package": "google-auth"},
    {"module": "google.auth.transport.requests", "package": "google-auth-httplib2"},
]


def _error(message: str, status: int = 400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def _valid_package(package):
    return isinstance(package, str) and 1 <= len(package) <= 160 and PACKAGE_RE.fullmatch(package)


def _package_name(package):
    if not isinstance(package, str):
        return ""
    match = PACKAGE_NAME_RE.match(package)
    if not match:
        return ""
    return match.group(1).lower().replace("_", "-")


def _allowed_package(package):
    return _package_name(package) in ALLOWED_PACKAGES


def _package_for_module(module_name):
    root = module_name.split(".", 1)[0]
    for dep in TRACKED_DEPS:
        if dep["module"] == module_name or dep["module"].split(".", 1)[0] == root:
            return dep["package"]
    return root.replace("_", "-")


def _is_lazy(module_name):
    for dep in TRACKED_DEPS:
        if dep.get("lazy") and (dep["module"] == module_name or dep["module"].split(".", 1)[0] == module_name.split(".", 1)[0]):
            return True
    return False


def _check_module(module_name, package=None):
    if _is_lazy(module_name):
        # Lazy modules: check if pip package exists without importing
        pkg_name = package or module_name.split(".", 1)[0].replace("_", "-")
        try:
            version = metadata.version(pkg_name)
            return {"module": module_name, "package": pkg_name, "installed": True, "version": version, "lazy": True}
        except metadata.PackageNotFoundError:
            return {"module": module_name, "package": pkg_name, "installed": False, "version": None, "lazy": True}
        except Exception:
            pass
    try:
        importlib.import_module(module_name)
        installed = True
    except ImportError:
        installed = False
    version = None
    if installed:
        for candidate in (package, module_name, module_name.split(".", 1)[0]):
            if not candidate:
                continue
            try:
                version = metadata.version(candidate)
                break
            except metadata.PackageNotFoundError:
                continue
            except Exception:
                break
    return {"module": module_name, "package": package or module_name, "installed": installed, "version": version}


def _pip_install(package):
    if not _valid_package(package):
        raise ValueError("Invalid package spec")
    if not _allowed_package(package):
        raise ValueError("Package is not in the allowed install list")
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True,
        text=True,
        timeout=600,
    )


@deps_bp.route("/deps", methods=["GET"])
def route_deps_index():
    deps = [_check_module(dep["module"], dep["package"]) for dep in TRACKED_DEPS]
    return jsonify({"deps": deps, "count": len(deps)})


@deps_bp.route("/deps/check", methods=["POST"])
def route_deps_check():
    data = _json_payload()
    package = data.get("package")
    if not isinstance(package, str) or not package.strip():
        return _error("package is required")
    module = data.get("module") if isinstance(data.get("module"), str) else package
    tracked = next((dep for dep in TRACKED_DEPS if dep["package"] == package or dep["module"] == module), None)
    if tracked:
        return jsonify(_check_module(tracked["module"], tracked["package"]))
    return jsonify(_check_module(module, package))


@deps_bp.route("/deps/install", methods=["POST"])
def route_deps_install():
    data = _json_payload()
    package = data.get("package")
    if not _valid_package(package):
        return _error("package must be a valid pip package spec")
    if not _allowed_package(package):
        return _error("package is not in the allowed install list", package=package)
    try:
        result = _pip_install(package)
        return jsonify({
            "package": package,
            "returncode": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
            "installed": result.returncode == 0,
        }), 200 if result.returncode == 0 else 500
    except Exception as e:
        return _error(str(e), 500, type=type(e).__name__)


@deps_bp.route("/deps/install-all", methods=["POST"])
def route_deps_install_all():
    results = []
    for dep in TRACKED_DEPS:
        status = _check_module(dep["module"], dep["package"])
        if status["installed"]:
            results.append({**status, "action": "skipped"})
            continue
        try:
            result = _pip_install(dep["package"])
            results.append({
                **status,
                "action": "installed",
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            })
        except Exception as e:
            results.append({**status, "action": "failed", "error": str(e), "type": type(e).__name__})
    return jsonify({"results": results, "count": len(results)})


@deps_bp.route("/deps/auto", methods=["POST"])
def route_deps_auto():
    if not SERVER_LOG.exists():
        return jsonify({"installed": [], "missing": [], "errors": [], "log": str(SERVER_LOG)})
    try:
        lines = SERVER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
    except Exception as e:
        return _error(f"Cannot read log: {e}", 500)
    missing = []
    for line in lines:
        if "ImportError" not in line and "No module named" not in line and "ModuleNotFoundError" not in line:
            continue
        for match in NO_MODULE_RE.findall(line):
            module = match.split(".", 1)[0]
            if module and module not in missing:
                missing.append(module)
    results = []
    for module in missing[:10]:
        package = _package_for_module(module)
        if not _allowed_package(package):
            return _error("auto-install package is not in the allowed install list", package=package, module=module)
        try:
            result = _pip_install(package)
            results.append({
                "module": module,
                "package": package,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            })
        except Exception as e:
            results.append({"module": module, "package": package, "error": str(e), "type": type(e).__name__})
    return jsonify({"missing": missing, "results": results, "count": len(results)})


def register_routes(app, state, require_auth):
    app.register_blueprint(deps_bp)
    _wrap_registered_blueprint_routes(app, deps_bp.name, require_auth)

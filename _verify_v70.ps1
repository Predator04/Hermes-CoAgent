# _verify_v70.ps1 - Static verification for Hermes CoAgent v7.0
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $pythonCmd) {
    throw "Python not found on PATH"
}
$python = $pythonCmd.Source

$files = @(
    "hermes_coagent.py",
    "shared.py",
    "routes_mouse.py",
    "routes_ocr.py",
    "routes_uia.py",
    "routes_file.py",
    "routes_media.py",
    "routes_v63.py",
    "coagent_features.py",
    "computer_use_mcp.py",
    "uia_engine.py"
)

foreach ($file in $files) {
    if (-not (Test-Path $file)) {
        throw "Missing required file: $file"
    }
}

& $python -m py_compile @files
if ($LASTEXITCODE -ne 0) {
    throw "Python syntax verification failed"
}

$check = @'
from pathlib import Path
import ast
import json
import re
import sys

root = Path.cwd()

def read(name):
    return (root / name).read_text(encoding="utf-8")

def assigned_literal(module_text, name):
    tree = ast.parse(module_text)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} assignment not found")

shared = read("shared.py")
version = re.search(r'^VERSION\s*=\s*"([^"]+)"', shared, re.M)
build = re.search(r'^BUILD\s*=\s*"([^"]+)"', shared, re.M)
assert version and version.group(1) == "7.0", "shared.VERSION must be 7.0"
assert build and build.group(1) == "2026-06-18", "shared.BUILD must be 2026-06-18"

hermes = read("hermes_coagent.py")
prefixes = assigned_literal(hermes, "AUTH_EXEMPT_PREFIXES")
paths = assigned_literal(hermes, "AUTH_EXEMPT_PATHS")
assert len(prefixes) == 13, f"AUTH_EXEMPT_PREFIXES count is {len(prefixes)}, expected 13"
assert len(paths) >= 20, f"AUTH_EXEMPT_PATHS count is {len(paths)}, expected 20+"
assert "from routes_v63 import register_routes as reg_v63" in hermes, "routes_v63 import missing"
assert "reg_v63(app, state, require_auth)" in hermes, "routes_v63 registration missing"

for feature in ("modular_routes", "sse_mcp", "health_watchdog", "thread_pool_4"):
    assert feature in hermes, f"/version feature missing: {feature}"

route_files = [
    "hermes_coagent.py",
    "routes_mouse.py",
    "routes_ocr.py",
    "routes_uia.py",
    "routes_file.py",
    "routes_media.py",
    "routes_v63.py",
]
routes = set()
for file in route_files:
    text = read(file)
    routes.update(re.findall(r'@app\.route\("([^"]+)"', text))

required = {
    "/mouse/move", "/mouse/click", "/mouse/dblclick", "/mouse/rclick",
    "/mouse/drag", "/mouse/scroll", "/key/type", "/key/press", "/chain",
    "/act", "/cursor/pos", "/copilot/mode", "/input/send",
    "/ocr/find", "/visual/find", "/crop", "/describe", "/screen",
    "/screen/jpeg", "/screen/base64", "/screen/fresh", "/screen/diag",
    "/uia/tree", "/uia/snapshot", "/uia/find/<name>", "/uia/click",
    "/uia/find-cmb", "/uia/diag", "/uia/window-tree", "/uia/element/find",
    "/uia/element/click-by-name", "/uia/element/click-by-index",
    "/som/screenshot", "/som/image", "/som/cache/clear", "/som/bridge",
    "/som/per-window", "/som/point", "/uia/accel-reg",
    "/file/list", "/file/read", "/file/write", "/file/delete",
    "/app/open", "/app/run", "/power/sleep", "/power/shutdown",
    "/power/restart", "/power/lock", "/power/cancel",
    "/wallpaper/set", "/wallpaper/cycle", "/wallpaper/random",
    "/monitors/layout", "/windows", "/windows/activate", "/clipboard/get",
    "/clipboard/set", "/tts/speak", "/scheduler/list", "/scheduler/add",
    "/scheduler/remove", "/scheduler/run", "/macro/list", "/macro/save",
    "/macro/run", "/macro/record", "/macro/delete", "/replay",
    "/voice/toggle", "/tunnel/start", "/tunnel/stop", "/tunnel/status",
    "/search/files", "/emergency/stop", "/emergency/resume",
    "/emergency/status", "/monitors", "/stats", "/history", "/events",
    "/features", "/cursor/enable", "/cursor/style", "/cursor/status",
    "/recording/start", "/recording/stop", "/recording/status",
    "/wait/element", "/wait/element-gone", "/stabilize",
    "/version", "/ping", "/health",
}
missing = sorted(required - routes)
assert not missing, "Missing routes: " + ", ".join(missing)

media = read("routes_media.py")
assert '"/features"' not in media, "v6.3 feature routes still live in routes_media.py"
v63 = read("routes_v63.py")
assert 'coagent_features' in v63, "routes_v63.py must call coagent_features"

cursor = read("coagent_features.py")
assert "_CURSOR_SIZE = 48" in cursor, "cursor size must be 48"
assert "_CURSOR_COLOR = 0xFF4400" in cursor, "cursor color must be 0xFF4400"
assert "_WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE | _WS_EX_TOPMOST" in cursor, "cursor extended style incomplete"
assert "SetLayeredWindowAttributes(hwnd, 0, 200" in cursor, "cursor layered alpha missing"

mcp = read("computer_use_mcp.py")
assert '"--http" in sys.argv or "--sse" in sys.argv' in mcp, "MCP --sse alias missing"
assert '"--port" in sys.argv' in mcp, "MCP --port support missing"
assert "port = 8001" in mcp, "MCP SSE default port must be 8001"

ocr = read("routes_ocr.py")
assert "def _check_winrt_version" in ocr, "WinRT version diagnostic missing"
assert "except (ImportError, AttributeError, TypeError)" in ocr, "WinRT OCR fallback exceptions missing"

print(json.dumps({
    "status": "ok",
    "version": version.group(1),
    "build": build.group(1),
    "route_count": len(routes),
    "auth_exempt_prefixes": len(prefixes),
    "auth_exempt_paths": len(paths),
}, indent=2))
'@

$checkPath = Join-Path $PSScriptRoot "_verify_v70_runtime.py"
try {
    Set-Content -Path $checkPath -Value $check -Encoding utf8
    & $python $checkPath
    if ($LASTEXITCODE -ne 0) {
        throw "v7.0 structural verification failed"
    }
} finally {
    Remove-Item -Path $checkPath -Force -ErrorAction SilentlyContinue
}

Write-Host "v7.0 verification passed"

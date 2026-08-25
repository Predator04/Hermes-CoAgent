"""
Webcam capture route for CoAgent.
Provides a clean /webcam/capture endpoint using multiple fallback methods.
"""

import base64
import json
import subprocess
import uuid
from datetime import datetime
from pathlib import Path


def register_routes(app, jsonify, request, COAGENT_DIR, _log, _json_body, require_auth):
    """Register webcam routes with the Flask app."""

    @app.route("/webcam/capture", methods=["POST"])
    @require_auth
    def route_webcam_capture():
        """Take a photo with the webcam. Returns base64 JPEG + saved file path."""
        d = _json_body() or {}
        quality = d.get("quality", 85)
        
        shots_dir = Path(COAGENT_DIR) / "camera_shots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        fname = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
        path = shots_dir / fname
        
        # Try methods in order of reliability
        methods = [
            ("PowerShell MediaCapture", _capture_ps_media),
            ("FFmpeg DShow", _capture_ffmpeg),
        ]
        
        last_error = None
        for name, method in methods:
            try:
                result = method(path, quality)
            except Exception as e:
                last_error = f"{name}: {e}"
                continue
            if result:
                _log(f"Webcam capture via {name}: {fname}")
                break
            last_error = f"{name}: returned no image"
        else:
            _log(f"All webcam capture methods failed: {last_error}")
            return jsonify({
                "success": False,
                "error": f"All capture methods failed. Last: {last_error}"
            }), 500
        
        # Read and return
        with open(path, "rb") as f:
            img_data = f.read()
        
        return jsonify({
            "success": True,
            "path": str(path),
            "filename": fname,
            "size_bytes": len(img_data),
            "image": base64.b64encode(img_data).decode(),
            "timestamp": datetime.now().isoformat(),
        })

    @app.route("/webcam/list", methods=["GET"])
    @require_auth
    def route_webcam_list():
        """List available webcam devices."""
        devices = _list_cameras_ps()
        if not devices:
            devices = _list_cameras_ffmpeg()
        return jsonify({"success": True, "devices": devices})


def _capture_ps_media(path, quality=85):
    """Capture via PowerShell MediaCapture API (most reliable on Win10+)."""
    shots_dir = str(Path(path).parent)
    fname = Path(path).name
    script = rf'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{$_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation`1"}})[0]

function Await($WinRtTask, $ResultType) {{
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}}

[Windows.Media.Capture.MediaCapture, Windows.Media.Capture, ContentType=WindowsRuntime] | Out-Null
$mediaCapture = New-Object Windows.Media.Capture.MediaCapture
$settings = New-Object Windows.Media.Capture.MediaCaptureInitializationSettings
$settings.StreamingCaptureMode = [Windows.Media.Capture.StreamingCaptureMode]::Video
$settings.PhotoCaptureSource = [Windows.Media.Capture.PhotoCaptureSource]::Photo

try {{
    $initOp = $mediaCapture.InitializeAsync($settings)
    Await $initOp ([Windows.Media.Capture.MediaCaptureInitializationSettings])
}} catch {{
    Write-Error "MediaCapture init failed: $_"
    exit 1
}}

$folderOp = [Windows.Storage.StorageFolder]::GetFolderFromPathAsync("{shots_dir}")
$folder = Await $folderOp ([Windows.Storage.StorageFolder])
$fileOp = $folder.CreateFileAsync("{fname}", [Windows.Storage.CreationCollisionOption]::ReplaceExisting)
$file = Await $fileOp ([Windows.Storage.StorageFile])
$captureOp = $mediaCapture.CapturePhotoToStorageFileAsync(
    [Windows.Media.MediaProperties.ImageEncodingProperties]::CreateJpeg(), $file
)
Await $captureOp ([void])
'''
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30
        )
        return Path(path).exists() and Path(path).stat().st_size > 1000
    except Exception:
        return False


def _capture_ps_winforms(path, quality=85):
    """Capture via PowerShell Windows Forms + webcam control."""
    script = rf'''
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$outputPath = "{path}"

# Try using the webcam via WMI/Devices
$cameras = Get-CimInstance -ClassName Win32_PnPEntity | Where-Object {{
    $_.PNPClass -eq "Camera" -or $_.Name -match "camera|webcam|usb video"
}}
$output = $cameras | ConvertTo-Json -Compress
Write-Output $output
'''
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=15
        )
        return Path(path).exists() and Path(path).stat().st_size > 1000
    except Exception:
        return False


def _capture_ffmpeg(path, quality=85):
    """Capture via ffmpeg DShow."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found")
    
    # Enumerate cameras first
    enum = subprocess.run(
        [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True, text=True, timeout=10
    )
    
    # Parse camera names from ffmpeg output
    cameras = []
    for line in enum.stderr.split("\n"):
        if '"' in line and ("video" in line.lower() or "camera" in line.lower() or "usb" in line.lower()):
            import re
            m = re.search(r'"([^"]+)"', line)
            if m:
                cameras.append(m.group(1))
    
    # Try each camera
    for cam in (cameras or ["USB Camera", "HD Camera", "Integrated Camera", "USB2.0 Camera", "HP HD Camera"]):
        cmd = [
            ffmpeg, "-f", "dshow", "-i", f"video={cam}",
            "-frames:v", "1", "-q:v", "3", str(path), "-y"
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=15)
            if Path(path).exists() and Path(path).stat().st_size > 1000:
                return True
        except Exception:
            continue
    
    return False


def _find_ffmpeg():
    """Find ffmpeg executable."""
    import shutil
    paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    ]
    for p in paths:
        if Path(p).exists():
            return p
    return shutil.which("ffmpeg")


def _list_cameras_ps():
    """List cameras via PowerShell."""
    script = '''
Get-CimInstance -ClassName Win32_PnPEntity | Where-Object {
    $_.PNPClass -eq "Camera" -or $_.Name -match "camera|webcam"
} | Select-Object Name,Status,PNPClass | ConvertTo-Json -Compress
'''
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip():
            devices = json.loads(result.stdout)
            if isinstance(devices, dict):
                devices = [devices]
            return devices
    except Exception:
        pass
    return []


def _list_cameras_ffmpeg():
    """List cameras via ffmpeg."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return []
    enum = subprocess.run(
        [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True, text=True, timeout=10
    )
    cameras = []
    import re
    for line in enum.stderr.split("\n"):
        m = re.search(r'"([^"]+)"', line)
        if m and ("camera" in line.lower() or "video" in line.lower()):
            cameras.append({"name": m.group(1), "source": "ffmpeg"})
    return cameras

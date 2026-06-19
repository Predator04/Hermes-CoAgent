# One-shot CoAgent + Hermes launch
# Usage: powershell -File launch_all.ps1
# Launches: CoAgent server on desktop, wakes MCP in Hermes config
# Set MCP_FAST=1 env var for fast start

$ErrorActionPreference = "Continue"

# Auto-detect paths relative to this script
$coagentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonwCandidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe"
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe"
    "C:\Program Files\Python313\pythonw.exe"
    "C:\Python313\pythonw.exe"
)
$pythonw = $pythonwCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonw) {
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { $pythonw = $cmd.Source }
}
if (-not $pythonw) { throw "pythonw.exe not found" }
$python = "python.exe"

Write-Output "=========================================="
Write-Output " Hermes CoAgent Launch (Path-Relative)"
Write-Output "=========================================="
Write-Output "Workspace: $coagentDir"

# ── Step 1: Kill stale CoAgent processes ──
Write-Output "[1/6] Cleaning stale processes..."
Get-Process -Name "python*" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
        if ($cmdLine -match "hermes_coagent" -or $cmdLine -match "coagent_tray" -or $cmdLine -match "tray_icon.py" -or $cmdLine -match "screenshot_relay.py") {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            Write-Output "  Killed PID $($_.Id)"
        }
    } catch {}
}
Start-Sleep -Milliseconds 500

# ── Step 2: Launch CoAgent server ──
Write-Output "[2/6] Starting CoAgent server..."
$serverArgs = @(
    "`"$coagentDir\\hermes_coagent.py`""
    "--secure"
    "--allow-external"
)
$env:MCP_FAST = "1"
$serverProc = Start-Process -FilePath $pythonw -ArgumentList $serverArgs -WorkingDirectory $coagentDir -PassThru -WindowStyle Hidden -ErrorAction SilentlyContinue
if (-not $serverProc) {
    # Fallback to python.exe if pythonw not found
    $serverProc = Start-Process -FilePath "python.exe" -ArgumentList $serverArgs -WorkingDirectory $coagentDir -PassThru -WindowStyle Hidden
}
Write-Output "  Server PID: $($serverProc.Id)"

Start-Sleep -Seconds 2

# ── Step 3: Launch tray icon on Session 1 ──
Write-Output "[3/6] Launching tray icon..."
$trayScript = Join-Path $coagentDir "tray_icon.py"
$trayArgs = @(
    "`"$trayScript`""
    "9123"
    "9124"
)
try {
    Start-Process -FilePath $pythonw -ArgumentList $trayArgs -WorkingDirectory $coagentDir -WindowStyle Hidden -ErrorAction Stop | Out-Null
    Write-Output "  Tray launch requested with pythonw.exe"
} catch {
    Write-Output "  Tray launch failed: $($_.Exception.Message)"
}

# --- Step 4: Ensure screenshot relay ---
Write-Output "[4/6] Ensuring screenshot relay..."
Start-Sleep -Seconds 1
$relayOk = $false
try {
    $relay = Invoke-WebRequest -Uri "http://127.0.0.1:9124/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    $relayOk = ($relay.StatusCode -eq 200)
} catch {}
if ($relayOk) {
    Write-Output "  Screenshot relay OK (port 9124)"
} else {
    $relayScript = Join-Path $coagentDir "screenshot_relay.py"
    if (Test-Path $relayScript) {
        $relayArgs = @("`"$relayScript`"")
        try {
            Start-Process -FilePath $pythonw -ArgumentList $relayArgs -WorkingDirectory $coagentDir -WindowStyle Hidden -ErrorAction Stop | Out-Null
            Write-Output "  Screenshot relay fallback launched"
        } catch {
            Write-Output "  Screenshot relay launch failed: $($_.Exception.Message)"
        }
    } else {
        Write-Output "  screenshot_relay.py not found"
    }
}

# ── Step 5: Verify server is running ──
Write-Output "[5/6] Verifying server..."
Start-Sleep -Seconds 2
try {
    $ping = Invoke-WebRequest -Uri "http://127.0.0.1:9123/ping" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($ping.StatusCode -eq 200) {
        Write-Output "  ✅ Server OK (port 9123)"
    }
} catch {
    Write-Output "  ⚠️  Server not responding yet - check coagent_server.log"
}

# ── Step 6: Done ──
Write-Output "[6/6] Launch complete!"
Write-Output ""
Write-Output "  Dashboard: http://localhost:9123/"
Write-Output "  Dashboard2: http://localhost:9123/dashboard2"
Write-Output "  Tray icon: Look for purple 'C' in system tray"
Write-Output ""
Write-Output "  MCP server auto-launches on first tool call (MCP_FAST=1)"
Write-Output "  Auth token: check coagent_server.log for '[SECURE]'"

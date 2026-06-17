# One-shot CoAgent + Hermes launch
# Usage: powershell -File launch_all.ps1
# Launches: CoAgent server on desktop, wakes MCP in Hermes config
# Set MCP_FAST=1 env var for fast start

$ErrorActionPreference = "Continue"

# Auto-detect paths relative to this script
$coagentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = "pythonw.exe"
$python = "python.exe"

Write-Output "=========================================="
Write-Output " Hermes CoAgent Launch (Path-Relative)"
Write-Output "=========================================="
Write-Output "Workspace: $coagentDir"

# ── Step 1: Kill stale CoAgent processes ──
Write-Output "[1/5] Cleaning stale processes..."
Get-Process -Name "python*" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
        if ($cmdLine -match "hermes_coagent" -or $cmdLine -match "coagent_tray") {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            Write-Output "  Killed PID $($_.Id)"
        }
    } catch {}
}
Start-Sleep -Milliseconds 500

# ── Step 2: Launch CoAgent server ──
Write-Output "[2/5] Starting CoAgent server..."
$serverArgs = @(
    "$coagentDir\hermes_coagent.py"
    "--secure"
)
$env:MCP_FAST = "1"
$serverProc = Start-Process -FilePath "pythonw.exe" -ArgumentList $serverArgs -WorkingDirectory $coagentDir -PassThru -WindowStyle Hidden -ErrorAction SilentlyContinue
if (-not $serverProc) {
    # Fallback to python.exe if pythonw not found
    $serverProc = Start-Process -FilePath "python.exe" -ArgumentList $serverArgs -WorkingDirectory $coagentDir -PassThru -WindowStyle Hidden
}
Write-Output "  Server PID: $($serverProc.Id)"

Start-Sleep -Seconds 2

# ── Step 3: Launch tray icon on Session 1 ──
Write-Output "[3/5] Launching tray icon..."
& "$coagentDir\launch_fixed.ps1"

# ── Step 4: Verify server is running ──
Write-Output "[4/5] Verifying server..."
Start-Sleep -Seconds 2
try {
    $ping = Invoke-WebRequest -Uri "http://127.0.0.1:9123/ping" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($ping.StatusCode -eq 200) {
        Write-Output "  ✅ Server OK (port 9123)"
    }
} catch {
    Write-Output "  ⚠️  Server not responding yet - check coagent_server.log"
}

# ── Step 5: Done ──
Write-Output "[5/5] Launch complete!"
Write-Output ""
Write-Output "  Dashboard: http://localhost:9123/"
Write-Output "  Dashboard2: http://localhost:9123/dashboard2"
Write-Output "  Tray icon: Look for purple 'C' in system tray"
Write-Output ""
Write-Output "  MCP server auto-launches on first tool call (MCP_FAST=1)"
Write-Output "  Auth token: check coagent_server.log for '[SECURE]'"

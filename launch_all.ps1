# One-shot CoAgent + Hermes launch
# Usage: powershell -File launch_all.ps1
# Launches: CoAgent server on desktop, wakes MCP in Hermes config
# Set MCP_FAST=1 env var for fast start

$ErrorActionPreference = "Continue"

$coagentDir = "C:\Users\Admin\Desktop\Hermes CoAgent"
$pythonw = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe"
$python = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
$hermesHome = "C:\Users\Admin\.hermes"

Write-Output "=========================================="
Write-Output " Hermes CoAgent Launch v2.0 (Optimized)"
Write-Output "=========================================="

# ── Step 1: Kill stale CoAgent processes ──
Write-Output "[1/5] Cleaning stale processes..."
Get-Process -Name "python*" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
        if ($cmdLine -match "hermes_coagent" -or $cmdLine -match "coagent_tray") {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            Write-Output "  Killed PID $($_.Id) ($($cmdLine -replace '.{80}', '$0...'))"
        }
    } catch {}
}
Start-Sleep -Milliseconds 500

# ── Step 2: Launch CoAgent server ──
Write-Output "[2/5] Starting CoAgent server..."
$env:MCP_FAST = "1"
Start-Process -FilePath $pythonw -ArgumentList "$coagentDir\hermes_coagent.py" -WindowStyle Hidden
Write-Output "  PID: $( (Get-Process -Name pythonw | Select-Object -Last 1).Id )"

# ── Step 3: Wait for CoAgent ──
Write-Output "[3/5] Waiting for CoAgent (max 20s)..."
$maxWait = 20
for ($i = 0; $i -lt $maxWait; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:9123/" -UseBasicParsing -TimeoutSec 1
        if ($resp.StatusCode -eq 200) {
            $body = $resp.Content | ConvertFrom-Json
            Write-Output "  Ready! Version: $($body.version) (${i}s)"
            break
        }
    } catch {}
    if ($i -eq 0) { Write-Output "  Waiting..." }
    Start-Sleep -Seconds 1
}
if ($i -ge $maxWait) { Write-Warning "  CoAgent not responding after ${maxWait}s" }

# ── Step 4: Enable fast mode in Hermes MCP ──
Write-Output "[4/5] Configuring Hermes MCP for fast start..."
$configPath = "$hermesHome\config.yaml"
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw
    # Add MCP_FAST=1 env to windows-computer-use MCP server if not present
    $search = "windows-computer-use:"
    $replace = "windows-computer-use:`n    env:`n      MCP_FAST: '1'"
    $newConfig = $config -replace [regex]::Escape($search), $replace
    # Check if it already has env: block
    if ($config -match "windows-computer-use:\s*\n\s+command:" -or $config -match "windows-computer-use:\s*\n\s+env:") {
        $newConfig = $config -replace "MCP_FAST: '1'", "MCP_FAST: '1'"  # no-op, already there
    }
    $config | Out-File -FilePath "$configPath.tmp"
    $newConfig | Out-File -FilePath $configPath
    Write-Output "  Config updated"
}

# ── Step 5: Final status ──
Write-Output "[5/5] Final status check..."
try {
    $status = Invoke-WebRequest -Uri "http://localhost:9123/" -UseBasicParsing -TimeoutSec 2
    $body = $status.Content | ConvertFrom-Json
    Write-Output ""
    Write-Output "=========================================="
    Write-Output " ALL SYSTEMS READY"
    Write-Output "=========================================="
    Write-Output " CoAgent:      http://localhost:9123/"
    Write-Output " Dashboard2:   http://localhost:9123/dashboard2"
    Write-Output " MCP:          Active via Hermes config"
    Write-Output " Fast mode:    ON (lazy imports)"
    Write-Output ""
    Write-Output " Commands:"
    Write-Output "   powershell -File send_telegram_file.ps1 -FilePath `"C:\path\to\file.apk`""
    Write-Output "=========================================="
} catch {
    Write-Warning "CoAgent not responding - check manually"
}

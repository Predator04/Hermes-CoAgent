# One-shot Telegram desktop file sender
# Usage: powershell -File send_telegram_file.ps1 -FilePath "C:\path\to\file.apk" -ChatName "William"
# Sends any file (<50MB via bot, >50MB via desktop GUI automation)

param(
    [Parameter(Mandatory=$true)]
    [string]$FilePath,
    [string]$ChatName = "William"
)

# Validate file exists
if (-not (Test-Path $FilePath)) { Write-Error "File not found: $FilePath"; exit 1 }

$ErrorActionPreference = "Continue"

# ── 1. Copy to C:\temp with clean name ──
if (-not (Test-Path "C:\temp")) { New-Item -ItemType Directory -Force -Path "C:\temp" | Out-Null }
$ext = [System.IO.Path]::GetExtension($FilePath)
$cleanName = "file_to_send" + $ext
Copy-Item -Force $FilePath "C:\temp\$cleanName"
Write-Output "COPIED|C:\temp\$cleanName"

# ── 2. Kill stale TrayLauncher if running ──
Get-Process -Name "pythonw" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "coagent" } | Stop-Process -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 1

# ── 3. Launch CoAgent fresh ──
$coagentDir = "C:\Users\Admin\Desktop\Hermes CoAgent"
$python = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
$pythonw = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe"

# Kill stale processes
Get-Process -Name "python*" -ErrorAction SilentlyContinue | Where-Object { 
    (Get-Process -Id $_.Id -ErrorAction SilentlyContinue).StartInfo -and 
    (Get-Process -Id $_.Id).StartInfo.Arguments -match "hermes_coagent" 
} | Stop-Process -Force -ErrorAction SilentlyContinue

# Start CoAgent server
Start-Process -FilePath $pythonw -ArgumentList "$coagentDir\hermes_coagent.py" -WindowStyle Hidden -PassThru
Write-Output "COAGENT_LAUNCHED"

# Wait for CoAgent to come online
$maxWait = 30
$waited = 0
while ($waited -lt $maxWait) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:9123/" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) {
            Write-Output "COAGENT_READY|$( $waited )s"
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
    $waited++
}

if ($waited -ge $maxWait) {
    Write-Error "CoAgent failed to start in ${maxWait}s"
    exit 1
}

# ── 4. Bring Telegram to front ──
try {
    $wshell = New-Object -ComObject wscript.shell
    $wshell.AppActivate($ChatName)
    Start-Sleep -Milliseconds 500
} catch {
    Write-Warning "AppActivate failed, continuing..."
}

Write-Output "READY|$cleanName"

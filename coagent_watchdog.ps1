# PowerShell Watchdog Script for Hermes CoAgent v7.6
# Runs every 60 seconds via Windows Task Scheduler.
# Checks CoAgent health, restarts if dead.
# Logs to C:\Windows\Temp\coagent_watchdog.log

param(
    [string]$CoAgentDir = "C:\Users\Admin\Desktop\Hermes CoAgent",
    [string]$PythonPath = "C:\Program Files\Python312\python.exe",
    [string]$Token = "YOUR_TOKEN_HERE",
    [int]$Port = 9123,
    [string]$LogFile = "C:\Windows\Temp\coagent_watchdog.log"
)

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp | $Message" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Test-CoAgentAlive {
    $url = "http://127.0.0.1:$Port/ping"
    try {
        $response = Invoke-WebRequest -Uri $url -Method GET -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        $data = $response.Content | ConvertFrom-Json
        if ($data.status -eq "pong") {
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

function Get-CoAgentPid {
    $procs = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue
    $escapedDir = $CoAgentDir.Replace('\', '\\')
    foreach ($p in $procs) {
        if ($p.CommandLine -match $escapedDir -and $p.CommandLine -match "hermes_coagent" -and $p.CommandLine -notmatch "watchdog") {
            return $p.ProcessId
        }
    }
    return $null
}

Function Start-CoAgent {
    # Write a temp batch file with no spaces in path
    $tempBat = "C:\Windows\Temp\coagent_launch.bat"
    $pythonExe = "C:\Program Files\Python312\python.exe"
    $coagentPy = "$CoAgentDir\hermes_coagent.py"
    @"
@echo off
cd /d "$CoAgentDir"
start "" "$pythonExe" "$coagentPy" --token=$Token --allow-external
"@ | Out-File -FilePath $tempBat -Encoding ASCII -Force

    # Create and run a one-shot interactive task (Session 1)
    $launchTaskName = "HermesCoAgent-Launch"
    schtasks /Delete /TN $launchTaskName /F 2>$null
    schtasks /Create /TN $launchTaskName /TR "$tempBat" /SC ONCE /ST 00:00 /RU Admin /IT /RL HIGHEST /F 2>$null
    Start-Sleep -Milliseconds 500
    schtasks /Run /TN $launchTaskName 2>$null
    Start-Sleep -Seconds 10
}

# ---- Main ----
Write-Log "Watchdog tick starting..."

$alive = Test-CoAgentAlive
$procId = Get-CoAgentPid

if (-not $alive -and -not $procId) {
    Write-Log "CoAgent is DEAD (no PID, no ping). Restarting..."
    Start-CoAgent
    Start-Sleep -Seconds 3
    if (Test-CoAgentAlive) {
        Write-Log "CoAgent restarted SUCCESSFULLY on port $Port"
    } else {
        Write-Log "CoAgent RESTART FAILED - check $CoAgentDir for errors"
    }
} elseif (-not $alive -and $procId) {
    Write-Log "CoAgent PID $procId exists but NOT RESPONDING. Killing and restarting..."
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-CoAgent
} else {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/version" -UseBasicParsing -TimeoutSec 5
        $ver = ($resp.Content | ConvertFrom-Json).agent
        Write-Log "CoAgent $ver is healthy (PID: $procId)"
    } catch {
        Write-Log "CoAgent alive but /version failed: $_"
    }
}

# Start screenshot relay if missing
# Check if screenshot relay is running (port 9124 listening)
$relayRunning = $false
try {
    $relayResp = Invoke-WebRequest -Uri "http://127.0.0.1:9124/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    $relayRunning = $true
} catch {}
if (-not $relayRunning) {
    $relayScript = "$CoAgentDir\screenshot_relay.py"
    if (Test-Path $relayScript) {
        Start-Process -FilePath $PythonPath -ArgumentList "$relayScript 9124" -WindowStyle Hidden
        Write-Log "Screenshot relay started"
    } else {
        Write-Log "screenshot_relay.py not found at $relayScript"
    }
}

Write-Log "Watchdog tick complete."

# One-shot CoAgent + Hermes launch
# Usage: powershell -File launch_all.ps1
# Launches: CoAgent server on desktop, tray icon, and screenshot relay.
# Set MCP_FAST=1 env var for fast start.

$ErrorActionPreference = "Continue"

$serverPort = 9123
$relayPort = 9124

# Auto-detect paths relative to this script
$coagentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $coagentDir "coagent.pid"
$serverScript = Join-Path $coagentDir "hermes_coagent.py"
$trayScript = Join-Path $coagentDir "tray_icon.py"
$relayScript = Join-Path $coagentDir "scripts\screenshot_relay.py"

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

$python = "python.exe"
$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCmd) { $python = $pythonCmd.Source }
if (-not $pythonw) { $pythonw = $python }

function Test-ProcessAlive {
    param([int]$ProcessIdValue)
    try {
        [void](Get-Process -Id $ProcessIdValue -ErrorAction Stop)
        return $true
    } catch {
        return $false
    }
}

function Get-CoAgentPidFromFile {
    if (-not (Test-Path $pidFile)) { return $null }
    try {
        $raw = (Get-Content -LiteralPath $pidFile -Raw -ErrorAction Stop).Trim()
        $parsed = 0
        if ([int]::TryParse($raw, [ref]$parsed)) { return $parsed }
    } catch {}
    return $null
}

function Test-CoAgentPing {
    param([int]$Port = $serverPort)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/ping" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $payload = $response.Content | ConvertFrom-Json -ErrorAction Stop
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300 -and
            $payload.status -eq "pong" -and "$($payload.agent)" -match "CoAgent|Hermes")
    } catch {
        return $false
    }
}

function Test-PortListener {
    param([int]$Port)
    try {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        return ($null -ne $listener)
    } catch {
        return $false
    }
}

function Test-TrayRunning {
    try {
        $match = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -eq "CoAgentTray.exe" -or
            (($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and $_.CommandLine -match "tray_icon\.py")
        } | Select-Object -First 1
        return ($null -ne $match)
    } catch {
        return $false
    }
}

Write-Output "=========================================="
Write-Output " Hermes CoAgent Launch (Path-Relative)"
Write-Output "=========================================="
Write-Output "Workspace: $coagentDir"

# Step 1: Check existing CoAgent server
Write-Output "[1/6] Checking existing CoAgent server..."
$serverAlreadyRunning = $false
$existingProcessId = Get-CoAgentPidFromFile

if ($existingProcessId -and (Test-ProcessAlive -ProcessIdValue $existingProcessId)) {
    Write-Output "  Already running (PID $existingProcessId from coagent.pid)"
    $serverAlreadyRunning = $true
} elseif ($existingProcessId) {
    try {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction Stop
        Write-Output "  Removed stale coagent.pid for PID $existingProcessId"
    } catch {
        Write-Output "  Stale coagent.pid could not be removed: $($_.Exception.Message)"
    }
}

if (-not $serverAlreadyRunning -and (Test-CoAgentPing -Port $serverPort)) {
    Write-Output "  Already running at port $serverPort"
    $serverAlreadyRunning = $true
}

if (-not $serverAlreadyRunning -and (Test-PortListener -Port $serverPort)) {
    Write-Output "  Port $serverPort is in use but /ping did not identify CoAgent; backend lock will decide"
}

# Step 2: Launch CoAgent server only when needed
Write-Output "[2/6] Starting CoAgent server..."
$env:MCP_FAST = "1"
if ($serverAlreadyRunning) {
    Write-Output "  Already running - server launch skipped"
} else {
    $serverArgs = @(
        "`"$serverScript`""
        "--secure"
        "--allow-external"
    )
    $serverProc = Start-Process -FilePath $pythonw -ArgumentList $serverArgs -WorkingDirectory $coagentDir -PassThru -WindowStyle Hidden -ErrorAction SilentlyContinue
    if (-not $serverProc) {
        $serverProc = Start-Process -FilePath $python -ArgumentList $serverArgs -WorkingDirectory $coagentDir -PassThru -WindowStyle Hidden -ErrorAction SilentlyContinue
    }
    if ($serverProc) {
        Write-Output "  Server PID: $($serverProc.Id)"
        Start-Sleep -Seconds 2
    } else {
        Write-Output "  Server launch failed"
    }
}

# Step 3: Launch tray icon when not already present
Write-Output "[3/6] Launching tray icon..."
if (Test-TrayRunning) {
    Write-Output "  Already running - tray launch skipped"
} else {
    $trayLaunched = $false
    if (Test-Path $trayScript) {
        Write-Output "  Installing tray deps for python launcher..."
        try {
            & $python -m pip install pystray pillow -q 2>$null
            Write-Output "  Deps installed"
        } catch {
            Write-Output "  Deps install skipped: $($_.Exception.Message)"
        }

        $trayArgs = @(
            "`"$trayScript`""
            "$serverPort"
            "--coagent-dir"
            "`"$coagentDir`""
        )
        try {
            Start-Process -FilePath $pythonw -ArgumentList $trayArgs -WorkingDirectory $coagentDir -WindowStyle Hidden -ErrorAction Stop | Out-Null
            Write-Output "  Tray launch requested with tray_icon.py"
            $trayLaunched = $true
        } catch {
            Write-Output "  Tray python launch failed: $($_.Exception.Message)"
        }
    }

    if (-not $trayLaunched) {
        $trayExeCandidates = @(
            (Join-Path $coagentDir "dist\CoAgentTray.exe")
            (Join-Path ([Environment]::GetFolderPath("Desktop")) "CoAgentTray.exe")
        )
        $trayExe = $trayExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($trayExe) {
            try {
                Start-Process -FilePath $trayExe -ArgumentList @("$serverPort", "--coagent-dir", "`"$coagentDir`"") -WorkingDirectory $coagentDir -WindowStyle Hidden -ErrorAction Stop | Out-Null
                Write-Output "  Tray launch requested with $trayExe"
            } catch {
                Write-Output "  Tray EXE launch failed: $($_.Exception.Message)"
            }
        } else {
            Write-Output "  Tray EXE not found"
        }
    }
}

# Step 4: Ensure screenshot relay on interactive desktop
Write-Output "[4/6] Ensuring screenshot relay..."
Start-Sleep -Seconds 1
$relayOk = $false
try {
    $relay = Invoke-WebRequest -Uri "http://127.0.0.1:$relayPort/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    $relayOk = ($relay.StatusCode -eq 200)
} catch {}

if ($relayOk) {
    Write-Output "  Screenshot relay already running (port $relayPort)"
} elseif (Test-Path $relayScript) {
    Write-Output "  Launching screenshot relay on interactive desktop..."
    try {
        $relayAction = New-ScheduledTaskAction -Execute "$pythonw" -Argument "`"$relayScript`""
        $relayTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(5)
        $relaySettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        $relayPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive
        Register-ScheduledTask -TaskName "CoAgent Screenshot Relay" -Action $relayAction -Trigger $relayTrigger -Settings $relaySettings -Principal $relayPrincipal -Force | Out-Null
        Start-ScheduledTask -TaskName "CoAgent Screenshot Relay" -ErrorAction SilentlyContinue | Out-Null
        Write-Output "  Relay scheduled (will start in ~5s on your desktop)"
    } catch {
        Write-Output "  Relay launch failed: $($_.Exception.Message)"
    }
} else {
    Write-Output "  scripts/screenshot_relay.py not found - live desktop unavailable"
}

# Step 5: Verify server is running
Write-Output "[5/6] Verifying server..."
if (Test-CoAgentPing -Port $serverPort) {
    Write-Output "  Server OK (port $serverPort)"
} else {
    Write-Output "  Server not responding yet - check coagent_server.log"
}

# Step 6: Done
Write-Output "[6/6] Launch complete!"
Write-Output ""
Write-Output "  Dashboard: http://localhost:$serverPort/"
Write-Output "  Dashboard2: http://localhost:$serverPort/dashboard2"
Write-Output "  Tray icon: Look for purple 'C' in system tray"
Write-Output ""
Write-Output "  MCP server auto-launches on first tool call (MCP_FAST=1)"
Write-Output "  Auth token: check coagent_server.log for '[SECURE]'"

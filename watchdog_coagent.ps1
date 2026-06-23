# watchdog_coagent.ps1 — Checks CoAgent health every 30s, restarts if down
$ErrorActionPreference = "SilentlyContinue"
$log = "$PSScriptRoot\watchdog.log"
$url = "http://127.0.0.1:9123/ping"
$checkInterval = 30

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

Write-Log "Watchdog started"

while ($true) {
    Start-Sleep $checkInterval
    try {
        $r = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            # Healthy — do nothing
            continue
        }
    } catch {
        # CoAgent down — restart
    }
    
    Write-Log "CoAgent DOWN. Restarting..."
    Get-Process python* -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "hermes_coagent" } | Stop-Process -Force
    Start-Sleep 2
    
    $batch = "$PSScriptRoot\start_coagent.bat"
    if (Test-Path $batch) {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$batch`"" -WindowStyle Hidden
        Write-Log "Launched via start_coagent.bat"
    } else {
        $pyw = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\pythonw.exe"
        $script = "$PSScriptRoot\hermes_coagent.py"
        if (Test-Path $pyw -and (Test-Path $script)) {
            Start-Process -FilePath $pyw -ArgumentList "`"$script`" --secure --allow-external" -WindowStyle Hidden
            Write-Log "Launched via direct pythonw"
        }
    }
    
    Start-Sleep 5
    
    try {
        $r = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            Write-Log "CoAgent restarted OK"
        }
    } catch {
        Write-Log "CoAgent restart FAILED"
    }
}

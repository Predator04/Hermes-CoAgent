$ErrorActionPreference = "Stop"
cd "C:\Users\Admin\Desktop\Hermes CoAgent"

# Kill old
Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1

# Start server
$p = Start-Process python -ArgumentList "hermes_coagent.py 9123" -NoNewWindow -RedirectStandardOutput "server.log" -RedirectStandardError "server_err.log" -PassThru
Write-Output "Server PID: $($p.Id)"
Start-Sleep 3

# Test endpoints
Write-Output "`n=== /ping ==="
try {
    $r = Invoke-RestMethod -Uri "http://localhost:9123/ping" -TimeoutSec 5
    Write-Output "OK: $($r | ConvertTo-Json -Compress)"
} catch { Write-Output "FAIL: $_" }

Write-Output "`n=== /stats ==="
try {
    $r = Invoke-RestMethod -Uri "http://localhost:9123/stats" -TimeoutSec 5
    Write-Output "OK: $($r | ConvertTo-Json -Compress)"
} catch { Write-Output "FAIL: $_" }

Write-Output "`n=== /logs ==="
try {
    $r = Invoke-RestMethod -Uri "http://localhost:9123/logs" -TimeoutSec 5
    Write-Output "OK: $($r | ConvertTo-Json -Compress)"
} catch { Write-Output "FAIL: $_" }

Write-Output "`n=== /history ==="
try {
    $r = Invoke-RestMethod -Uri "http://localhost:9123/history" -TimeoutSec 5
    Write-Output "OK: $($r | ConvertTo-Json -Compress)"
} catch { Write-Output "FAIL: $_" }

Write-Output "`n=== Tray syntax test ==="
python -c "import py_compile; py_compile.compile(r'C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py', doraise=True); print('OK')"

Write-Output "`n=== Cleanup ==="
$p.Kill()
Write-Output "Done"

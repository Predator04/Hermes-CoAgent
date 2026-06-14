# Start CoAgent server fresh
Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1

$py = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
$script = "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py"

# Start server
$p = Start-Process -FilePath $py -ArgumentList "$script 9123" -WindowStyle Hidden -PassThru
Write-Output "Server PID: $($p.Id)"
Start-Sleep 3

# Verify
try {
    $r = Invoke-RestMethod -Uri "http://localhost:9123/ping" -TimeoutSec 5
    Write-Output "Server: $($r.status)"
} catch {
    Write-Output "FAIL: $_"
}

# Test cursor pulse
Write-Output "`n--- Testing cursor pulse ---"
try {
    Invoke-RestMethod -Uri "http://localhost:9123/mouse/move" -Method POST -Body (@{x=800; y=500} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null
    Write-Output "Move with pulse: OK"
} catch {
    Write-Output "Move: FAIL - $_"
}
Start-Sleep 1

try {
    Invoke-RestMethod -Uri "http://localhost:9123/mouse/click" -Method POST -Body (@{button="left"} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null
    Write-Output "Click with pulse: OK"
} catch {
    Write-Output "Click: FAIL - $_"
}

# Launch tray
Start-Process wscript -ArgumentList '"C:\Users\Admin\Desktop\Hermes CoAgent\start_tray_hidden.vbs"' -WindowStyle Hidden
Write-Output "`nTray launched!"

Start-Sleep 2
Get-Process python* | Select-Object Id, @{N='Start';E={$_.StartTime.ToString('HH:mm:ss')}} | Format-Table -AutoSize

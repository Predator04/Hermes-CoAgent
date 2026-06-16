$myPid = $PID
Get-Process -Name python* -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $myPid } | Stop-Process -Force
Start-Sleep -Seconds 1
Write-Output "Killed old processes"
Start-Process -FilePath "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe" -ArgumentList "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py --allow-external" -WindowStyle Hidden
Start-Sleep -Seconds 2
# Check it started
$p = Get-Process -Name python* -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $myPid }
Write-Output "Running PIDs: $($p.Id -join ', ')"

# Kill all python processes (except the PS script itself)
$myPid = $PID
Get-Process -Name python*,pythonw* -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $myPid } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Output "All Python processes killed"

# Launch CoAgent fresh
Start-Process -FilePath "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe" -ArgumentList "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py --allow-external" -WindowStyle Hidden
Start-Sleep -Seconds 3

# Verify it started
$p = Get-Process -Name pythonw*,python* -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $myPid }
Write-Output "Running PIDs: $($p.Id -join ', ')"

# Wait and test
Start-Sleep -Seconds 5
$result = netstat -ano | Select-String ":9123" | Select-String "LISTENING"
if ($result) {
    Write-Output "Port 9123 is LISTENING!"
} else {
    Write-Output "Port 9123 is NOT listening"
}

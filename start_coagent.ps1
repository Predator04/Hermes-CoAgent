$batPath = Join-Path $PSScriptRoot "launch_coagent.bat"
Write-Output "Starting: $batPath"

# Use Invoke-Expression for the batch file (simulates double-click)
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "cmd.exe"
$psi.Arguments = "/c `"$batPath`""
$psi.WorkingDirectory = $PSScriptRoot
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$psi.CreateNoWindow = $true
$p = [System.Diagnostics.Process]::Start($psi)

Write-Output "Started with PID (cmd.exe): $($p.Id)"
Start-Sleep -Seconds 2
Write-Output "Checking port 9123..."
netstat -ano | Select-String ':9123'

Start-Sleep -Seconds 5
Write-Output "After 5s check..."
netstat -ano | Select-String ':9123'

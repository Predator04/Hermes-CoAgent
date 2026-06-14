# Kill old trays
Get-Process python* -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'coagent_tray' } | ForEach-Object { $_.Kill(); Write-Output "Killed PID $($_.Id)" }
Write-Output "Ready for Codex"

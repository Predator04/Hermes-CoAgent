# Aggressive kill of all hermes_coagent processes
Get-Process | Where-Object { $_.ProcessName -match 'python' } | ForEach-Object {
    try {
        if ($_.CommandLine -match 'hermes_coagent|coagent_features|coagent_server') {
            Write-Output "Killing $($_.Id)"
            Stop-Process $_.Id -Force
        }
    } catch { }
}

Start-Sleep -Seconds 2

# Kill any remaining python processes holding port 9123
netstat -ano | Select-String '9123' | ForEach-Object {
    $parts = $_ -split '\s+'
    $procId = $parts[-1]
    if ($procId -match '^\d+$') {
        Write-Output "Killing process $procId holding port 9123"
        Stop-Process $procId -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 1
Write-Output "Done"

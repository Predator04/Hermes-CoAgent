# Install CoAgent Watchdog as Windows Scheduled Task
# Run this script as Administrator

$taskName = "HermesCoAgent-Watchdog"
$scriptPath = Join-Path $PSScriptRoot "coagent_watchdog.ps1"
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

# Delete old task if exists
schtasks /Delete /TN $taskName /F 2>$null

# Create the task using schtasks.exe with properly escaped quotes
$cmd = "schtasks /Create /TN `"$taskName`" /TR `"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \`"$scriptPath\`"`" /SC MINUTE /MO 1 /RU `"$taskUser`" /IT /F"
Write-Host "Running: $cmd"
Invoke-Expression $cmd

if ($LASTEXITCODE -eq 0) {
    Write-Host "Watchdog task installed successfully!"
    
    # Run it once to test
    schtasks /Run /TN $taskName
    Write-Host "Task launched. Waiting 10s for first check..."
    Start-Sleep -Seconds 10
    
    # Check log
    $log = Get-Content "C:\Windows\Temp\coagent_watchdog.log" -Tail 5 -ErrorAction SilentlyContinue
    if ($log) {
        Write-Host "=== Last log entries ==="
        $log | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "No log entries yet. Check C:\Windows\Temp\coagent_watchdog.log"
    }
} else {
    Write-Host "Failed to create task. Exit code: $LASTEXITCODE"
}

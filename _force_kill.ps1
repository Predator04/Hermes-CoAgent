# Kill all old tray processes
$procs = Get-Process python* -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    try {
        if ($p.CommandLine -match 'coagent_tray') {
            $p.Kill()
            Write-Output "Killed tray PID $($p.Id)"
        }
        if ($p.CommandLine -match 'hermes_coagent') {
            $p.Kill()
            Write-Output "Killed server PID $($p.Id)"
        }
    } catch {}
}
Start-Sleep 1
Write-Output "All dead"

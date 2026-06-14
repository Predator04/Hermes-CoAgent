# Kill tray processes
$procs = Get-Process python* -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    try {
        if ($p.CommandLine -match 'coagent_tray') {
            $p.Kill()
            Write-Output "Killed tray PID $($p.Id)"
        }
    } catch {}
}

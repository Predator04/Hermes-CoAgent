# Kill old tray, launch new one
$old = Get-Process python* | Where-Object { $_.Id -ne $null }
foreach ($p in $old) {
    try {
        $cmd = $p.CommandLine
        if ($cmd -match 'coagent_tray') {
            $p.Kill()
            Write-Output "Killed tray PID $($p.Id)"
        }
    } catch {}
}
Start-Sleep 1

# Launch new tray
$vbs = "C:\Users\Admin\Desktop\Hermes CoAgent\start_tray_hidden.vbs"
Start-Process wscript -ArgumentList "`"$vbs`"" -WindowStyle Hidden
Write-Output "Launched tray"

Start-Sleep 2
$procs = Get-Process python* | Select-Object Id, @{N='MemMB';E={[math]::Round($_.WorkingSet/1MB,1)}}, @{N='Start';E={$_.StartTime.ToString('HH:mm:ss')}}, @{N='Cmd';E={$_.CommandLine.Substring(0,[Math]::Min(120,$_.CommandLine.Length))}}
$procs | Format-Table -AutoSize

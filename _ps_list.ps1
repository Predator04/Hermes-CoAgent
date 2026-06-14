Get-Process python* | ForEach-Object {
    $s = $_.StartTime.ToString('HH:mm:ss')
    try { $c = $_.CommandLine.Substring(0, [Math]::Min(80, $_.CommandLine.Length)) } catch { $c = "?" }
    Write-Output ("PID:{0} Start:{1} Cmd:{2}" -f $_.Id, $s, $c)
}

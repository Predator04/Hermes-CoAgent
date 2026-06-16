$p = Get-Process -Name python* -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'python*' }
Write-Output "Process count: $($p.Count)"
$p | Select-Object Id, ProcessName | Format-Table -AutoSize

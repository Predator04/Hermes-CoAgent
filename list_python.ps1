Get-Process -Name pythonw*,python* -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, @{N='CPU(s)';E={[math]::Round($_.TotalProcessorTime.TotalSeconds,1)}} | Format-Table -AutoSize

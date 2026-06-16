$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe"
$psi.Arguments = '"C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py" --allow-external'
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$psi.UseShellExecute = $true
$p = [System.Diagnostics.Process]::Start($psi)
Write-Output "Launched PID: $($p.Id)"

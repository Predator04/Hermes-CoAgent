# Kill old CoAgent processes
Get-Process -Name python* 2>$null | Where-Object {
    $proc = $_
    try {
        $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)").CommandLine
        return $cmd -match 'hermes_coagent'
    } catch { return $false }
} | Stop-Process -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 2

# Launch fresh with token+secure
Start-Process -FilePath 'pythonw.exe' -ArgumentList "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py --secure --allow-external" -WindowStyle Hidden

Write-Output 'Done'

# Kill old CoAgent processes
Get-Process -Name python* -ErrorAction SilentlyContinue | Where-Object {
    $proc = $_
    try {
        $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($proc.Id)").CommandLine
        return ($cmd -match 'hermes_coagent' -or $cmd -match 'tray_icon')
    } catch { return $false }
} | Stop-Process -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 3

# Launch fresh
cd "C:\Users\Admin\Desktop\Hermes CoAgent"
Start-Process -FilePath pythonw.exe -ArgumentList "hermes_coagent.py --secure --token=YOUR_TOKEN_HERE --allow-external" -WindowStyle Hidden -PassThru

Write-Output "DONE"

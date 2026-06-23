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
Set-Location $PSScriptRoot
$pythonwCandidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe"
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe"
    "C:\Program Files\Python313\pythonw.exe"
    "C:\Python313\pythonw.exe"
)
$pythonw = $pythonwCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonw) {
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { $pythonw = $cmd.Source }
}
if (-not $pythonw) { throw "pythonw.exe not found" }
$script = Join-Path (Get-Location) "hermes_coagent.py"
Start-Process -FilePath $pythonw -ArgumentList "`"$script`" --secure --allow-external" -WindowStyle Hidden -PassThru

Write-Output "DONE"

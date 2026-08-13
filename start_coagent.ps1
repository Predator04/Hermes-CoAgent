$workdir = $PSScriptRoot
$script = Join-Path $workdir "hermes_coagent.py"
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $python) { $python = "C:\Program Files\Python312\pythonw.exe" }

Set-Location $workdir
Start-Process -FilePath $python -ArgumentList "`"$script`" --secure --allow-external" -WorkingDirectory $workdir

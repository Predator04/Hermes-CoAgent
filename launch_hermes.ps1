# Launch CoAgent properly — workingdir is the CoAgent folder
$coagentDir = $PSScriptRoot
$python = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\python.exe"
$script = "$coagentDir\hermes_coagent.py"
$log = "$coagentDir\launch_debug.log"

# Write startup info
"Launch at $(Get-Date)" | Out-File $log
"Python: $python" | Out-File $log -Append
"Script: $script" | Out-File $log -Append
"WorkingDir: $coagentDir" | Out-File $log -Append

# Test import from working dir
$result = & $python -c @"
import sys
sys.path.insert(0, r'$coagentDir')
import auth
import routes_bypass
print('Imports OK')
"@ 2>&1
"Test: $result" | Out-File $log -Append

if ($LASTEXITCODE -eq 0) {
    Start-Process -FilePath $python -ArgumentList "`"$script`" --secure --allow-external" -WorkingDirectory $coagentDir -WindowStyle Hidden -PassThru | Out-File $log -Append
    "Launched with PID: $_" | Out-File $log -Append
} else {
    "Import test failed: $result" | Out-File $log -Append
}

$coagentDir = "$env:USERPROFILE\Desktop\Hermes CoAgent"
$scriptPath = "$coagentDir\start_hidden.vbs"

$vbsContent = @"
CreateObject("Wscript.Shell").Run "cmd /c cd /d `"$coagentDir`" && python hermes_coagent.py 9123", 0, False
"@

Set-Content -Path $scriptPath -Value $vbsContent -Force

# Add to Windows startup
$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Hermes CoAgent.lnk")
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$scriptPath`""
$shortcut.WindowStyle = 7
$shortcut.Description = "Hermes CoAgent v3 - Desktop Co-Pilot"
$shortcut.Save()

Write-Host "✅ Hermes CoAgent autostart installed"
Write-Host "  → Starts minimized on Windows boot"
Write-Host "  → Dashboard at http://localhost:9123"
Write-Host "  → Ctrl+Alt+Shift = emergency stop"

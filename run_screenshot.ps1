$taskName = "CoAgent_Screenshot"
$scriptPath = "C:\Users\Admin\Desktop\Hermes CoAgent\capture_desktop.ps1"

$psScript = @"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
`$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
`$bmp = New-Object System.Drawing.Bitmap `$bounds.Width, `$bounds.Height
`$g = [System.Drawing.Graphics]::FromImage(`$bmp)
`$g.CopyFromScreen(`$bounds.X, `$bounds.Y, 0, 0, `$bounds.Size)
`$g.Dispose()
`$bmp.Save("C:\Users\Admin\Desktop\Hermes CoAgent\screenshot_v73.jpg", [System.Drawing.Imaging.ImageFormat]::Jpeg)
`$bmp.Dispose()
"@

Set-Content -Path $scriptPath -Value $psScript -Force

schtasks /create /tn $taskName /tr "powershell.exe -ExecutionPolicy Bypass -File `"$scriptPath`"" /sc once /st 00:00 /ru Admin /IT /f
Start-Sleep -Seconds 1
schtasks /run /tn $taskName
Start-Sleep -Seconds 5
schtasks /delete /tn $taskName /f

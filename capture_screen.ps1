$scriptPath = "C:\Users\Admin\Desktop\Hermes CoAgent\"
Set-Location $scriptPath

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
$g.Dispose()

$outPath = $scriptPath + "screenshot_v73.jpg"
$bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Jpeg)
$bmp.Dispose()

Write-Host ("Captured: " + $bounds.Width + "x" + $bounds.Height + " -> " + $outPath)

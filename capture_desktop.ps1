Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
$g.Dispose()
$bmp.Save("C:\Users\Admin\Desktop\Hermes CoAgent\screenshot_v73.jpg", [System.Drawing.Imaging.ImageFormat]::Jpeg)
$bmp.Dispose()

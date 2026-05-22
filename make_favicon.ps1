Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile('logo.png')
$size = [math]::Max($img.Width, $img.Height)
$bmp = New-Object System.Drawing.Bitmap($size, $size)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::Transparent)
$x = ($size - $img.Width) / 2
$y = ($size - $img.Height) / 2
$g.DrawImage($img, $x, $y, $img.Width, $img.Height)
$bmp.Save('favicon.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$img.Dispose()
$bmp.Dispose()

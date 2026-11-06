Add-Type -AssemblyName System.Drawing

function New-DiagramCanvas($path, $width, $height, $title) {
  $bitmap = New-Object System.Drawing.Bitmap($width, $height)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $graphics.Clear([System.Drawing.Color]::FromArgb(245, 247, 251))
  $fontTitle = New-Object System.Drawing.Font('Arial', 23, [System.Drawing.FontStyle]::Bold)
  $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(16, 42, 67))
  $graphics.DrawString($title, $fontTitle, $brush, 45, 35)
  $fontTitle.Dispose(); $brush.Dispose()
  return @{ Bitmap = $bitmap; Graphics = $graphics; Path = $path }
}

function Draw-Box($g, $x, $y, $w, $h, $fill, $heading, $lines) {
  $rect = New-Object System.Drawing.Rectangle($x, $y, $w, $h)
  $fillBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb($fill))
  $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(148, 163, 184), 2)
  $g.FillRectangle($fillBrush, $rect); $g.DrawRectangle($pen, $rect)
  $headFont = New-Object System.Drawing.Font('Arial', 15, [System.Drawing.FontStyle]::Bold)
  $bodyFont = New-Object System.Drawing.Font('Arial', 12)
  $ink = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(16, 42, 67))
  $g.DrawString($heading, $headFont, $ink, $x + 16, $y + 15)
  $yy = $y + 50
  foreach ($line in $lines) { $g.DrawString($line, $bodyFont, $ink, $x + 16, $yy); $yy += 27 }
  $fillBrush.Dispose(); $pen.Dispose(); $headFont.Dispose(); $bodyFont.Dispose(); $ink.Dispose()
}

function Draw-Line($g, $x1, $y1, $x2, $y2, $color) {
  $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb($color), 4)
  $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::ArrowAnchor
  $g.DrawLine($pen, $x1, $y1, $x2, $y2); $pen.Dispose()
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$a = New-DiagramCanvas (Join-Path $root 'arquitetura.png') 1100 550 'Sentinela | System architecture'
Draw-Box $a.Graphics 55 140 240 150 0xFFE6FFFA 'Microphone MAX9814' @('Analog OUT', 'GPIO 34 | ADC1', 'PCM mono ~16 kHz')
Draw-Box $a.Graphics 390 115 320 220 0xFFFFFFFF 'ESP32 DevKit v1' @('SENTINELA access point', 'HTTP server | port 80', '/status | /sensor | /audio.wav', '/atuador | /config | CORS')
Draw-Box $a.Graphics 805 120 240 175 0xFFFFFAF0 'Actuators' @('Green LED | GPIO 16', 'Red LED | GPIO 17', 'Buzzer | GPIO 18')
Draw-Box $a.Graphics 390 390 320 110 0xFFEBF8FF 'Notebook client' @('Local Wi-Fi | HTTP requests')
Draw-Line $a.Graphics 295 205 380 205 0xFF0F766E
Draw-Line $a.Graphics 710 205 795 205 0xFFD97706
Draw-Line $a.Graphics 550 380 550 345 0xFF52606D
$a.Graphics.DrawString('Local Wi-Fi | 192.168.4.1', (New-Object System.Drawing.Font('Arial', 10)), (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(72, 101, 129))), 565, 355)
$a.Bitmap.Save($a.Path, [System.Drawing.Imaging.ImageFormat]::Png)
$a.Graphics.Dispose(); $a.Bitmap.Dispose()

$s = New-DiagramCanvas (Join-Path $root 'esquematico.png') 1100 570 'Sentinela | Wiring reference'
Draw-Box $s.Graphics 420 110 270 350 0xFFFFFFFF 'ESP32 DevKit v1' @('GPIO 34 | ADC1', 'GPIO 16 | green LED', 'GPIO 17 | red LED', 'GPIO 18 | active buzzer', 'GPIO 2 | onboard alert', '3V3 | GND')
Draw-Box $s.Graphics 65 175 230 190 0xFFFFFFFF 'GY-MAX9814' @('OUT -> GPIO 34', 'VDD -> 3V3', 'GAIN -> VDD | 40 dB', 'GND -> GND | AR open')
Draw-Box $s.Graphics 815 145 230 245 0xFFFFFFFF 'Actuators' @('GPIO 16 -> 220R -> LED', 'GPIO 17 -> 220R -> LED', 'LED cathodes -> GND', 'GPIO 18 -> driver -> buzzer')
Draw-Line $s.Graphics 295 255 410 255 0xFF0F766E
Draw-Line $s.Graphics 690 310 800 310 0xFF0F766E
Draw-Line $s.Graphics 690 435 800 340 0xFF475569
Draw-Line $s.Graphics 295 300 410 395 0xFFD97706
Draw-Line $s.Graphics 295 340 410 435 0xFF475569
$noteFont = New-Object System.Drawing.Font('Arial', 11)
$noteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(72, 101, 129))
$s.Graphics.DrawString('GPIO 34 must not receive more than 3.3 V. Use a common ground.', $noteFont, $noteBrush, 65, 490)
$s.Graphics.DrawString('Use a driver if the buzzer current exceeds the GPIO rating.', $noteFont, $noteBrush, 65, 515)
$s.Bitmap.Save($s.Path, [System.Drawing.Imaging.ImageFormat]::Png)
$noteFont.Dispose(); $noteBrush.Dispose(); $s.Graphics.Dispose(); $s.Bitmap.Dispose()

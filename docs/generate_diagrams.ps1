# generate_diagrams.ps1 — Gera docs/arquitetura.(svg|png) e docs/esquematico.(svg|png).
#
# Cada diagrama é descrito UMA vez (lista de caixas, setas e notas) e desenhado
# duas vezes: em SVG (texto, bom para o GitHub) e em PNG (System.Drawing do
# Windows, bom para slides). Uso, na pasta do projeto:
#     powershell -ExecutionPolicy Bypass -File docs\generate_diagrams.ps1
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = 'Stop'
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path

function Caixa($x, $y, $w, $h, $cor, $titulo, $linhas) {
  @{ x = $x; y = $y; w = $w; h = $h; cor = $cor; titulo = $titulo; linhas = $linhas }
}
function Seta($x1, $y1, $x2, $y2, $cor, $rotulo, $dupla = $false) {
  @{ x1 = $x1; y1 = $y1; x2 = $x2; y2 = $y2; cor = $cor; rotulo = $rotulo; dupla = $dupla }
}
function Escapar($t) { $t.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;') }

function Gerar-Svg($arquivo, $w, $h, $titulo, $caixas, $setas, $notas) {
  $s = New-Object System.Text.StringBuilder
  [void]$s.Append("<svg xmlns='http://www.w3.org/2000/svg' width='$w' height='$h' viewBox='0 0 $w $h' font-family='Arial'>")
  [void]$s.Append("<defs><marker id='m' markerWidth='10' markerHeight='10' refX='8' refY='3' orient='auto-start-reverse'><path d='M0 0v6l9-3z' fill='context-stroke'/></marker></defs>")
  [void]$s.Append("<rect width='$w' height='$h' fill='#f5f7fb'/>")
  [void]$s.Append("<text x='40' y='52' font-size='28' font-weight='700' fill='#102a43'>$(Escapar $titulo)</text>")
  foreach ($c in $caixas) {
    [void]$s.Append("<rect x='$($c.x)' y='$($c.y)' width='$($c.w)' height='$($c.h)' rx='14' fill='$($c.cor)' stroke='#94a3b8' stroke-width='2'/>")
    [void]$s.Append("<text x='$($c.x + 16)' y='$($c.y + 32)' font-size='18' font-weight='700' fill='#102a43'>$(Escapar $c.titulo)</text>")
    $yy = $c.y + 62
    foreach ($l in $c.linhas) { [void]$s.Append("<text x='$($c.x + 16)' y='$yy' font-size='15' fill='#334e68'>$(Escapar $l)</text>"); $yy += 24 }
  }
  foreach ($a in $setas) {
    $inicio = if ($a.dupla) { " marker-start='url(#m)'" } else { '' }
    [void]$s.Append("<line x1='$($a.x1)' y1='$($a.y1)' x2='$($a.x2)' y2='$($a.y2)' stroke='$($a.cor)' stroke-width='3' marker-end='url(#m)'$inicio/>")
    if ($a.rotulo) {
      $mx = [int](($a.x1 + $a.x2) / 2) + 8; $my = [int](($a.y1 + $a.y2) / 2) - 8
      [void]$s.Append("<text x='$mx' y='$my' font-size='13' fill='#243b53'>$(Escapar $a.rotulo)</text>")
    }
  }
  $yn = $h - 20 - 22 * ($notas.Count - 1)
  foreach ($n in $notas) { [void]$s.Append("<text x='40' y='$yn' font-size='14' fill='#486581'>$(Escapar $n)</text>"); $yn += 22 }
  [void]$s.Append('</svg>')
  [System.IO.File]::WriteAllText($arquivo, $s.ToString(), (New-Object System.Text.UTF8Encoding($false)))
}

function Cor($hex) { [System.Drawing.ColorTranslator]::FromHtml($hex) }

function Gerar-Png($arquivo, $w, $h, $titulo, $caixas, $setas, $notas) {
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAlias
  $g.Clear((Cor '#f5f7fb'))
  $fTitulo = New-Object System.Drawing.Font('Arial', 21, [System.Drawing.FontStyle]::Bold)
  $fCaixa = New-Object System.Drawing.Font('Arial', 13.5, [System.Drawing.FontStyle]::Bold)
  $fTexto = New-Object System.Drawing.Font('Arial', 11)
  $fNota = New-Object System.Drawing.Font('Arial', 10.5)
  $tinta = New-Object System.Drawing.SolidBrush((Cor '#102a43'))
  $tinta2 = New-Object System.Drawing.SolidBrush((Cor '#334e68'))
  $g.DrawString($titulo, $fTitulo, $tinta, 36, 22)
  $borda = New-Object System.Drawing.Pen((Cor '#94a3b8'), 2)
  foreach ($c in $caixas) {
    $fundo = New-Object System.Drawing.SolidBrush((Cor $c.cor))
    $g.FillRectangle($fundo, $c.x, $c.y, $c.w, $c.h); $g.DrawRectangle($borda, $c.x, $c.y, $c.w, $c.h); $fundo.Dispose()
    $g.DrawString($c.titulo, $fCaixa, $tinta, $c.x + 14, $c.y + 12)
    $yy = $c.y + 46
    foreach ($l in $c.linhas) { $g.DrawString($l, $fTexto, $tinta2, $c.x + 14, $yy); $yy += 24 }
  }
  foreach ($a in $setas) {
    $caneta = New-Object System.Drawing.Pen((Cor $a.cor), 3)
    $caneta.CustomEndCap = New-Object System.Drawing.Drawing2D.AdjustableArrowCap(5, 5)
    if ($a.dupla) { $caneta.CustomStartCap = New-Object System.Drawing.Drawing2D.AdjustableArrowCap(5, 5) }
    $g.DrawLine($caneta, $a.x1, $a.y1, $a.x2, $a.y2); $caneta.Dispose()
    if ($a.rotulo) { $g.DrawString($a.rotulo, $fNota, $tinta, [int](($a.x1 + $a.x2) / 2) + 8, [int](($a.y1 + $a.y2) / 2) - 24) }
  }
  $yn = $h - 36 - 22 * ($notas.Count - 1)
  foreach ($n in $notas) { $g.DrawString($n, $fNota, $tinta2, 36, $yn); $yn += 22 }
  $bmp.Save($arquivo, [System.Drawing.Imaging.ImageFormat]::Png)
  foreach ($o in @($fTitulo, $fCaixa, $fTexto, $fNota, $tinta, $tinta2, $borda, $g, $bmp)) { $o.Dispose() }
}

# ---------------- Arquitetura ----------------
$caixas = @(
  (Caixa 40 110 250 160 '#e6fffa' 'Microfone GY-MAX9814' @('Eletreto + AGC, ganho 40 dB', 'Saída analógica OUT', '-> GPIO34 (ADC1_CH6)')),
  (Caixa 380 90 360 250 '#ffffff' 'ESP32 DevKit v1 (servidor)' @('Wi-Fi Access Point "SENTINELA"', 'IP 192.168.4.1 · HTTP porta 80', 'Captura 16 kHz: timer + tarefa no núcleo 1', 'Buffer circular de ~2 s (64 KB)', 'GET /status /sensor /audio.wav', 'GET /atuador /config · CORS')),
  (Caixa 830 110 250 160 '#fffaf0' 'Atuadores' @('LED verde · GPIO16', 'LED vermelho · GPIO17', 'Buzzer (NPN) · GPIO18', 'LED azul onboard · GPIO2')),
  (Caixa 40 430 1040 230 '#ebf8ff' 'Notebook (conectado ao Wi-Fi SENTINELA, sem internet)' @()),
  (Caixa 70 480 430 160 '#ffffff' 'Dashboard (navegador, JS puro)' @('Polling de 1 s: /status e /sensor', 'Selo conectado/desconectado, gráficos', 'Botões Normal / Alerta / Buzzer / Teste', 'Funciona SEM o serviço de IA')),
  (Caixa 620 480 430 160 '#ffffff' 'Serviço de IA (Python, localhost:5000)' @('Puxa /audio.wav a cada ~1 s', 'YAMNet -> porteiro "é carro?"', '-> diagnóstico (normal/batida/ignição)', 'Comanda /atuador; serve o dashboard'))
)
$setas = @(
  (Seta 290 190 372 190 '#0f766e' 'áudio'),
  (Seta 740 190 822 190 '#d97706' 'GPIO'),
  (Seta 285 472 470 348 '#2563eb' 'HTTP GET' $true),
  (Seta 835 472 650 348 '#7c3aed' '/audio.wav, /atuador' $true),
  (Seta 508 560 612 560 '#475569' '/api' $true)
)
$notas = @('Núcleo obrigatório = ESP32 + dashboard por HTTP. A IA é um diferencial: se ela cair, o resto continua funcionando.')
Gerar-Svg (Join-Path $pasta 'arquitetura.svg') 1120 740 'SENTINELA · Arquitetura' $caixas $setas $notas
Gerar-Png (Join-Path $pasta 'arquitetura.png') 1120 740 'SENTINELA · Arquitetura' $caixas $setas $notas

# ---------------- Esquemático ----------------
$caixas = @(
  (Caixa 420 100 280 330 '#ffffff' 'ESP32 DevKit v1' @('3V3  -> VDD do MAX9814', 'GND  -> trilho de GND comum', 'GPIO34 <- OUT do MAX9814', 'GPIO16 -> LED verde', 'GPIO17 -> LED vermelho', 'GPIO18 -> base do NPN', 'VIN (5 V) -> (+) do buzzer', 'GPIO2 = LED azul onboard')),
  (Caixa 40 120 300 190 '#e6fffa' 'GY-MAX9814' @('VDD  -> 3V3 (nunca 5 V)', 'GND  -> GND', 'OUT  -> GPIO34', 'GAIN -> VDD (40 dB fixo)', 'AR   -> solto')),
  (Caixa 780 90 320 150 '#f0fff4' 'LEDs (5 mm)' @('GPIO16 -> 220 Ω -> ânodo verde', 'GPIO17 -> 220 Ω -> ânodo vermelho', 'cátodos (perna curta) -> GND')),
  (Caixa 780 270 320 190 '#fffaf0' 'Buzzer ativo 5 V via NPN' @('GPIO18 -> 1 kΩ -> base', 'emissor -> GND', 'coletor -> (-) do buzzer', '(+) do buzzer -> VIN (5 V)', 'BC548: C-B-E · 2N2222: E-B-C'))
)
$setas = @(
  (Seta 340 215 412 215 '#0f766e' 'OUT'),
  (Seta 700 165 772 165 '#16a34a' '16/17'),
  (Seta 700 360 772 360 '#d97706' '18 / VIN')
)
$notas = @('Monte com o USB desligado. GND comum a todos os componentes. GPIO34 é só entrada e não pode passar de 3,3 V.',
           'A corrente do buzzer passa pelo transistor (não pelo GPIO). Pinagem do transistor: face reta para você, pernas para baixo.')
Gerar-Svg (Join-Path $pasta 'esquematico.svg') 1140 560 'SENTINELA · Ligações (esquemático)' $caixas $setas $notas
Gerar-Png (Join-Path $pasta 'esquematico.png') 1140 560 'SENTINELA · Ligações (esquemático)' $caixas $setas $notas
Write-Output 'Diagramas gerados em docs/.'

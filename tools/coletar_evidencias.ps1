# coletar_evidencias.ps1 - Testes de rede do TDE com evidencias salvas em arquivo.
#
# Roda, contra o ESP32 (ou o simulador), os testes pedidos na secao 6 do regulamento:
#   1. conectividade (ping) e camada de enlace (arp: MAC do ESP32 visto pela rede)
#   2. acesso a porta do servidor (TCP 80 aberta x 81 fechada)
#   3. comunicacao cliente-servidor: pedido HTTP escrito a mao num socket TCP (como telnet)
#      e curl -v em todas as rotas (mostra conexao TCP, pedido e resposta HTTP)
#   4. sensor e atuador via rede (leituras, comandos, erros 400/404) e o log da flash
# Saida: docs\evidencias\AAAA-MM-DD_HHMMSS\ com um .txt por teste e RESUMO.md.
#
# Uso (PowerShell, na raiz do repositorio):
#   powershell -ExecutionPolicy Bypass -File tools\coletar_evidencias.ps1
#   powershell -ExecutionPolicy Bypass -File tools\coletar_evidencias.ps1 -Alvo 192.168.0.50
#   powershell -ExecutionPolicy Bypass -File tools\coletar_evidencias.ps1 -Alvo 127.0.0.1 -Porta 8080   (simulador)
param(
    [string]$Alvo = "192.168.4.1",
    [int]$Porta = 80
)

$ErrorActionPreference = "Continue"
$base = "http://${Alvo}:$Porta"
$pasta = Join-Path (Split-Path $PSScriptRoot -Parent) ("docs\evidencias\" + (Get-Date -Format "yyyy-MM-dd_HHmmss"))
New-Item -ItemType Directory -Force $pasta | Out-Null
$resultados = New-Object System.Collections.ArrayList

function Salvar($nome, $texto) {
    $texto | Out-File -Encoding utf8 (Join-Path $pasta $nome)
}

function Registrar($teste, $ok, $detalhe, $arquivo) {
    $null = $resultados.Add([pscustomobject]@{ Teste = $teste; Ok = $ok; Detalhe = $detalhe; Arquivo = $arquivo })
    $marca = if ($ok) { "[OK]   " } else { "[FALHA]" }
    Write-Host "$marca $teste - $detalhe"
}

function Cabecalho($titulo) {
    "# $titulo`r`n# Data: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  Alvo: $base  Cliente: $env:COMPUTERNAME`r`n"
}

# Pedido HTTP via curl. Devolve @{codigo; corpo; texto} (texto = saida completa com -v).
function Pedir($caminho) {
    $arqCorpo = [System.IO.Path]::GetTempFileName()
    $verbose = & curl.exe -sS -v --max-time 8 -o $arqCorpo -w "`nHTTP_CODE=%{http_code} TEMPO=%{time_total}s" "$base$caminho" 2>&1 | Out-String
    $corpo = Get-Content $arqCorpo -Raw -Encoding UTF8
    Remove-Item $arqCorpo -ErrorAction SilentlyContinue
    $codigo = if ($verbose -match "HTTP_CODE=(\d+)") { [int]$Matches[1] } else { 0 }
    return @{ codigo = $codigo; corpo = $corpo; texto = "$verbose`r`n--- corpo ---`r`n$corpo" }
}

Write-Host "Coletando evidencias contra $base -> $pasta`n"

# ---------- 1. Conectividade (ICMP) e enlace (ARP) ----------
$ping = ping -n 10 $Alvo | Out-String
Salvar "01_ping.txt" ((Cabecalho "Teste de conectividade (ICMP echo / ping)") + $ping)
$perdaOk = $ping -match "Perdidos = 0|Lost = 0"  # o Windows quebra "(0% de perda)" em duas linhas
Registrar "Ping (ICMP)" ($ping -match "TTL=") $(if ($perdaOk) { "10 de 10 respostas" } else { "houve perda; ver arquivo" }) "01_ping.txt"

$arp = arp -a | Out-String
Salvar "02_arp.txt" ((Cabecalho "Tabela ARP do cliente (IP -> MAC, camada de enlace)") + $arp)
Registrar "ARP (MAC do ESP32 na rede)" ($arp -match [regex]::Escape($Alvo)) "procure $Alvo na tabela" "02_arp.txt"

# ---------- 2. Porta do servidor (TCP) ----------
$tcp = Test-NetConnection -ComputerName $Alvo -Port $Porta -WarningAction SilentlyContinue
$tcpFechada = Test-NetConnection -ComputerName $Alvo -Port ($Porta + 1) -WarningAction SilentlyContinue
$txtPorta = (Cabecalho "Acesso a porta do servidor (handshake TCP)") +
    "Porta $Porta (servidor HTTP): TcpTestSucceeded = $($tcp.TcpTestSucceeded)`r`n" +
    ($tcp | Format-List ComputerName, RemoteAddress, RemotePort, SourceAddress, TcpTestSucceeded | Out-String) +
    "Porta $($Porta + 1) (nenhum servico, controle): TcpTestSucceeded = $($tcpFechada.TcpTestSucceeded)`r`n"
Salvar "03_porta_tcp.txt" $txtPorta
Registrar "Porta TCP $Porta aberta" $tcp.TcpTestSucceeded "porta $($Porta + 1) fechada: $(-not $tcpFechada.TcpTestSucceeded)" "03_porta_tcp.txt"

# ---------- 3. Socket TCP "na mao" (equivalente ao telnet) ----------
try {
    $cliente = New-Object System.Net.Sockets.TcpClient
    $cliente.ReceiveTimeout = 5000
    $cliente.Connect($Alvo, $Porta)
    $fluxo = $cliente.GetStream()
    $pedido = "GET /sensor HTTP/1.1`r`nHost: $Alvo`r`nConnection: close`r`n`r`n"
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($pedido)
    $fluxo.Write($bytes, 0, $bytes.Length)
    $leitor = New-Object System.IO.StreamReader($fluxo)
    $resposta = $leitor.ReadToEnd()
    $local = $cliente.Client.LocalEndPoint
    $cliente.Close()
    Salvar "04_socket_tcp.txt" ((Cabecalho "Cliente TCP escrito a mao (socket) enviando HTTP cru") +
        "Conexao TCP: $local -> ${Alvo}:$Porta`r`n`r`n>>> enviado:`r`n$pedido<<< recebido:`r`n$resposta")
    Registrar "Socket TCP + HTTP cru" ($resposta -match "HTTP/1\.[01] 200") "porta local $($local.Port)" "04_socket_tcp.txt"
} catch {
    Salvar "04_socket_tcp.txt" ((Cabecalho "Socket TCP") + "ERRO: $($_.Exception.Message)")
    Registrar "Socket TCP + HTTP cru" $false $_.Exception.Message "04_socket_tcp.txt"
}

# ---------- 4. Rotas HTTP (curl -v) ----------
$texto = Cabecalho "Comunicacao cliente-servidor HTTP (curl -v): rotas de consulta"
foreach ($rota in "/info", "/status", "/sensor") {
    $r = Pedir $rota
    $texto += "`r`n==================== GET $rota ====================`r`n" + $r.texto
    Registrar "GET $rota" ($r.codigo -eq 200) "HTTP $($r.codigo)" "05_rotas_consulta.txt"
}
Salvar "05_rotas_consulta.txt" $texto

$st = Pedir "/status"
try {
    $j = $st.corpo | ConvertFrom-Json
    $info = "IP estacao: $($j.rede.sta_ip)  MAC estacao: $($j.rede.sta_mac)  IP AP: $($j.rede.ap_ip)  MAC AP: $($j.rede.ap_mac)  Wi-Fi: $($j.rede.sta_ssid) conectado=$($j.rede.sta_conectado)  hora: $($j.hora)"
    Registrar "IP, MAC e status da conexao em /status" ($null -ne $j.rede.ap_mac) $info "05_rotas_consulta.txt"
} catch { Registrar "IP, MAC e status da conexao em /status" $false "JSON invalido" "05_rotas_consulta.txt" }

# Sensor em tempo real: 5 leituras com 1 s de intervalo.
$texto = Cabecalho "Sensor (microfone) consultado via rede: 5 leituras, 1 por segundo"
$janelas = @()
for ($i = 1; $i -le 5; $i++) {
    $r = Pedir "/sensor"
    $texto += "leitura $i : $($r.corpo)`r`n"
    try { $janelas += ($r.corpo | ConvertFrom-Json).ts_ms } catch {}
    Start-Sleep -Milliseconds 1000
}
Salvar "06_sensor_tempo_real.txt" $texto
Registrar "Sensor em tempo real" (($janelas | Select-Object -Unique).Count -ge 4) "carimbos de tempo distintos: $(($janelas | Select-Object -Unique).Count)/5" "06_sensor_tempo_real.txt"

# Audio (WAV) do microfone.
$wav = Join-Path $pasta "07_audio_1s.wav"
$codigoWav = & curl.exe -s --max-time 10 -o $wav -w "%{http_code}" "$base/audio.wav?ms=1000"
$tam = if (Test-Path $wav) { (Get-Item $wav).Length } else { 0 }
Registrar "GET /audio.wav (1 s)" ($codigoWav -eq "200" -and $tam -gt 30000) "$tam bytes" "07_audio_1s.wav"

# ---------- 5. Atuadores via rede ----------
$texto = Cabecalho "Atuadores (LEDs, buzzer e tela OLED) comandados via rede"
$sequencia = @(
    @{ rota = "/atuador?estado=normal"; esperado = "normal" },
    @{ rota = "/atuador?estado=alerta&falha=Teste%20de%20evidencia"; esperado = "alerta" },
    @{ rota = "/atuador?estado=normal&buzzer=1"; esperado = "normal" },
    @{ rota = "/atuador?estado=off"; esperado = "off" }
)
foreach ($passo in $sequencia) {
    $r = Pedir $passo.rota
    $texto += "`r`n==================== GET $($passo.rota) ====================`r`n" + $r.texto
    $ok = $r.codigo -eq 200 -and $r.corpo -match "`"estado`":\s*`"$($passo.esperado)`""
    Registrar "Comando $($passo.rota)" $ok "HTTP $($r.codigo)" "08_atuadores.txt"
    Start-Sleep -Milliseconds 1500
}
Salvar "08_atuadores.txt" $texto

# ---------- 6. Tratamento de erros ----------
$texto = Cabecalho "Pedidos invalidos: o servidor responde 400/404 em JSON e registra AVISO no log"
foreach ($caso in @(@{ rota = "/atuador?estado=xyz"; codigo = 400 }, @{ rota = "/audio.wav?ms=99999"; codigo = 400 },
                   @{ rota = "/rota-que-nao-existe"; codigo = 404 })) {
    $r = Pedir $caso.rota
    $texto += "`r`n==================== GET $($caso.rota) ====================`r`n" + $r.texto
    Registrar "Erro esperado em $($caso.rota)" ($r.codigo -eq $caso.codigo) "HTTP $($r.codigo) (esperado $($caso.codigo))" "09_erros.txt"
}
Salvar "09_erros.txt" $texto

# ---------- 7. Log persistente ----------
$r = Pedir "/log?linhas=200"
Salvar "10_log_flash.txt" ((Cabecalho "Log persistente lido da memoria flash do ESP32 (GET /log)") + $r.corpo)
$niveis = @("INFO", "AVISO", "ERRO") | Where-Object { $r.corpo -match "\[$_" }
Registrar "Log com data/hora e niveis" ($r.codigo -eq 200 -and $r.corpo -match "\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[") "niveis presentes: $($niveis -join ', ')" "10_log_flash.txt"

# ---------- Resumo ----------
$ok = ($resultados | Where-Object { $_.Ok }).Count
$linhas = $resultados | ForEach-Object { "| $($_.Teste) | $(if ($_.Ok) { 'OK' } else { 'FALHA' }) | $($_.Detalhe) | ``$($_.Arquivo)`` |" }
$resumo = @"
# Evidencias de teste - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Alvo: ``$base`` - cliente: ``$env:COMPUTERNAME`` - gerado por ``tools/coletar_evidencias.ps1``.

**$ok de $($resultados.Count) verificacoes passaram.**

| Teste | Resultado | Detalhe | Arquivo |
|---|---|---|---|
$($linhas -join "`r`n")
"@
Salvar "RESUMO.md" $resumo
Write-Host "`n$ok de $($resultados.Count) verificacoes passaram. Evidencias em: $pasta"

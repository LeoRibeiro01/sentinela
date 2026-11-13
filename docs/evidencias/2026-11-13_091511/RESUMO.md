# Evidencias de teste - 2026-11-13 09:16:08

Alvo: `http://172.20.10.8:80` - cliente: `LENOVO-NOTE` - gerado por `tools/coletar_evidencias.ps1`.

**18 de 18 verificacoes passaram.**

| Teste | Resultado | Detalhe | Arquivo |
|---|---|---|---|
| Ping (ICMP) | OK | houve perda; ver arquivo | `01_ping.txt` |
| ARP (MAC do ESP32 na rede) | OK | procure 172.20.10.8 na tabela | `02_arp.txt` |
| Porta TCP 80 aberta | OK | porta 81 fechada: True | `03_porta_tcp.txt` |
| Socket TCP + HTTP cru | OK | porta local 52480 | `04_socket_tcp.txt` |
| GET /info | OK | HTTP 200 | `05_rotas_consulta.txt` |
| GET /status | OK | HTTP 200 | `05_rotas_consulta.txt` |
| GET /sensor | OK | HTTP 200 | `05_rotas_consulta.txt` |
| IP, MAC e status da conexao em /status | OK | IP estacao: 172.20.10.8  MAC estacao: B0:CB:D8:CD:83:54  IP AP: 192.168.4.1  MAC AP: B0:CB:D8:CD:83:55  Wi-Fi: iPhone conectado=True  hora: 2026-11-13 09:15:53 | `05_rotas_consulta.txt` |
| Sensor em tempo real | OK | carimbos de tempo distintos: 5/5 | `06_sensor_tempo_real.txt` |
| GET /audio.wav (1 s) | OK | 32044 bytes | `07_audio_1s.wav` |
| Comando /atuador?estado=normal | OK | HTTP 200 | `08_atuadores.txt` |
| Comando /atuador?estado=alerta&falha=Teste%20de%20evidencia | OK | HTTP 200 | `08_atuadores.txt` |
| Comando /atuador?estado=normal&buzzer=1 | OK | HTTP 200 | `08_atuadores.txt` |
| Comando /atuador?estado=off | OK | HTTP 200 | `08_atuadores.txt` |
| Erro esperado em /atuador?estado=xyz | OK | HTTP 400 (esperado 400) | `09_erros.txt` |
| Erro esperado em /audio.wav?ms=99999 | OK | HTTP 400 (esperado 400) | `09_erros.txt` |
| Erro esperado em /rota-que-nao-existe | OK | HTTP 404 (esperado 404) | `09_erros.txt` |
| Log com data/hora e niveis | OK | niveis presentes: INFO, AVISO | `10_log_flash.txt` |

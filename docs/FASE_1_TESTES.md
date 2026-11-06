# Fase 1 — roteiro de validação do firmware

## Ambiente e compilação

- Arduino CLI portátil 1.5.1 instalado em `.tools/arduino-cli` (ignorado pelo Git); o `winget` encontrou o pacote, mas não aplicou o instalador.
- Core `esp32:esp32` 2.0.17 instalado localmente; FQBN selecionado `esp32:esp32:esp32`.
- Porta serial detectada: `COM6`. `arduino-cli board list` mostra dispositivo USB serial, placa ainda desconhecida.
- Sketch de áudio compilado: passou; 268.769 bytes de programa e 21.568 bytes de globais.
- Firmware principal compilado: passou; 773.189 bytes de programa (58%) e 110.692 bytes de globais (33%), restando 216.988 bytes de RAM dinâmica.
- Upload, API, taxa real, WAV, sensor durante download e heap em execução: pendentes de validação física.

## Compilação e upload

```powershell
.tools\arduino-cli\arduino-cli.exe --config-file .tools\arduino-cli\arduino-cli.yaml compile --fqbn esp32:esp32:esp32 src/esp32/esp32_server
.tools\arduino-cli\arduino-cli.exe --config-file .tools\arduino-cli\arduino-cli.yaml upload -p COM6 --fqbn esp32:esp32:esp32 src/esp32/esp32_server
.tools\arduino-cli\arduino-cli.exe --config-file .tools\arduino-cli\arduino-cli.yaml monitor -p COM6 -c baudrate=115200
```

Confirme no monitor `Ponto de acesso: SENTINELA`, `IP: 192.168.4.1` e `Servidor HTTP pronto`. Conecte o notebook ao AP com senha `sentinela123`.

## Verificações HTTP

```powershell
curl.exe -i http://192.168.4.1/
curl.exe -i http://192.168.4.1/status
curl.exe -i http://192.168.4.1/sensor
curl.exe -i http://192.168.4.1/atuador?estado=normal
curl.exe -i http://192.168.4.1/atuador?estado=alerta
curl.exe -i http://192.168.4.1/atuador?estado=off
curl.exe -i http://192.168.4.1/atuador?estado=teste
curl.exe -i "http://192.168.4.1/atuador?estado=normal&buzzer=1"
curl.exe -i "http://192.168.4.1/atuador?estado=alerta&buzzer=0"
curl.exe -i "http://192.168.4.1/config?modo=auto&limiar=45"
curl.exe -i http://192.168.4.1/config?modo=manual
curl.exe -i http://192.168.4.1/config?modo=invalido
curl.exe -i http://192.168.4.1/atuador?estado=invalido
curl.exe -i "http://192.168.4.1/audio.wav?ms=100"
curl.exe -i http://192.168.4.1/rota-inexistente
curl.exe -sS -D audio-headers.txt "http://192.168.4.1/audio.wav?ms=1000" -o audio-teste.wav
python -c "import wave; w=wave.open('audio-teste.wav'); print('canais=',w.getnchannels(),'bytes/amostra=',w.getsampwidth(),'Hz=',w.getframerate(),'segundos=',w.getnframes()/w.getframerate())"
```

O arquivo deve gerar status HTTP 200, `Content-Type: audio/wav` e `Content-Length: 32044` para fs=16 kHz (ou `44 + 2 × fs_real_hz × duração_s`). O script deve informar mono, 2 bytes/amostra, cerca de 16 kHz e 1,0 s. A rota deve rejeitar `ms=100` e aceitar o intervalo de 200 a 2000 ms.

## Teste crítico de áudio + AP

Com o MAX9814 em GPIO 34, sem atuadores externos, execute consultas a `/sensor` falando e batendo palmas. RMS/pico devem variar e `clipping` deve ser falso em uso normal. Observe `fs_real_hz` em `/status`; alvo de aceitação: aproximadamente 16 kHz. Em outro terminal, baixe `/audio.wav?ms=1000` repetidamente durante pelo menos 2 minutos e observe se as leituras continuam variando, sem zeros persistentes nem reinicialização.

Para repetir downloads por 2 min no PowerShell, use uma janela:

```powershell
1..120 | ForEach-Object { curl.exe -fsS "http://192.168.4.1/audio.wav?ms=1000" -o "$env:TEMP\sentinela.wav"; Start-Sleep -Milliseconds 100 }
```

Em outra janela, confira que o sensor continua ativo durante esse loop:

```powershell
1..120 | ForEach-Object { curl.exe -fsS http://192.168.4.1/sensor; Start-Sleep -Seconds 1 }
```

Após a aceitação inicial, mantenha o ESP32 ligado por 30 minutos; consulte `/status` a cada minuto e registre uptime e heap. Heap não deve cair continuamente e o uptime não deve zerar.

## Resultados

Compilações verificadas no host; resultados de execução na placa continuam pendentes. Preencher as medições físicas após executar o roteiro:

| Verificação | Resultado medido |
|---|---|
| Compilação do teste de áudio (core 2.0.17) | Passou: 268.769 bytes de programa |
| Compilação do firmware (core 2.0.17) | Passou: 773.189 bytes de programa; 110.692 bytes de globais |
| Rotas e códigos HTTP | Pendente |
| WAV: duração, taxa e reprodução | Pendente |
| Taxa real com AP ativo | Pendente |
| Sensor durante download contínuo | Pendente |
| 30 min: reinicializações e heap | Pendente |

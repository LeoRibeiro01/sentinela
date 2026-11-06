# Fase 1 — roteiro de testes do firmware

## O que já foi verificado (sem a placa)

| Verificação | Resultado |
|---|---|
| Compilação limpa `esp32_server` (core 2.0.17, `--warnings all`) | **Passou, 0 avisos**: 772 497 bytes de programa (58%), 110 716 bytes de globais (33%), 216 964 bytes livres para heap/pilhas |
| Compilação limpa `teste_audio` | **Passou**: 268 769 bytes (20%) |
| `tools/teste_fase1.py` (rotas, crítico, resistência, ESP32 fora do ar) contra servidor falso local que segue o contrato | **Passou** — valida o script de teste, **não** o firmware |
| Filtro de DC novo × antigo, simulado em Python (silêncio, DC 1550) | Antigo: RMS 32 (resíduo de DC); novo: RMS 8 (só o ruído) |

Tudo o que depende da placa (Wi-Fi, ADC, temporização, heap em execução) está **pendente** e deve ser preenchido na tabela de resultados abaixo.

## Comandos (PowerShell, na raiz do repositório)

```powershell
# Descobrir a porta (procure "Serial Port (USB)"; antes era COM6):
.tools\arduino-cli\arduino-cli.exe --config-file .tools\arduino-cli\arduino-cli.yaml board list
# Compilar e gravar:
.tools\arduino-cli\arduino-cli.exe --config-file .tools\arduino-cli\arduino-cli.yaml compile --fqbn esp32:esp32:esp32 src/esp32/esp32_server
.tools\arduino-cli\arduino-cli.exe --config-file .tools\arduino-cli\arduino-cli.yaml upload -p COM6 --fqbn esp32:esp32:esp32 src/esp32/esp32_server
# Monitor serial (Ctrl+C para sair):
.tools\arduino-cli\arduino-cli.exe --config-file .tools\arduino-cli\arduino-cli.yaml monitor -p COM6 -c baudrate=115200
```

Se o upload ficar em `Connecting....`, segure o botão **BOOT** da placa até começar a gravar.

## Roteiro na placa

**Passo 1 — boot e log serial (2 min).** Grave e abra o monitor. Deve aparecer `AP SENTINELA ativo em http://192.168.4.1/` e `Servidor HTTP pronto`. A cada 10 s surge uma linha `[saude] ...`. Confira:
- `fs=` entre 15 900 e 16 000 Hz;
- `perdidas=` 0 ou crescendo muito devagar;
- `int_max=` perto de 63 µs (até ~150 µs é aceitável);
- em silêncio, `adc=[a..b]` com valores no meio da faixa (por volta de 1200–1900), **nunca 0**.

Feche o monitor antes do passo 2 se a porta COM for necessária para outra coisa (não é necessária para os testes HTTP).

**Passo 2 — rotas (1 min).** Conecte o notebook ao Wi-Fi `SENTINELA` (senha `sentinela123`; o Windows vai avisar "sem internet": é esperado). Depois:

```powershell
python tools\teste_fase1.py rotas
```

Todas as linhas devem dar `[OK]`. O script salva `audio-teste.wav`: abra num player e confira se a sua voz soa natural (nem acelerada nem lenta). Durante o script, o **LED azul da placa** acende no `alerta` e pisca no `teste`.

**Passo 3 — teste crítico: áudio estável com Wi-Fi (2 min).**

```powershell
python tools\teste_fase1.py critico --minutos 2
```

Durante os 2 minutos: fale, bata palmas, fique em silêncio. O `rms` deve subir com o som e cair no silêncio, e `adc_min`/`adc_max` nunca devem ficar em 0. Ao final, todas as linhas devem dar `[OK]`. **Anote** `amostras_perdidas` e `intervalo_max_us`.

**Passo 4 — resistência (30 min).** Deixe o notebook parado, ainda ligado ao AP:

```powershell
python tools\teste_fase1.py resistencia --minutos 30
```

Deve passar sem reinício (o uptime nunca volta) e com heap estável. Gera um `resistencia_*.csv` (não versionado).

**Passo 5 — queda de conexão (1 min).** Com `python tools\teste_fase1.py critico --minutos 1` rodando, aperte **EN/RST** da placa. O script deve mostrar falhas temporárias e voltar a ler sozinho depois que o AP reaparece; o Windows pode levar até ~15 s para reconectar ao AP. (O tratamento completo da queda é do dashboard, na Fase 2.)

## Se algo falhar

| Sintoma | Causa provável / ação |
|---|---|
| `adc_max` = 0 ou `rms` sempre 0 | Fio OUT↔GPIO34 solto, ou MAX9814 sem 3V3/GND. Rode `src/esp32/teste_audio` para isolar o problema. |
| `clipping` true o tempo todo | Sinal alto demais: afaste o microfone ou confira se o GAIN está em VDD (40 dB) e não solto (60 dB). |
| `fs_real_hz` bem abaixo de 16 000, ou `amostras_perdidas` subindo rápido | Amostragem instável. Mande-me as linhas `[saude]`; o plano B é 8 kHz (mudar o divisor/alarme do timer). |
| Reinicia sozinho (uptime volta) | Copie o que o monitor serial mostra no reinício (`Guru Meditation`/`Brownout`). Brownout = cabo/porta USB fraca. |
| `curl`/script sem conexão | O notebook saiu do AP `SENTINELA` (o Windows às vezes troca para uma rede com internet). Desative "conectar automaticamente" nas outras redes. |

## Resultados medidos na placa (preencher)

| Verificação | Resultado |
|---|---|
| Boot: AP visível em até 15 s | Pendente |
| `teste_fase1.py rotas` | Pendente |
| WAV soa natural no player | Pendente |
| `fs_real_hz` com AP + download em loop | Pendente |
| `amostras_perdidas` / `intervalo_max_us` após 2 min | Pendente |
| Sem leituras zeradas durante o teste crítico | Pendente |
| 30 min: reinícios / heap início → fim | Pendente |
| Reconexão após RST | Pendente |

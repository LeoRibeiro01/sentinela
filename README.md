# SENTINELA — Diagnóstico acústico automotivo

Sistema ciberfísico que **escuta o motor** e ajuda a diagnosticar falhas. Um microfone (GY-MAX9814) ligado a um **ESP32** capta o som. O ESP32 cria a própria rede Wi-Fi e roda um **servidor HTTP**: entrega leituras e trechos de áudio e recebe comandos para LEDs e buzzer. Um **dashboard web** mostra tudo ao vivo. Um **serviço de IA** local (YAMNet + classificador) responde três perguntas sobre o áudio: *é som de carro?*, *está normal?* e *se não, qual a falha provável?* Depois acende o alerta.

> Apoio à decisão — não substitui um mecânico. As porcentagens exibidas são **probabilidade estimada pelo modelo**.

Disciplina: Conectividade em Sistemas Ciberfísicos (TDE) — Engenharia de Software, PUCPR.

## Integrantes

| Nome | RA |
|---|---|
| Leonardo Farias Ribeiro | [RA] |
| Leonardo Silva Sobrinho | [RA] |
| Nathan Banach | [RA] |

## Arquitetura

![Arquitetura](docs/arquitetura.png)

- **ESP32 = servidor** (requisito do regulamento): modo Access Point `SENTINELA` (senha `sentinela123`, IP `192.168.4.1`), `WebServer` na porta 80, rotas GET com JSON e CORS. Não depende de internet nem da rede da faculdade.
- **Núcleo obrigatório (sem IA):** ESP32 + dashboard falando direto por HTTP. Consulta o sensor, comanda os atuadores e mostra conectado/desconectado e o estado do sensor e dos atuadores.
- **Diferencial (IA):** `src/ai/server.py` roda no notebook (porta 5000), puxa áudio do ESP32, classifica e comanda o alerta. Se cair, o núcleo continua funcionando.
- Tudo **offline**: nenhum CDN, fonte externa ou chamada à internet em tempo de execução.

```text
sentinela/
├── docs/            # API, decisões, diagramas, métricas da IA, montagem, explicação do código
├── src/
│   ├── esp32/
│   │   ├── esp32_server/   # firmware: esp32_server.ino (Wi-Fi e rotas),
│   │   │                   #   captura_audio.* (ADC a 16 kHz), atuadores.* (LEDs/buzzer)
│   │   └── teste_audio/    # teste isolado do microfone
│   ├── client/      # dashboard: index.html, app.js, style.css (JS puro, sem build)
│   └── ai/          # server.py, train.py, prepare_dataset.py, record.py, analise.py, ...
├── tools/           # mock_esp32.py (simulador), teste_fase1.py (testes), baixar_yamnet.py
├── models/          # classificador.joblib + classes.json (o YAMNet não é versionado)
└── data/            # áudios brutos e de treino (não versionado)
```

## Hardware e pinagem

![Esquemático](docs/esquematico.png)

| Componente | Pino | Ligação |
|---|---|---|
| ESP32 DevKit v1 (WROOM-32, 30 pinos, sem PSRAM) | — | USB do notebook ou power bank 5000 mAh |
| GY-MAX9814 VDD / GND | 3V3 / GND | **Nunca 5 V** |
| GY-MAX9814 OUT | **GPIO34** | ADC1_CH6 (o ADC2 não funciona com Wi-Fi) |
| GY-MAX9814 GAIN / AR | VDD / solto | Ganho fixo de 40 dB |
| LED verde | **GPIO16** | 220 Ω → ânodo; cátodo → GND |
| LED vermelho | **GPIO17** | 220 Ω → ânodo; cátodo → GND |
| Buzzer ativo 5 V | **GPIO18** | 1 kΩ → base do NPN; emissor → GND; coletor → (−) do buzzer; (+) → VIN |
| LED azul onboard | GPIO2 | Espelha o alerta (testa a lógica sem peças) |

O passo a passo de montagem, os testes de cada atuador e a solução de problemas estão em **[docs/MONTAGEM_SEGUNDA.md](docs/MONTAGEM_SEGUNDA.md)**.

## API do ESP32 (somente GET)

Documentação completa, incluindo o serviço de IA: **[docs/API.md](docs/API.md)**. Todas as respostas trazem `Access-Control-Allow-Origin: *` e `Cache-Control: no-store`. Erros vêm em JSON (400 para parâmetro inválido, 404 para rota inexistente).

| Rota | Função |
|---|---|
| `/status` | Uptime, taxa real de amostragem, heap, modo e estado do atuador |
| `/sensor` | RMS, pico, nível 0–100 e clipping da última janela de ~250 ms |
| `/audio.wav?ms=1000` | Trecho mais recente em WAV PCM 16-bit mono (200–2000 ms) |
| `/atuador?estado=normal\|alerta\|off\|teste[&buzzer=0\|1]` | Comanda LEDs e buzzer |
| `/config?modo=auto\|manual&limiar=0-100` | Modo automático local por nível (fallback sem IA) |

```powershell
curl.exe http://192.168.4.1/sensor
curl.exe "http://192.168.4.1/atuador?estado=alerta"
```

## Instalação e execução

### 1. Firmware (Arduino CLI + core ESP32 2.0.17)

```powershell
# Se ainda não houver o Arduino CLI portátil em .tools\ (ver docs/DECISOES.md):
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@2.0.17

$cli = ".tools\arduino-cli\arduino-cli.exe"; $cfg = ".tools\arduino-cli\arduino-cli.yaml"
& $cli --config-file $cfg board list                                     # descobre a porta COM
& $cli --config-file $cfg compile --fqbn esp32:esp32:esp32 src/esp32/esp32_server
& $cli --config-file $cfg upload -p COM6 --fqbn esp32:esp32:esp32 src/esp32/esp32_server
```

Conecte o notebook ao Wi-Fi **SENTINELA** (senha `sentinela123`; o aviso "sem internet" é esperado).

### 2. Dashboard (não precisa instalar nada)

Dê **duplo clique em `src\client\index.html`**. O endereço padrão é `192.168.4.1`, e ele fica salvo no navegador. Com o serviço de IA rodando, também abre em `http://localhost:5000/`.

### 3. Serviço de IA (Python 3.11)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r src\ai\requirements.txt
.venv\Scripts\python tools\baixar_yamnet.py          # 1 vez, com internet; depois roda offline
.venv\Scripts\python src\ai\server.py                # http://localhost:5000/
```

Treino (reproduzível, 1 comando cada; já existe um modelo treinado em `models/`):

```powershell
.venv\Scripts\python src\ai\prepare_dataset.py       # data/raw/* -> data/train/ (ver docs/DATASETS.md)
.venv\Scripts\python src\ai\train.py                 # -> models/ e docs/metricas_ia.md
.venv\Scripts\python src\ai\record.py --classe normal --segundos 60   # grava áudio rotulado pela placa
```

Atalho: **duplo clique em `tools\iniciar_ia.bat`** sobe o serviço e abre o dashboard.

Kit de sons para a demonstração (trechos de teste que o modelo acerta, 15 s cada, para tocar no celular ou no notebook perto do microfone): `.venv\Scripts\python tools\montar_sons_demo.py` → `data\demo_sons\`.

### 4. Sem a placa (simulador)

```powershell
python tools\mock_esp32.py                                    # ESP32 simulado em 127.0.0.1:8080
python tools\mock_esp32.py --wav-dir data\raw\kwerimoto\prepared\test\engine_knock   # tocando áudio real
.venv\Scripts\python src\ai\server.py --esp32 127.0.0.1:8080
```

Abra `http://localhost:5000/?esp32=127.0.0.1:8080`.

## Inteligência artificial

```text
áudio (1 s) ─► tem som? ─não─► "sinal fraco"
                 │sim
                 ▼
     YAMNet (Google, 521 classes) ─► embedding de 1024 números por quadro de 0,96 s
                 ▼
     porteiro: é carro?  (classificador + veto do YAMNet p/ fala, música, animais)
                 │sim                                  └─não─► "não é motor de carro"
                 ▼
     diagnóstico: normal · batida de pino · ignição · correia · tucho ─► confiança ≥ 60%? ─não─► "inconclusivo"
                 ▼ sim
     cartão de diagnóstico (causas, o que verificar, urgência) + comando /atuador
```

- Dados: [KweriMoto Engine Sounds](https://huggingface.co/datasets/rayyyyy007/kwerimoto-engine-sounds) (normal, knock, misfire), [MyDataSet](https://huggingface.co/datasets/RashmiKarunarathne/MyDataSet) (correia, tucho; gravado com celular), [ESC-50](https://github.com/karolpiczak/ESC-50) (sons ambientais que não são carro) e [amrrashed](https://github.com/amrrashed/Sound-Based-Vehicle-Diagnostics-Emergency-Signal-Recognition) (falhas mecânicas e sons que não são carro). Os WAVs segmentados do amrrashed estão **corrompidos** (ruído branco); usamos as gravações originais. Detalhes em [docs/DATASETS.md](docs/DATASETS.md).
- Divisão treino/validação/teste **por gravação** (sem vazamento); hiperparâmetros e limiar escolhidos na validação.
- Resultados no teste ([docs/metricas_ia.md](docs/metricas_ia.md)): porteiro ~94% de acerto (rejeita ~94% de 249 sons de sala do ESC-50); diagnóstico ~82% em 5 classes (~81% no formato do botão de 5 s). No binário normal × falha, precisão ~94% e revocação ~83%. Knock **real** nunca visto: ~90% reconhecido. Com áudio degradado (simulando celular + MAX9814), ~73%.
- Limitações honestas: dados da internet e parte sintética. O som captado pelo MAX9814 é diferente, e a melhoria mais eficaz é gravar com `record.py` e retreinar.

## Testes

- `python tools\teste_fase1.py rotas | critico | resistencia` — aceitação do firmware (rotas, áudio estável com Wi-Fi, 30 min de operação). Roteiro: [docs/FASE_1_TESTES.md](docs/FASE_1_TESTES.md).
- Queda de conexão: o dashboard faz polling com timeout de 2 s. Após 2 falhas mostra **DESCONECTADO**, desabilita os comandos e reconecta sozinho. O serviço de IA mostra "ESP32 sem resposta" e volta sozinho.
- Testes de aceitação da montagem: [docs/MONTAGEM_SEGUNDA.md](docs/MONTAGEM_SEGUNDA.md).

## Documentação

| Documento | Conteúdo |
|---|---|
| [docs/API.md](docs/API.md) | Rotas do ESP32 e do serviço de IA |
| [docs/EXPLICACAO_CODIGO.md](docs/EXPLICACAO_CODIGO.md) | Cada arquivo: propósito, fluxo, funções e perguntas prováveis da defesa |
| [docs/DECISOES.md](docs/DECISOES.md) | Decisões técnicas e porquês |
| [docs/metricas_ia.md](docs/metricas_ia.md) | Métricas do modelo (geradas pelo `train.py`) |
| [docs/DATASETS.md](docs/DATASETS.md) | Origem, licença e problemas dos dados |
| [docs/MONTAGEM_SEGUNDA.md](docs/MONTAGEM_SEGUNDA.md) | Ligação, energização, aceitação, plano B |

## Screenshots e vídeo

![Dashboard](docs/screenshots/dashboard.png)

Vídeo da demonstração: *[adicionar link após a apresentação]*.

## Trabalhos futuros

Nuvem/MQTT, I2S/INMP441/ESP32-S3, vários microfones para localizar a falha, app mobile, autenticação, banco de dados, TinyML dentro do ESP32, display OLED SSD1306, mais classes de falha mecânica (rolamento, escapamento, freio) quando houver dados suficientes.

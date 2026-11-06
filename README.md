# Sentinela — diagnóstico acústico automotivo

O Sentinela lê o módulo analógico GY-MAX9814 e disponibiliza áudio e estado por uma API HTTP hospedada no próprio ESP32. O ESP32 cria a rede Wi-Fi `SENTINELA` (`192.168.4.1`); o núcleo de monitoramento e controle funciona sem nuvem ou serviço de IA.

## Integrantes

- Leonardo Farias Ribeiro — RA: [RA]
- Leonardo Silva Sobrinho — RA: [RA]
- Nathan Banach — RA: [RA]

## Arquitetura e estrutura

Notebook (cliente HTTP) ⇄ ponto de acesso Wi-Fi do ESP32 ⇄ MAX9814 no GPIO 34; o ESP32 também comanda LEDs nos GPIOs 16/17, buzzer no GPIO 18 e LED onboard GPIO 2.

```text
sentinela/
├── docs/                 # API.md, DECISOES.md, FASE_1_TESTES.md, diagramas
├── src/
│   ├── esp32/
│   │   ├── esp32_server/ # firmware: esp32_server.ino (rede/rotas),
│   │   │                 #   captura_audio.* (ADC a 16 kHz), atuadores.* (LEDs/buzzer)
│   │   └── teste_audio/  # teste isolado do microfone
│   ├── client/           # dashboard (será refeito offline na Fase 2)
│   └── ai/               # serviço de IA (Fase 3)
├── tools/                # teste_fase1.py (testes de aceitação do firmware)
├── models/               # classificador treinado (Fase 3)
└── data/                 # áudios de treino (não versionado)
```

Diagramas: [arquitetura](docs/arquitetura.png) e [ligações](docs/esquematico.png). As fontes vetoriais SVG e o script de geração também estão em `docs/`.

## Hardware e pinagem

| Módulo/peça | Pino ESP32 | Ligação |
|---|---:|---|
| GY-MAX9814 VDD | 3V3 | Alimentação do módulo |
| GY-MAX9814 GND | GND | Terra comum |
| GY-MAX9814 OUT | GPIO 34 | Saída analógica; ADC1, somente entrada |
| GY-MAX9814 GAIN | 3V3 | Ganho fixo de 40 dB; manter igual durante gravações |
| GY-MAX9814 AR | — | Deixar sem conexão |
| LED verde | GPIO 16 | HIGH acende; resistor de 220 Ω em série para GND |
| LED vermelho | GPIO 17 | HIGH acende; resistor de 220 Ω em série para GND |
| Buzzer ativo | GPIO 18 | HIGH apita; usar driver se exceder corrente do pino |
| LED onboard | GPIO 2 | Espelha o estado de alerta |

O firmware mantém as saídas desligadas na inicialização e funciona mesmo sem os atuadores externos. O GPIO 34 nunca deve receber mais de 3,3 V.

## Instalação e execução

1. Instale Arduino CLI e o core `esp32:esp32` 2.0.17; selecione o FQBN `esp32:esp32:esp32`.
2. Compile com `arduino-cli compile --fqbn esp32:esp32:esp32 src/esp32/esp32_server`.
3. Para enviar, conecte a placa e use `arduino-cli upload -p COMx --fqbn esp32:esp32:esp32 src/esp32/esp32_server` (troque `COMx` pela porta identificada).
4. Abra o Monitor Serial em 115200 baud. Conecte o notebook à rede `SENTINELA`, senha `sentinela123`.
5. Acesse `http://192.168.4.1/status`. A rede é local e deliberadamente não fornece acesso à internet.

Para testar somente o microfone, carregue `src/esp32/teste_audio/teste_audio.ino` e observe a leitura no Monitor Serial enquanto fala ou bate palmas.

## API do firmware (somente GET)

Documentação completa em [docs/API.md](docs/API.md). Todas as respostas trazem CORS aberto e `Cache-Control: no-store`; os erros vêm em JSON (400/404).

| Rota | Função |
|---|---|
| `/status` | Uptime, taxa real de amostragem, heap, modo e estado do atuador |
| `/sensor` | RMS, pico, nível 0–100 e clipping da última janela de ~250 ms |
| `/audio.wav?ms=1000` | Trecho mais recente em WAV PCM 16-bit mono (200–2000 ms) |
| `/atuador?estado=normal\|alerta\|off\|teste[&buzzer=0\|1]` | Comanda LEDs e buzzer |
| `/config?modo=auto\|manual&limiar=0-100` | Modo automático local (fallback sem IA) |

Exemplo no PowerShell: `curl.exe http://192.168.4.1/sensor`. Teste automático de todas as rotas: `python tools\teste_fase1.py rotas` (roteiro completo em [docs/FASE_1_TESTES.md](docs/FASE_1_TESTES.md)).

## Progresso e validação

O roteiro da Fase 1 e os resultados disponíveis estão em [docs/FASE_1_TESTES.md](docs/FASE_1_TESTES.md). A interface web atual ainda é da versão anterior e carrega Tailwind/fontes por CDN; removê-los e alinhar o painel à API local é trabalho da Fase 2.

Screenshots e vídeo da demonstração serão adicionados após os testes com a placa.

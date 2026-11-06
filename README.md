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
├── docs/                      # API e roteiro/resultados das Fases 0 e 1
├── src/esp32/
│   ├── esp32_server/esp32_server.ino
│   └── teste_audio/teste_audio.ino
└── src/client/                # dashboard existente; fase 2 vai deixá-lo offline
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

Todas as respostas incluem CORS aberto e `Cache-Control: no-store`; erros são JSON UTF-8.

| Rota | Comportamento |
|---|---|
| `/` | Nome, versão e IP do sistema |
| `/status` | `ok`, versão, uptime, taxa real de amostragem, heap, modo e estado/pinos do atuador |
| `/sensor` | RMS, pico, nível (0–100), clipping e instante da última janela de ~250 ms |
| `/audio.wav?ms=1000` | Trecho PCM 16-bit mono recente; `ms` entre 200 e 2000 |
| `/atuador?estado=normal` | LED verde |
| `/atuador?estado=alerta` | LED vermelho, buzzer e LED onboard |
| `/atuador?estado=off` | Desliga todas as saídas |
| `/atuador?estado=teste` | Sequência curta nas saídas físicas |
| `/atuador?estado=normal&buzzer=1` | Controle opcional do buzzer em estado normal; `0` desliga |
| `/config?modo=auto&limiar=45` | Ajusta modo e limiar automático (0–100, três janelas acima do limiar) |
| `/config?modo=manual` | Retorna o controle dos atuadores ao modo manual |

Exemplo no PowerShell: `curl.exe http://192.168.4.1/sensor`.

## Progresso e validação

O roteiro da Fase 1 e os resultados disponíveis estão em [docs/FASE_1_TESTES.md](docs/FASE_1_TESTES.md). A interface web atual ainda é da versão anterior e carrega Tailwind/fontes por CDN; removê-los e alinhar o painel à API local é trabalho da Fase 2.

Screenshots e vídeo da demonstração serão adicionados após os testes com a placa.

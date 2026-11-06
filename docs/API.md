# API HTTP do ESP32

O servidor roda no ESP32 DevKit v1 em `192.168.4.1:80`. Rotas aceitam GET. JSON usa UTF-8, inclui `Access-Control-Allow-Origin: *` e `Cache-Control: no-store`.

| Caminho | Sucesso | Erro de entrada |
|---|---|---|
| `/` | `{"nome":"Sentinela","versao":"1.0","ip":"192.168.4.1"}` | — |
| `/status` | Estado operacional, heap, taxa medida e saídas digitais | — |
| `/sensor` | `{"rms":N,"pico":N,"nivel":0-100,"clipping":false,"ts_ms":N}` | — |
| `/audio.wav?ms=200..2000` | WAV PCM mono 16-bit, taxa medida, duração pedida e Content-Length | HTTP 400 para faixa/formato inválido; 503 antes de preencher o buffer |
| `/atuador?estado=normal\|alerta\|off\|teste` | Novo estado e valores das saídas | HTTP 400 para estado/parâmetro inválido |
| `/config?modo=auto\|manual&limiar=0..100` | Modo e limiar ativos | HTTP 400 para modo/limiar inválido |

`nivel` é uma escala relativa para a demonstração, calculada do RMS em contagens do ADC; não representa dB SPL. `fs_real_hz` vem da contagem de amostras observada em um segundo. O timer usa intervalo de 62 μs, portanto a taxa-alvo teórica é aproximadamente 16,1 kHz; a taxa observada será registrada durante o teste na placa.

O modo `auto` aciona alerta após três janelas (~250 ms cada) acima do limiar e retorna a `normal` quando o nível cai. `teste` executa uma sequência de um segundo e retorna a `normal`.

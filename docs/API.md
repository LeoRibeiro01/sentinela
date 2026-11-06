# API HTTP do ESP32

Servidor HTTP no próprio ESP32 (`WebServer`, porta 80), acessível em `http://192.168.4.1` depois de conectar à rede Wi-Fi `SENTINELA` (senha `sentinela123`).

- Somente **GET**.
- Todas as respostas têm `Access-Control-Allow-Origin: *` e `Cache-Control: no-store`.
- JSON em UTF-8. Parâmetro inválido → **400** `{"erro":"..."}`. Rota inexistente → **404** `{"erro":"..."}`.
- O servidor atende **um cliente por vez**: faça as consultas em sequência (polling), não em paralelo.

## `GET /status`

Saúde do sistema e estado do atuador.

```json
{"ok":true,"versao":"1.0","uptime_s":125,"fs_real_hz":16000,"heap_livre":201234,
 "heap_minimo":198000,"modo":"manual","limiar":45,
 "atuador":{"estado":"normal","verde":1,"vermelho":0,"buzzer":0},
 "amostras_perdidas":0,"intervalo_max_us":64,"clientes_wifi":1}
```

| Campo | Significado |
|---|---|
| `uptime_s` | Segundos desde o boot. Se voltar a zero, a placa reiniciou. |
| `fs_real_hz` | Amostras de áudio efetivamente lidas no último segundo (alvo: 16000). |
| `heap_livre` / `heap_minimo` | Memória livre agora e o menor valor desde o boot (bytes). |
| `modo` / `limiar` | `manual` ou `auto`; limiar de nível (0–100) usado no modo auto. |
| `atuador` | Estado lógico e valor de cada saída (1 = ligada). |
| `amostras_perdidas` | Ticks do timer sem leitura desde o boot (ideal: 0 ou quase 0). |
| `intervalo_max_us` | Maior intervalo entre duas amostras no último segundo (ideal: ~63 µs). |
| `clientes_wifi` | Dispositivos conectados ao AP. |

## `GET /sensor`

Métricas da última janela de ~250 ms (4000 amostras), sem o nível DC.

```json
{"rms":42,"pico":180,"nivel":7,"clipping":false,"ts_ms":125000,"adc_min":1380,"adc_max":1720}
```

| Campo | Significado |
|---|---|
| `rms` | RMS em contagens do ADC (0–2048). |
| `pico` | Maior desvio absoluto em relação ao DC. |
| `nivel` | Escala relativa 0–100 (RMS 600 = 100). **Não é dB SPL.** |
| `clipping` | `true` se o ADC encostou em 0 ou 4095 na janela. |
| `ts_ms` | `millis()` do fechamento da janela; avança a cada ~250 ms. |
| `adc_min` / `adc_max` | Leituras brutas extremas da janela (diagnóstico: `adc_max` = 0 significa ADC zerado). |

## `GET /audio.wav?ms=1000`

WAV PCM 16-bit mono com o trecho **mais recente** do buffer. `ms` de **200 a 2000** (padrão 1000). A taxa no cabeçalho é `fs_real_hz`; `Content-Length` = 44 + 2 × amostras.

- 400 se `ms` estiver fora da faixa ou não for inteiro.
- 503 nos primeiros instantes após o boot, enquanto o buffer ainda não tem amostras suficientes.

## `GET /atuador?estado=normal|alerta|off|teste[&buzzer=0|1]`

| `estado` | Efeito |
|---|---|
| `normal` | LED verde aceso. |
| `alerta` | LED vermelho + buzzer + LED azul onboard (GPIO2). |
| `off` | Tudo apagado. |
| `teste` | ~2 s: pisca verde/vermelho duas vezes, beep de 0,5 s; depois volta ao estado anterior. |

`buzzer=1`/`0` força o buzzer ligado/desligado junto com `normal` ou `alerta` (ex.: alerta silencioso com `estado=alerta&buzzer=0`).

```json
{"ok":true,"atuador":{"estado":"alerta","verde":0,"vermelho":1,"buzzer":1}}
```

## `GET /config?modo=auto|manual&limiar=0-100`

Os dois parâmetros são opcionais. Se algum for inválido, nada é alterado.

No modo **auto** (fallback sem IA), o próprio ESP32 liga o `alerta` quando `nivel > limiar` por 3 janelas seguidas (~0,75 s) e volta a `normal` depois de 8 janelas abaixo (~2 s). Ao entrar em auto com o atuador em `off`, ele passa a `normal`. Comandos manuais em `/atuador` continuam valendo até a próxima transição automática. **O serviço de IA deve usar o modo `manual`**, senão os dois disputam o atuador.

```json
{"ok":true,"modo":"auto","limiar":45}
```

## `GET /`

Identificação e lista de rotas.

## Exemplos (PowerShell)

```powershell
curl.exe http://192.168.4.1/status
curl.exe "http://192.168.4.1/atuador?estado=alerta&buzzer=0"
curl.exe "http://192.168.4.1/audio.wav?ms=1000" -o trecho.wav
```

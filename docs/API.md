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

---

# API do serviço de IA (`src/ai/server.py`, `http://localhost:5000`)

Roda no notebook. Também só aceita GET, com CORS aberto e `Cache-Control: no-store`. Se estiver fora do ar, o dashboard mostra "IA: OFFLINE" e o resto continua funcionando.

## `GET /` (e `/app.js`, `/style.css`)

Serve o dashboard (`src/client`). Aceita `?esp32=ENDERECO` para escolher o ESP32 (ex.: `?esp32=127.0.0.1:8080` com o simulador).

## `GET /api/resultado`

Estado ao vivo: a cada ~1 s, analisa os últimos ~5 s de áudio (5 janelas de 1 s, o mesmo formato do botão). Silêncio zera essa memória.

```json
{"ok":true,"modelo":true,"classes":["normal","falha_batida_pino","falha_ignicao","falha_correia","falha_tucho"],
 "esp32":"192.168.4.1","demo":false,"ia_atuador":false,"limiar_silencio":0.004,"limiar_confianca":60,
 "esp32_ok":true,"estado_suave":"normal","diagnosticando":false,
 "ao_vivo":{"texto":"Motor normal","status":"ok","confianca":79,"carro_prob":99,"rms_bruto":0.06,
            "top3":[{"classe":"normal","nome":"Motor normal","prob":79}, ...]},
 "historico":[{"hora":"23:29:17","texto":"Batida de pino"}, ...]}
```

`ao_vivo.status`: `ok` · `sinal_fraco` · `nao_carro` · `easter_egg` (modo demo) · `sem_modelo` · `esp32_offline`.
`estado_suave`: decisão por maioria de 3 dos últimos 5 votos confiantes (`normal`/`alerta`). Com `ia_atuador` ligado, é enviada ao `/atuador` **somente quando muda**.

## `GET /api/diagnostico?segundos=5`

Captura `segundos` janelas de 1 s (1 a 10), descarta as silenciosas, analisa o restante junto e responde em ~6 s.

```json
{"status":"ok","top":"falha_batida_pino","top_nome":"Batida de pino","confianca":85,"carro_prob":99,
 "som_detectado":"motor","janelas_validas":5,"janelas_total":5,"atuador":"alerta",
 "classes":[{"classe":"falha_batida_pino","nome":"Batida de pino","prob":85}, ...],
 "diagnostico":{"titulo":"Possível batida de pino (detonação)","causas_provaveis":["..."],
                "o_que_verificar":["..."],"urgencia":"media","aviso":"Apoio à decisão: ..."}}
```

| `status` | Quando | Atuador |
|---|---|---|
| `ok` | confiança do 1º colocado ≥ limiar (padrão 60%) | `alerta` se não for `normal`; senão `normal` |
| `inconclusivo` | confiança abaixo do limiar (o sistema não finge certeza) | `normal` |
| `sinal_fraco` | menos de 40% das janelas com som ("aproxime o microfone") | inalterado |
| `nao_carro` | o porteiro ou o veto do YAMNet dizem que não é motor de carro | inalterado |
| `erro` | ESP32 não respondeu ou modelo ausente (`erro` traz o motivo) | inalterado |

409 se já houver um diagnóstico em andamento; 400 se `segundos` estiver fora de 1–10.

## `GET /api/config`

Parâmetros opcionais: `esp32=ENDERECO`, `demo=0|1` (easter eggs de animais), `ia_atuador=0|1` (IA comanda os LEDs ao vivo), `limiar_silencio=0..0.5` (RMS), `limiar_confianca=0..100`. Responde com a configuração atual.

## `GET /api/calibrar`

Mede 3 s em silêncio e ajusta `limiar_silencio` para 2,5× o maior RMS medido (mínimo 0,002). Responde `{"ok":true,"rms_medidos":[...],"limiar_silencio":N}`.

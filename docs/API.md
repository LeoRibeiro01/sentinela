# API HTTP do ESP32

Servidor HTTP no próprio ESP32 (`WebServer`, **porta TCP 80**, modo passivo aguardando conexões). Endereços:

- `http://192.168.4.1` — pela rede própria `SENTINELA` (senha `sentinela123`), sempre ativa;
- `http://<IP da estação>` ou `http://sentinela.local` — pela rede Wi-Fi configurada em `/wifi` (o IP aparece na tela OLED e em `/status`).

Regras gerais:

- Somente **GET**.
- Todas as respostas têm `Access-Control-Allow-Origin: *` e `Cache-Control: no-store`.
- JSON em UTF-8. Parâmetro inválido → **400** `{"erro":"..."}`. Rota inexistente → **404** `{"erro":"..."}`.
- O servidor atende **um cliente por vez**: faça as consultas em sequência (polling), não em paralelo.
- Todo pedido inválido (400/404) e todo comando que muda estado é registrado no **log persistente** (`/log`), com o IP do cliente.

## `GET /`

O **dashboard**: HTML + CSS + JS num arquivo só, gravado na flash (`pagina_web.h`, gerado por `tools/gerar_pagina_esp32.py`) e enviado com `Content-Encoding: gzip` e `Cache-Control: no-store` (~17 KB). Com a placa desligada, a página não abre.

## `GET /status`

Saúde do sistema, **rede (IP e MAC)**, data/hora e estado dos atuadores.

```json
{"ok":true,"versao":"2.0","boot":7,"uptime_s":125,"hora":"2026-11-11 14:03:22","hora_ok":true,
 "fs_real_hz":16000,"heap_livre":160234,"heap_minimo":151000,"modo":"manual","limiar":45,
 "atuador":{"estado":"alerta","verde":0,"vermelho":1,"buzzer":1,"tela":true,"falha":"Batida de pino"},
 "rede":{"modo":"ap+sta","ap_ssid":"SENTINELA","ap_ip":"192.168.4.1","ap_mac":"24:6F:28:AA:BB:CD",
         "clientes_ap":1,"sta_ssid":"HotspotEquipe","sta_conectado":true,"sta_ip":"192.168.43.120",
         "sta_mac":"24:6F:28:AA:BB:CC","rssi":-58,"mdns":"sentinela.local"},
 "amostras_perdidas":0,"intervalo_max_us":64,"clientes_wifi":1,"laco_hz":980}
```

| Campo | Significado |
|---|---|
| `boot` | Quantas vezes a placa já ligou (contador na NVS). |
| `hora` / `hora_ok` | Data e hora da placa (fuso de Brasília). `hora_ok=false` = relógio ainda não ajustado (sem NTP e sem `/relogio`). |
| `rede.modo` | `ap` (só a rede própria) ou `ap+sta` (também conectada/tentando conectar a uma rede). |
| `rede.ap_*` | Rede própria: nome, IP, **MAC** da interface AP e nº de clientes. |
| `rede.sta_*` | Estação: rede configurada, se está conectada, **IP** recebido por DHCP e **MAC**. |
| `rede.rssi` | Intensidade do sinal da rede da estação (dBm; quanto mais perto de 0, melhor). |
| `atuador.tela` | `true` se a tela OLED foi detectada no I2C. |
| `atuador.falha` | Texto mostrado na tela (vazio = mensagem padrão do estado). |
| `uptime_s` | Segundos desde o boot. Se voltar a zero, a placa reiniciou. |
| `fs_real_hz` | Amostras de áudio efetivamente lidas no último segundo (alvo: 16000). |
| `heap_livre` / `heap_minimo` | Memória livre agora e o menor valor desde o boot (bytes). |
| `modo` / `limiar` | `manual` ou `auto`; limiar de nível (0–100) usado no modo auto. |
| `atuador` | Estado lógico e valor de cada saída (1 = ligada). |
| `amostras_perdidas` | Ticks do timer sem leitura desde o boot (ideal: 0 ou quase 0). |
| `intervalo_max_us` | Maior intervalo entre duas amostras no último segundo (ideal: ~63 µs). |
| `clientes_wifi` | Dispositivos conectados ao AP. |
| `laco_hz` | Voltas por segundo da tarefa que atende o HTTP (diagnóstico de desempenho). |

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

## `GET /atuador?estado=normal|alerta|off|teste[&buzzer=0|1][&falha=texto]`

| `estado` | Tela OLED | LEDs e buzzer |
|---|---|---|
| `normal` | "NORMAL" + texto (padrão: "Motor normal") | LED verde aceso |
| `alerta` | "ALERTA" piscando + texto da falha (padrão: "Falha detectada") | LED vermelho + buzzer + LED azul onboard (GPIO2) |
| `off` | "DESLIGADO" + "Aguardando comando" | tudo apagado |
| `teste` | "TESTE" | ~2 s: pisca verde/vermelho, beep de 0,5 s; depois volta ao estado anterior |

- `buzzer=1`/`0` força o buzzer ligado/desligado junto com `normal` ou `alerta` (ex.: alerta silencioso com `estado=alerta&buzzer=0`).
- `falha` (opcional, até 40 bytes UTF-8, sem aspas nem barras): texto exibido na tela, por exemplo a falha diagnosticada pela IA (`falha=Batida%20de%20pino%20(78%25)`). Acentos viram letras simples na tela (a fonte do OLED não os tem). Sem `falha`, a tela mostra a mensagem padrão do estado.
- Cada mudança de estado vira uma linha no log (`AVISO` para alerta, `INFO` para os demais), com o IP de quem mandou.

```json
{"ok":true,"atuador":{"estado":"alerta","verde":0,"vermelho":1,"buzzer":1,"tela":true,"falha":"Batida de pino"}}
```

## `GET /config?modo=auto|manual&limiar=0-100`

Os dois parâmetros são opcionais. Se algum for inválido, nada é alterado.

No modo **auto** (fallback sem IA), o próprio ESP32 liga o `alerta` quando `nivel > limiar` por 3 janelas seguidas (~0,75 s) e volta a `normal` depois de 8 janelas abaixo (~2 s). Ao entrar em auto com o atuador em `off`, ele passa a `normal`. Comandos manuais em `/atuador` continuam valendo até a próxima transição automática. **O serviço de IA deve usar o modo `manual`**, senão os dois disputam o atuador.

```json
{"ok":true,"modo":"auto","limiar":45}
```

## `GET /log?linhas=100` · `GET /log?completo=1`

Log persistente na memória flash (LittleFS, arquivo `/log.txt`; ao passar de ~48 KB vira `/log_antigo.txt`). Resposta `text/plain; charset=utf-8`, uma ocorrência por linha:

```text
2026-11-11 14:00:02 [INFO ] === Boot #7: SENTINELA v2.0 ligado (energia ligada) ===
2026-11-11 14:00:03 [INFO ] Wi-Fi conectado a "HotspotEquipe": IP 192.168.43.120, sinal -58 dBm
2026-11-11 14:05:41 [AVISO] Conexão Wi-Fi com "HotspotEquipe" PERDIDA (motivo 200); reconectando
2026-11-11 14:05:58 [INFO ] Wi-Fi RECONECTADO a "HotspotEquipe" após 17 s: IP 192.168.43.120
2026-11-11 14:06:10 [AVISO] Atuador -> alerta | falha: Batida de pino (comando de 192.168.43.20)
2026-11-11 14:07:00 [ERRO ] Tela OLED parou de responder no I2C (fio solto?)
```

(Exemplo ilustrativo do formato.)

- `linhas` = 1 a 500 (padrão 100): as últimas linhas do arquivo atual. `completo=1`: os dois arquivos inteiros (antigo + atual).
- Eventos de antes do relógio ser ajustado (ex.: o boot) esperam até 90 s na RAM e são gravados com a hora corrigida; se o relógio não for ajustado nesse tempo, aparecem como `sem hora (+Ns)`.
- O que é registrado: boot e motivo do reinício (reinício inesperado = ERRO), ponto de acesso, conexão/queda/reconexão do Wi-Fi, entrada e saída de clientes do AP, comandos e mudanças de configuração, pedidos inválidos, tela detectada/perdida, ajuste do relógio, memória baixa e perda de amostras.

## `GET /wifi?ssid=NOME&senha=SENHA`

Configura a rede que a placa deve usar como **estação** e conecta (o AP `SENTINELA` continua ativo). Os dados ficam na NVS (sobrevivem a reinícios). `ssid=` vazio esquece a rede. A senha nunca vai para o log.

- 400 se o `ssid` tiver mais de 32 caracteres, aspas ou barras, ou se a senha não tiver 8 a 63 caracteres (vazia = rede aberta).
- A resposta sai **antes** de o rádio ser reconfigurado: `{"ok":true,"mensagem":"conectando; acompanhe em /status e /log"}`.
- Se a rede do roteador estiver noutro canal, o AP muda junto (o rádio é um só) e quem está no AP pode cair por alguns segundos e reconectar.

## `GET /relogio?epoch=1762790400`

Acerta a data e a hora (segundos desde 1970 em UTC, 10 dígitos). Usado automaticamente pelo dashboard quando `hora_ok` é `false` (placa sem internet para o NTP). Responde `{"ok":true,"hora":"2026-11-11 14:03:22"}`.

## `GET /info`

Identificação e lista de rotas.

## Exemplos (PowerShell)

```powershell
curl.exe http://192.168.4.1/status
curl.exe "http://192.168.4.1/atuador?estado=alerta&buzzer=0"
curl.exe "http://192.168.4.1/audio.wav?ms=1000" -o trecho.wav
curl.exe "http://192.168.4.1/atuador?estado=alerta&falha=Teste"
curl.exe "http://192.168.4.1/log?linhas=30"
curl.exe "http://192.168.4.1/wifi?ssid=MinhaRede&senha=12345678"
```

---

# API do serviço de IA (`src/ai/server.py`, `http://localhost:5000`)

Roda no notebook. Também só aceita GET, com CORS aberto e `Cache-Control: no-store`. Se estiver fora do ar, o dashboard mostra "IA: OFFLINE" e o resto continua funcionando.

## `GET /`

**Redireciona** (302) para `http://<esp32>/`: o dashboard é servido pela placa, não por este serviço. As respostas trazem `Access-Control-Allow-Private-Network: true` e o serviço responde ao `OPTIONS` de pré-verificação, porque a página vem do ESP32 (rede local) e chama `localhost`.

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
`estado_suave`: decisão por maioria de 3 dos últimos 5 votos confiantes (`normal`/`alerta`). Com `ia_atuador` ligado, é enviada ao `/atuador` **somente quando muda**, com `falha=IA: <nome da falha>` no alerta (aparece na tela OLED).

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
| `ok` | confiança do 1º colocado ≥ limiar (padrão 60%) | `alerta` se não for `normal`; senão `normal` (tela: "<falha> (NN%)") |
| `inconclusivo` | confiança abaixo do limiar (o sistema não finge certeza) | `normal` (tela: "Diagnostico inconclusivo") |
| `sinal_fraco` | menos de 40% das janelas com som ("aproxime o microfone") | inalterado |
| `nao_carro` | o porteiro ou o veto do YAMNet dizem que não é motor de carro | inalterado |
| `erro` | ESP32 não respondeu ou modelo ausente (`erro` traz o motivo) | inalterado |

409 se já houver um diagnóstico em andamento; 400 se `segundos` estiver fora de 1–10.

## `GET /api/config`

Parâmetros opcionais: `esp32=ENDERECO`, `demo=0|1` (easter eggs de animais), `ia_atuador=0|1` (IA comanda os LEDs ao vivo), `limiar_silencio=0..0.5` (RMS), `limiar_confianca=0..100`. Responde com a configuração atual.

## `GET /api/calibrar`

Mede 3 s em silêncio e ajusta `limiar_silencio` para 2,5× o maior RMS medido (mínimo 0,002). Responde `{"ok":true,"rms_medidos":[...],"limiar_silencio":N}`.

# Registro de decisões técnicas

Cada decisão: o que foi decidido e por quê. Mais recentes no fim.

## Fases 0 e 1 — ambiente e firmware

- **Arduino CLI portátil em `.tools/`** (1.5.1, ignorado pelo Git) com core `esp32:esp32` **2.0.17** e FQBN `esp32:esp32:esp32`. O `winget` encontrou o pacote, mas não concluiu a instalação; a versão portátil evita depender de PATH/admin. Em outra máquina, basta seguir o README.
- **Rede em modo Access Point** fixo (`SENTINELA` / `sentinela123` / `192.168.4.1`), canal 6, até 4 clientes, `WiFi.setSleep(false)` e `WiFi.persistent(false)` (não grava configuração na flash a cada boot). Redes de faculdade costumam isolar dispositivos; o AP elimina essa dependência e funciona sem internet.
- **Firmware dividido em 3 arquivos**: `captura_audio.*` (amostragem), `atuadores.*` (pinos e modo auto) e `esp32_server.ino` (Wi-Fi e rotas). Um arquivo = uma responsabilidade, o que facilita a explicação na defesa.
- **Amostragem: timer de hardware + tarefa FreeRTOS no núcleo 1** (opção 1 do CLAUDE.md). O timer 0 usa divisor 40 (2 MHz) e alarme de 125 ticks, ou seja, **16 000 Hz exatos**. A versão anterior usava 62 µs, o que dava 16 129 Hz. A interrupção só notifica a tarefa, porque `adc1_get_raw` usa travas que não podem ser chamadas dentro de uma ISR. A tarefa tem prioridade 3 no núcleo 1 (o `loop()` tem prioridade 1); a pilha Wi-Fi fica no núcleo 0. O ADC contínuo por DMA (I2S-ADC) **não** foi adotado por causa dos relatos de leituras zeradas com Wi-Fi.
- **Medição de estabilidade**: a tarefa conta ticks perdidos (notificações acumuladas) e o maior intervalo entre amostras por segundo. Os valores aparecem em `/status` (`amostras_perdidas`, `intervalo_max_us`) e no log serial. Assim, taxa real e jitter são medidos, e não supostos.
- **Remoção de DC com média móvel em `float`** (α = 1/1024, corte de ~2,5 Hz). O filtro anterior era inteiro (`media += (x - media) >> 8`) e tem uma "zona morta" de até 255 contagens: o DC estimado parava longe do real e o resíduo inflava o RMS. Em simulação de silêncio, o RMS saía 32 em vez de 8. O ESP32 tem FPU de precisão simples, então o `float` é barato.
- **ADC1_CH6 (GPIO34), 12 bits, atenuação máxima.** No core 2.0.17 a constante `ADC_ATTEN_DB_11` está obsoleta e é idêntica a `ADC_ATTEN_DB_12`; usamos a nova para compilar sem avisos.
- **Buffer circular estático de 32 768 amostras PCM16 (64 KB, ~2,05 s).** É o limite de memória definido para a placa sem PSRAM. Por isso `/audio.wav` aceita `ms` de 200 a 2000.
- **WAV enviado em blocos de 512 bytes** com a API do `WebServer` (`setContentLength` + `sendContent`), sem copiar o trecho inteiro para a RAM. Limitação conhecida: com `ms=2000` sobram só ~48 ms de folga antes de a captura sobrescrever o início do trecho. Isso só corrompe o começo do WAV se o Wi-Fi travar o envio por mais de 48 ms logo no início. A IA usa `ms=1000` (folga de ~1 s).
- **Taxa no cabeçalho WAV = taxa medida** (`fs_real_hz`), como pede o contrato; antes da primeira medição usa 16 000.
- **Atuadores alterados só pelo `loop()`**. O modo `auto` passou da tarefa de áudio para o `loop()`, que avalia cada janela nova de 250 ms. Antes, a tarefa de áudio e os handlers HTTP mexiam no mesmo estado ao mesmo tempo (condição de corrida).
- **Modo auto com histerese**: alerta após 3 janelas acima do limiar (~0,75 s); volta a normal após 8 janelas abaixo (~2 s). Sem isso, o alerta e o buzzer piscariam a cada palavra.
- **`teste`**: sequência de 2 s (verde, vermelho, verde, vermelho, beep de 0,5 s, pausa) e depois **volta ao estado anterior**, para não atrapalhar uma demonstração em andamento.
- **Campos extras** (além do contrato, sem remover nenhum): `/status` ganhou `limiar`, `heap_minimo`, `amostras_perdidas`, `intervalo_max_us` e `clientes_wifi`; `/sensor` ganhou `adc_min`/`adc_max`, que mostram diretamente se o ADC está lendo zero com o Wi-Fi ligado (o teste crítico). A resposta de `/atuador` é `{"ok":true,"atuador":{...}}`, o mesmo objeto de `/status`.
- **`nivel`** é uma escala relativa: RMS 600 contagens = 100. Não é dB SPL. Pode ser recalibrado depois de medir silêncio e motor na placa.
- **Teste automatizado da Fase 1 em Python puro** (`tools/teste_fase1.py`, só biblioteca padrão), em vez de dezenas de `curl.exe` manuais: o resultado é objetivo ([OK]/[FALHA]) e repetível na segunda-feira.

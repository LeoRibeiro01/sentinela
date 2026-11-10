# Explicação do código — guia para a defesa

Cada integrante deve conseguir explicar qualquer arquivo. Para cada um: **propósito**, **fluxo**, **funções principais** e **5 perguntas prováveis** com resposta. Leia junto com o código aberto ao lado.

Visão geral em uma frase: *o ESP32 amostra o microfone a 16 kHz, é o servidor HTTP da porta 80 (inclusive da própria página), conecta-se ao Wi-Fi com reconexão registrada num log na flash e mostra estado e falha numa tela OLED; o navegador consulta e comanda a placa; o serviço de IA puxa o áudio, decide se é carro e qual a falha, e manda o resultado para a tela.*

---

## Parte 1 — Firmware (ESP32)

### `src/esp32/esp32_server/esp32_server.ino` — servidor HTTP e rotas

**Propósito.** O papel de **servidor** exigido pelo regulamento: abre a porta TCP 80, fica passivo esperando conexões e responde a cada pedido. Só faz HTTP: Wi-Fi em `rede.cpp`, log em `registro_log.cpp`, tela em `tela_oled.cpp`, áudio em `captura_audio.cpp`, LEDs/buzzer em `atuadores.cpp`.

**Fluxo.** `setup()`:
1. Inicia a Serial e o **log** (`iniciarLog()`), primeiro de tudo, para que o resto já possa registrar.
2. Registra o boot com o **motivo do reinício** (`esp_reset_reason()`): watchdog, panic ou brownout viram ERRO.
3. Inicia os atuadores (tudo desligado) e a **rede** (AP + estação).
4. Registra as rotas (`servidor.on(...)`) e chama `servidor.begin()` → a porta 80 passa a escutar.
5. Inicia a captura de áudio (núcleo 1), a tarefa da tela e a **tarefa principal** (núcleo 0).

`tarefaPrincipal()` (laço infinito no núcleo 0): `handleClient()` atende um pedido; avalia o modo auto quando há janela nova; anima o teste; `processarRede()` (reconexão); `processarLog()` (grava a fila na flash); `verificarSaude()`; `vTaskDelay(1)`. O `loop()` do Arduino só dorme.

**Funções principais.**
- `adicionarCabecalhos()` / `responderJson()`: CORS `*` e `no-store` em toda resposta JSON.
- `responderErro()`: responde 400/404 e registra **AVISO** no log com a rota e o IP do cliente.
- `lerInteiro()`: só dígitos (no máximo 5) dentro da faixa; rejeita `12abc` e números gigantes.
- `rotaPagina()`: envia o dashboard da flash (`PAGINA_GZ`) com `Content-Encoding: gzip`.
- `rotaStatus()`: monta com `snprintf` (buffer fixo, sem `String` em laço) o JSON com hora, boot, **rede (IP/MAC)**, atuadores e saúde.
- `rotaAtuador()`: valida `estado`, `buzzer` e `falha`; aplica; manda o texto para a tela; registra a mudança no log com o IP de quem pediu.
- `rotaLog()`, `rotaRelogio()`, `rotaWifi()`: log persistente, acerto da hora e configuração da rede (a resposta sai **antes** de reconfigurar o rádio).
- `rotaAudio()`: cabeçalho WAV de 44 bytes, `Content-Length` exato e envio em blocos de 512 bytes.

**Perguntas prováveis.**
1. *Onde está o servidor exigido pelo regulamento?* `ServidorRapido servidor(80)` e `servidor.begin()`: a placa abre a porta 80 e **aceita** conexões. Ela nunca inicia conexão com os clientes. (O único papel de cliente é o NTP, opcional, para a hora.)
2. *O que acontece com `/atuador?estado=xyz`?* `responderErro(400, ...)`: nada muda, o cliente recebe `{"erro":...}` e o log ganha um AVISO com o IP. Rota inexistente → 404 também em JSON e no log.
3. *Por que o HTTP roda numa tarefa no núcleo 0 e não no `loop()`?* Medimos na placa: no núcleo 1, junto com a captura a 16 kHz (prioridade maior), o laço dava só ~22 voltas/s e os pedidos expiravam. No núcleo 0 ele divide a CPU só com o Wi-Fi e roda a ~1000 voltas/s (~140 ms por pedido).
4. *Como a página web sai da placa?* `tools/gerar_pagina_esp32.py` junta HTML+CSS+JS e comprime com gzip num array (`pagina_web.h`, ~17 KB). `rotaPagina()` envia esses bytes com `Content-Encoding: gzip` e o navegador descomprime. `no-store` impede cópia em cache: sem a placa, não há página.
5. *Como o WAV é enviado sem estourar a memória?* O áudio já está no buffer circular. A rota envia o cabeçalho e depois blocos de 256 amostras copiados para um vetor local de 512 bytes. O ESP32 é little-endian como o WAV, então os bytes vão direto.

### `src/esp32/esp32_server/rede.h/.cpp` — Wi-Fi AP+STA e reconexão

**Propósito.** Requisito 3.2.1: a placa **se conecta a uma rede Wi-Fi** e, se perder a conexão, **reconecta registrando data e hora** no log. Mantém também a rede própria `SENTINELA` como reserva.

**Fluxo.** `iniciarRede()`: lê SSID e senha da NVS (`Preferences`); modo `WIFI_AP_STA` se houver rede salva (senão só `WIFI_AP`); sobe o AP (192.168.4.1); desliga a reconexão automática interna; chama `conectarEstacao()`; configura o NTP (`configTzTime`, fuso UTC−3) e o mDNS (`sentinela.local`). `aoEventoWifi()` recebe os eventos do sistema: `GOT_IP` → "conectado"/"RECONECTADO após N s"; `DISCONNECTED` (só na transição) → AVISO "PERDIDA"; entrada/saída de clientes no AP com o MAC. `processarRede()` (tarefa principal) tenta de novo a cada 15 s.

**Perguntas prováveis.**
1. *Por que AP+STA e não só estação?* Estação cumpre o requisito (rede real, DHCP, reconexão). O AP é o plano B: se o roteador/hotspot falhar, ainda dá para acessar a placa em 192.168.4.1.
2. *Por que desligar o `setAutoReconnect` e fazer a reconexão "na mão"?* Para controlar o intervalo, contar as tentativas e registrar cada etapa no log. A automática não avisa nada.
3. *Por que o evento de Wi-Fi não grava direto na flash?* O callback roda na tarefa de eventos do sistema. Ele só chama `registrar()`, que põe a mensagem numa fila; quem grava é a tarefa principal. Assim nunca há duas escritas ao mesmo tempo.
4. *Onde ficam a senha e o nome da rede?* Na NVS (memória não volátil, chave `rede`), gravados pela rota `/wifi`. A senha nunca vai para o log nem para o `/status`.
5. *Por que o AP às vezes "pisca" quando a estação conecta?* O ESP32 tem um rádio só: o AP precisa usar o mesmo canal do roteador e muda de canal quando a estação conecta. Os clientes do AP reconectam em segundos.

### `src/esp32/esp32_server/registro_log.h/.cpp` — log persistente na flash

**Propósito.** Requisito 3.2.3: log persistente em memória flash com **ERRO, AVISO e INFO** e **data e hora** de cada evento, acessível pela rede (`/log`).

**Fluxo.** `iniciarLog()`: fuso horário, fila do FreeRTOS (24 eventos), contador de boots na NVS e montagem do LittleFS (formata na primeira vez). `registrar(nivel, formato, ...)`: monta o texto com `vsnprintf` e **só enfileira** (nunca bloqueia). `processarLog()` (tarefa principal): ao detectar o relógio ajustado, registra "Relógio ajustado"; retira os eventos da fila e chama `gravar()`, que abre `/log.txt` em modo *append*, escreve a linha e rotaciona para `/log_antigo.txt` ao passar de 48 KB. `enviarLog()`: devolve as últimas N linhas usando um anel de posições de início de linha (memória fixa).

**Perguntas prováveis.**
1. *De onde vem a data e a hora, se o ESP32 não tem relógio com bateria?* Do NTP (quando a rede tem internet) ou do navegador: o dashboard chama `/relogio?epoch=...` quando `/status` diz `hora_ok=false`.
2. *E os eventos do boot, que acontecem antes de saber a hora?* Esperam até 90 s na RAM. Quando o relógio é ajustado, a hora deles é calculada voltando no tempo (`agora − (millis() − uptime do evento)`). Se ninguém ajustar, saem como `sem hora (+Ns)`.
3. *O log sobrevive a desligar a placa?* Sim: está num arquivo do LittleFS na flash. Teste: apertar EN e ver as linhas antigas e o "Boot #N" novo.
4. *Escrever na flash não atrapalha o áudio?* Durante a escrita o cache da flash é pausado; o timer pode perder algumas amostras (contadas em `amostras_perdidas`). Por isso o log grava só eventos (não leituras periódicas).
5. *Por que fila e não escrever direto?* Várias tarefas registram (HTTP, Wi-Fi, tela). Uma única tarefa escrevendo elimina condição de corrida no arquivo sem precisar de mutex.

### `src/esp32/esp32_server/tela_oled.h/.cpp` — tela OLED (atuador)

**Propósito.** Requisito 3.4: atuador que **não é LED nem buzzer**. A tela SSD1306 (I2C, SDA 21, SCL 22) muda de estado por comando de rede e mostra o estado atual e a falha.

**Fluxo.** `iniciarTela()` configura o I2C a 400 kHz e cria `tarefaTela` (núcleo 0, prioridade 1). A tarefa, a cada 250 ms: se não há tela, procura nos endereços 0x3C/0x3D a cada 3 s (registra INFO ao achar, AVISO se não achar); se há, confere se ainda responde (ERRO se sumir) e chama `desenhar()`: hora, estado em letras grandes (faixa invertida piscando no alerta), texto da falha em até 2 linhas, IP e barra de nível. `definirMensagemTela()` recebe o texto (protegido por `portMUX`) e converte acentos para ASCII (`paraAscii`).

**Perguntas prováveis.**
1. *Por que a tela conta como atuador?* É um dispositivo de saída que muda de estado físico (o que exibe) por comando recebido pela rede (`/atuador?estado=alerta&falha=...`).
2. *E se a tela não estiver ligada?* A tarefa só procura de novo a cada 3 s; nada mais depende dela. O dashboard mostra "Tela OLED: não detectada" e um espelho do que ela exibiria.
3. *Por que uma tarefa separada?* Enviar um quadro (1 KB) pelo I2C leva ~25 ms; na tarefa do HTTP isso atrasaria as respostas.
4. *Como as duas tarefas compartilham o texto da falha sem conflito?* Cópia dentro de uma seção crítica (`portENTER_CRITICAL`): a leitura nunca pega o texto pela metade.
5. *Por que tirar os acentos?* A fonte padrão da biblioteca Adafruit GFX não tem letras acentuadas; "Ignição" viraria símbolos estranhos.

### `src/esp32/esp32_server/servidor_rapido.h` e `pagina_web.h`

- **`servidor_rapido.h`**: subclasse do `WebServer` que reimplementa `handleClient()`. Uma conexão aberta sem pedido (pré-conexão do Chrome) é descartada em 300 ms, ou na hora se outro cliente estiver esperando. A biblioteca original esperava 5 s e travava a fila. *Pergunta: "por que mexer na biblioteca?"* Não mexemos: herdamos a classe e sobrescrevemos um método virtual; o resto é o original.
- **`pagina_web.h`**: **gerado** por `tools/gerar_pagina_esp32.py`, não se edita à mão. Contém o dashboard comprimido (`PAGINA_GZ`). Sempre que `src/client` mudar, rode o gerador antes de compilar.

### `src/esp32/esp32_server/captura_audio.h/.cpp` — amostragem a 16 kHz

**Propósito.** Ler o MAX9814 (GPIO34, ADC1_CH6) exatamente 16 000 vezes por segundo, tirar o nível DC, guardar ~2 s num buffer circular e publicar métricas a cada 250 ms.

**Fluxo.**
1. O **timer 0** usa divisor 40 (80 MHz / 40 = 2 MHz) e alarme a cada 125 ticks, ou seja, 62,5 µs = **16 kHz**.
2. A interrupção `aoTickDoTimer()` só chama `vTaskNotifyGiveFromISR`, que acorda a tarefa.
3. A `tarefaCaptura` (núcleo 1, prioridade 3) acorda e lê `adc1_get_raw`.
4. Atualiza a média do DC e subtrai. Converte para PCM16 (×16) e grava no buffer.
5. Acumula soma dos quadrados, pico, mínimo e máximo. A cada 4000 amostras (250 ms), fecha a janela: RMS, nível 0–100 e clipping. Publica tudo numa estrutura protegida por `portENTER_CRITICAL`.

**Funções principais.** `iniciarCaptura()` (configura o ADC, cria a tarefa e o timer), `lerSensor()` (cópia atômica da última janela), `inicioTrechoRecente()` e `copiarAmostras()` (usadas pelo WAV), `taxaRealHz()`, `amostrasPerdidas()` e `intervaloMaximoUs()` (diagnóstico de estabilidade).

**Perguntas prováveis.**
1. *Por que não ler o ADC dentro da interrupção?* `adc1_get_raw` usa travas (mutex) que não podem ser usadas numa ISR. A ISR só "cutuca" a tarefa, que faz o trabalho fora do contexto de interrupção.
2. *Por que GPIO34 e não outro pino?* Ele pertence ao **ADC1**. O ADC2 é usado pelo Wi-Fi e não funciona com o rádio ligado. O GPIO34 é só entrada, o que é perfeito para um sinal analógico.
3. *Como o DC é removido e por que em `float`?* Média móvel exponencial: `media += (x - media) / 1024`, que é um passa-altas de ~2,5 Hz. A versão inteira anterior (`>> 8`) tinha zona morta de até 255 contagens e inflava o RMS em silêncio (simulamos: RMS 32 contra 8). O ESP32 tem FPU, então `float` é barato.
4. *E se a tarefa atrasar?* `ulTaskNotifyTake` devolve quantas notificações acumularam. Se for mais de 1, contamos as amostras perdidas (`amostras_perdidas` em `/status`). Também medimos o maior intervalo entre amostras (`intervalo_max_us`). Ou seja, medimos a estabilidade em vez de supor.
5. *Por que o buffer tem 32 768 amostras?* São 64 KB (2 bytes por amostra), o limite que definimos para uma placa sem PSRAM (~520 KB de SRAM no total). A 16 kHz isso dá ~2,05 s, e por isso `/audio.wav` aceita até 2000 ms.

### `src/esp32/esp32_server/atuadores.h/.cpp` — LEDs, buzzer e modo auto

**Propósito.** Guardar o estado (`off`, `normal`, `alerta`, `teste`) e refletir nos pinos 16 (verde), 17 (vermelho), 18 (buzzer, via transistor) e 2 (LED azul que espelha o alerta). Também implementa o modo **auto**, o fallback sem IA.

**Fluxo.** `definirEstado()` muda o estado e chama `aplicarSaidas()`, que calcula cada saída e faz `digitalWrite`. No `teste`, `atualizarAtuadores()` (chamada pelo `loop`) avança uma etapa a cada 250 ms: verde, vermelho, verde, vermelho, beep, beep, pausa. Depois de 2 s, volta ao estado anterior. `processarJanelaAuto(nivel)` é chamada uma vez por janela nova.

**Perguntas prováveis.**
1. *Como o modo auto evita o pisca-pisca?* Com **histerese**: liga o alerta só depois de 3 janelas seguidas acima do limiar (~0,75 s) e só desliga depois de 8 janelas abaixo (~2 s).
2. *Por que o modo auto roda no `loop()` e não na tarefa de áudio?* Para que **só uma tarefa** mexa nos atuadores. Na versão anterior, a tarefa de áudio e os handlers HTTP mudavam o mesmo estado ao mesmo tempo (condição de corrida).
3. *Por que o buzzer precisa de transistor?* O buzzer de 5 V consome mais corrente do que um GPIO de 3,3 V fornece com segurança. O GPIO só aciona a base do NPN (por 1 kΩ), e a corrente do buzzer vem do VIN (5 V) e passa pelo transistor.
4. *Para que serve o LED azul da placa (GPIO2)?* Ele espelha o alerta. Assim dá para testar toda a lógica sem nenhum componente externo. O GPIO2 é pino de *strapping*, mas só é usado como saída depois do boot, o que é seguro.
5. *O que `buzzer=0/1` faz em `/atuador`?* Força o buzzer junto com o estado, por exemplo `alerta&buzzer=0` para um alerta silencioso. Sem o parâmetro, o buzzer segue o estado: liga no alerta.

### `src/esp32/teste_audio/teste_audio.ino` — teste isolado do microfone

**Propósito.** Imprimir a leitura bruta do GPIO34 na Serial, sem Wi-Fi, para isolar problemas de fiação. **Pergunta provável:** *por que manter esse sketch?* Se o firmware principal mostrar `adc_max = 0`, ele separa "problema de fio/microfone" de "problema de software/Wi-Fi".

---

## Parte 2 — Cliente (dashboard)

### `src/client/index.html`, `style.css`, `app.js`

**Propósito.** Interface de operação e de demonstração: estado conectado/desconectado, nível ao vivo com histórico de 60 s, comandos dos atuadores, forma de onda e espectro, painel de IA com o botão DIAGNOSTICAR. HTML e CSS só estruturam e estilizam; toda a lógica está em `app.js`.

**Fluxo (`app.js`).**
- `iniciar()` liga os botões e dispara dois laços independentes:
  - `lacoEsp32()`: a cada 1 s, pede `/status` e **depois** `/sensor`, sempre em sequência. Atualiza a tela. Duas falhas seguidas → DESCONECTADO.
  - `lacoIa()`: a cada 1 s, pede `/api/resultado`. Se falhar → "IA: OFFLINE", e só o painel de IA é desabilitado.
- `buscar()`: `fetch` com **AbortController**, que cancela depois de 2 s.
- `capturarAudio()`: baixa `/audio.wav`; `lerWav()` acha o bloco `data`; `desenharOnda()` e `desenharEspectro()` desenham. O espectro usa uma FFT radix-2 (`fft()`) com janela de Hann.
- `diagnosticar()`: chama `/api/diagnostico?segundos=5`, mostra a barra de progresso e depois `mostrarDiagnostico()` (ranking e cartão).

**Novidades da versão 2.0.**
- A página é **servida pela placa** (`SERVIDA_PELA_PLACA`): o endereço do ESP32 é o da própria página e o campo de IP some.
- Sem resposta da placa, `mostrarConexao(false)` põe a classe `sem-esp32` no `<body>` e **toda a interface some** atrás do aviso; quando a placa volta, a página é recarregada pela placa.
- Cartão Sistema: data/hora, rede, **IP e MAC** da estação e do AP, boot nº, e o formulário de Wi-Fi (`/wifi`).
- Atuadores: espelho da tela OLED e campo "Texto da falha" enviado com Normal/Alerta.
- Log do sistema: `atualizarLog()` busca `/log?linhas=80` a cada 5 voltas; `mostrarLog()` pinta por nível e permite filtrar.
- Se `/status` disser `hora_ok=false`, o dashboard manda a hora do aparelho para `/relogio` uma vez.

**Perguntas prováveis.**
1. *Como o dashboard detecta que o ESP32 caiu?* Cada pedido tem timeout de 2 s (`AbortController`). Com duas falhas seguidas, o selo vira DESCONECTADO e os botões são desabilitados. O laço nunca para; quando o ESP32 volta, o próximo pedido dá certo e o selo volta a CONECTADO sozinho.
2. *Por que os pedidos são sequenciais e não em paralelo?* O `WebServer` do ESP32 atende um cliente por vez. Pedidos paralelos só ficariam na fila e aumentariam o risco de timeout.
3. *Como funciona sem internet?* Não há CDN, fonte externa nem build. Os três arquivos são embutidos na flash da placa e servidos por ela.
4. *Como o dashboard funciona se a IA cair?* São dois laços separados. A falha do `lacoIa` só muda o selo da IA e desabilita o botão DIAGNOSTICAR. O núcleo obrigatório (sensor, atuadores, conexão) não depende dela.
5. *Por que usar `textContent` e não `innerHTML`?* Os dados vêm da rede. `textContent` nunca interpreta HTML, então não há risco de injeção de script.

---

## Parte 3 — Inteligência artificial (`src/ai/`)

### `audio_util.py` — áudio compartilhado

**Propósito.** Carregar (WAV/MP3/M4A), converter para 16 kHz mono, **normalizar** (RMS 0,1), aumentar dados e detectar arquivos corrompidos. Treino e serviço usam exatamente as mesmas funções.
- `para_16k_mono()`: média dos canais e `resample_poly`.
- `normalizar()`: leva o RMS a 0,1 e limita picos.
- `aumentar()`: passa-faixa 150–6000 Hz + ruído (simula alto-falante e microfone).
- `parece_corrompido()`: autocorrelação de passo 1 abaixo de 0,1 com RMS alto indica ruído branco.
- `simular_captura()`: degradação **só para avaliação**.

### `yamnet_util.py` — o modelo pré-treinado

**Propósito.** Carregar o YAMNet do disco. `analisar()` devolve as 521 probabilidades e o embedding de 1024 números por quadro de 0,96 s (passo 0,48 s), **só quadros cheios**. `resumo()` calcula o som mais provável, a soma das classes de veículo e o máximo das classes "não carro". `easter_egg()` acha o animal mais provável (modo demo).

### `analise.py` — decisão sobre um trecho

**Propósito.** Responder, em ordem: *tem som?* (RMS ≥ limiar), *é carro?* (porteiro ≥ 0,5 e sem veto), *qual o estado?* (probabilidades do diagnóstico). `veto_yamnet()` só veta quando o YAMNet ouve claramente fala, música, animal etc. **e** quase nada de veículo.

### `prepare_dataset.py` — dados brutos → treino

**Fluxo.**
1. Lê `fontes.json`.
2. Lista os arquivos de cada fonte com classe e **grupo** (gravação de origem).
3. Gera ruído sintético.
4. Sorteia treino/validação/teste **por grupo** (70/15/15, semente fixa).
5. Corta em trechos de até 10 s, descarta silêncio e trechos corrompidos, normaliza e salva em `data/train/<classe>/`.
6. Escreve o `manifest.csv` e um relatório.

### `train.py` — treino e métricas

**Fluxo.**
1. Calcula os embeddings de todos os trechos (com cache em disco). No treino, também de uma cópia aumentada.
2. **Porteiro**: regressão logística `carro × nao_carro`.
3. **Diagnóstico**: regressão logística em 5 classes (normal, batida de pino, ignição, correia, tucho).
4. Para cada um, escolhe **C** pela F1-macro na **validação**, retreina em treino+validação e avalia no **teste**.
5. Escolhe o **limiar de confiança** na validação, simulando o botão (grupos de 5 s).
6. Roda o teste de robustez com áudio degradado e o `real_test` (knock real).
7. Salva `models/classificador.joblib`, `classes.json` e `docs/metricas_ia.md`.

### `server.py` — serviço local

**Fluxo.** Thread `laco_ao_vivo()`: a cada ~1 s baixa 1 s de áudio, guarda os últimos 5 s e analisa tudo junto (silêncio zera a memória). Suaviza com maioria de 3 em 5 e, se "IA comanda os LEDs" estiver ligado, chama `/atuador` quando o estado muda. As rotas `/api/*` atendem o dashboard. `diagnosticar()` captura 5 janelas de 1 s, descarta as silenciosas, **concatena** e analisa. Depois monta o cartão a partir de `diagnosticos.json` e comanda o atuador. `calibrar_silencio()` ajusta o limiar de "sinal fraco".

### `record.py` — coleta de dados próprios

Baixa 1 s por segundo do ESP32, junta tudo e salva em `data/own/<classe>/`. Na próxima preparação, cada arquivo vira um grupo.

### `fontes.json` / `diagnosticos.json`

`fontes.json` diz qual pasta vira qual classe. Isso permite mudar o dataset sem mexer no código. `diagnosticos.json` é a base de conhecimento exibida no cartão: nome, causas, o que verificar, urgência e o aviso.

**Perguntas prováveis (IA).**
1. *O que é o YAMNet e por que usá-lo?* Uma rede neural do Google treinada em ~2 milhões de áudios do YouTube (AudioSet, 521 classes). Usamos a penúltima camada (**embedding** de 1024 números) como "resumo do som" e treinamos em cima um classificador simples (regressão logística). Isso é *transfer learning*: com poucos dados, aproveitamos o que a rede já aprendeu sobre sons.
2. *Como vocês garantem que a métrica não está inflada?* (a) A divisão é **por gravação**: trechos da mesma gravação nunca ficam em treino e teste. (b) O hiperparâmetro e o limiar são escolhidos na **validação**; o teste só é olhado no fim. (c) Reportamos também um teste com áudio degradado e um teste com knock real (AudioSet) que nunca entrou no treino. (d) Mostramos o acerto **por fonte**.
3. *Como o sistema sabe que o som é de carro?* Duas camadas. Primeiro, um **porteiro** treinado com exemplos de carro e de não-carro (animais, sirenes, tiros, furadeira, ruído sintético). Depois, um **veto** usando as próprias classes do YAMNet para fala, música e animais, que não temos como negativos treinados. Só se passar pelos dois o diagnóstico acontece.
4. *O que acontece quando o modelo não tem certeza?* Se a maior probabilidade ficar abaixo de 60%, o resultado é "**inconclusivo**" e o sistema pede para repetir. Ele não finge certeza. Esse limiar foi escolhido na validação: no teste, ele responde ~76% das vezes com ~89% de acerto.
5. *Qual foi o maior problema encontrado nos dados?* Os WAVs segmentados de um dos datasets eram **ruído branco** (corrompidos). A primeira versão do modelo parecia ótima numa classe (100%), mas tinha aprendido "ruído". Descobrimos ao ver o YAMNet classificar um gato como "chuva", confirmamos pela autocorrelação, trocamos pelas gravações originais e criamos um filtro automático.

Outras que podem cair: *por que regressão logística e não uma rede maior?* Poucos dados, treino em segundos, fácil de explicar, e o embedding já faz o trabalho pesado. *Por que "falha_outros" não é diagnosticada?* Só ~4 min de 29 falhas diferentes: no teste, acerto de 0%. Preferimos não exibir um diagnóstico em que não confiamos. *Por que 16 kHz?* É a taxa que o YAMNet exige, e cobre a faixa de interesse (até 8 kHz).

---

## Parte 4 — Ferramentas (`tools/`)

- **`mock_esp32.py`**: simulador com a mesma API do firmware (mesmas validações, mesma lógica do atuador e do modo auto). Gera tom + ruído ou toca WAVs reais. Permite desenvolver e demonstrar sem a placa. *Pergunta: "como vocês testaram sem hardware?"* Com ele: o mesmo roteiro de testes da placa passa 100% contra o simulador, e a IA foi testada de ponta a ponta com áudio de teste tocado por ele.
- **`teste_fase1.py`**: testes de aceitação do firmware (`rotas`, `critico`, `resistencia`), com resultado [OK]/[FALHA].
- **`montar_sons_demo.py`**: escolhe trechos de TESTE que o pipeline acerta em qualquer janela de 5 s e salva 15 s de cada em `data/demo_sons/`, para tocar na apresentação. *Pergunta: "esses sons não foram escolhidos a dedo?"* Sim, e dizemos isso: são exemplos para a demo. As métricas honestas, com trechos sorteados, estão em `docs/metricas_ia.md`.
- **`iniciar_ia.bat`**: duplo clique sobe o serviço de IA e abre o dashboard na placa (`http://192.168.4.1/`).
- **`baixar_yamnet.py`**: baixa o YAMNet uma vez e prova que ele carrega **offline**, rodando a verificação num processo em que qualquer conexão de rede dá erro.
- **`gerar_pagina_esp32.py`**: junta `index.html` + `style.css` + `app.js` num HTML único, comprime com gzip (`mtime=0`, saída reproduzível) e escreve `pagina_web.h`. O simulador usa a mesma função (`montar_pagina`) para servir a mesma página.
- **`coletar_evidencias.ps1`**: os testes da seção 6 do regulamento com evidência em arquivo: ping, ARP, porta TCP 80 × 81, cliente **socket TCP** escrito à mão (pedido HTTP em texto puro, equivalente ao telnet), `curl -v` nas rotas, sensor em tempo real, WAV, atuadores, erros 400/404 e log. *Pergunta: "como vocês provam que é TCP/IP?"* O arquivo do socket mostra a porta local, o pedido em texto e a resposta HTTP; o `curl -v` mostra a conexão TCP; o ARP mostra o MAC da placa.
- **`gerar_relatorio_docx.py`**: converte `docs/RELATORIO_TDE.md` em `.docx` com margens, fonte, espaçamento e títulos no padrão ABNT.
- **`docs/generate_diagrams.ps1`**: desenha os diagramas em SVG e PNG a partir de uma única descrição.

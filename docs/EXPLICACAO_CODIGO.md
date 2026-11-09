# Explicação do código — guia para a defesa

Cada integrante deve conseguir explicar qualquer arquivo. Para cada um: **propósito**, **fluxo**, **funções principais** e **5 perguntas prováveis** com resposta. Leia junto com o código aberto ao lado.

Visão geral em uma frase: *o ESP32 amostra o microfone a 16 kHz e serve os dados por HTTP; o dashboard consulta e comanda o ESP32; o serviço de IA puxa o áudio, decide se é carro e qual o estado, e comanda o alerta.*

---

## Parte 1 — Firmware (ESP32)

### `src/esp32/esp32_server/esp32_server.ino` — rede e rotas HTTP

**Propósito.** Criar o Wi-Fi `SENTINELA` (Access Point) e o servidor HTTP na porta 80, com as rotas do contrato. Só faz rede: a captura está em `captura_audio.cpp` e os atuadores em `atuadores.cpp`.

**Fluxo.** `setup()`:
1. Inicia a Serial.
2. Inicia os atuadores (tudo desligado).
3. Sobe o AP (`WiFi.softAP`, IP 192.168.4.1, `setSleep(false)`).
4. Registra as rotas (`servidor.on`) e chama `servidor.begin()`.
5. Inicia a captura.

`loop()`:
1. `servidor.handleClient()` atende um pedido.
2. Se houver janela de áudio nova, avalia o modo auto.
3. Anima a sequência de teste.
4. A cada 10 s, imprime o log de saúde.

**Funções principais.**
- `adicionarCabecalhos()`: CORS `*` (o dashboard roda em outra origem) e `no-store` (nada de leitura velha em cache).
- `responderJson()`: atalho que adiciona os cabeçalhos e envia o JSON.
- `lerInteiro()`: valida parâmetros. Aceita só dígitos (no máximo 5) dentro da faixa, e assim rejeita `12abc` e números gigantes.
- `rotaStatus()`, `rotaSensor()`: montam o JSON com `snprintf` num buffer fixo, sem `String` em laço.
- `rotaAtuador()`: valida `estado` e `buzzer`; inválido → 400.
- `rotaConfig()`: valida tudo antes de aplicar; inválido não altera nada.
- `rotaAudio()`: monta um cabeçalho WAV de 44 bytes, define `Content-Length` exato e envia o áudio em blocos de 256 amostras (512 bytes), sem copiar 64 KB para a RAM.
- `registrarSaude()`: uptime, heap, taxa real, amostras perdidas. Serve para o teste de 30 min.

**Perguntas prováveis.**
1. *Por que Access Point e não a rede da faculdade?* Redes institucionais costumam isolar os dispositivos (um não enxerga o outro) e exigem login. Com AP, o notebook conecta direto no ESP32, sem internet e sem depender de ninguém.
2. *Onde está o "servidor" exigido pelo regulamento?* `WebServer servidor(80)` e `servidor.begin()`. O ESP32 **recebe** conexões dos clientes (dashboard, IA, curl). Ele não é cliente de nenhuma nuvem.
3. *O que acontece se chegar `/atuador?estado=xyz`?* `rotaAtuador` não reconhece o estado e responde **400** com `{"erro":...}`, sem mudar nada. Rota inexistente cai em `rotaNaoEncontrada` → **404** em JSON.
4. *Como o WAV é enviado sem estourar a memória?* O áudio já está no buffer circular. A rota calcula onde começa o trecho, envia o cabeçalho e depois copia blocos de 256 amostras para um vetor local de 512 bytes, enviando um por vez. O ESP32 é little-endian como o WAV, então os bytes vão direto.
5. *Por que `delay(1)` no `loop()` não atrapalha a amostragem?* A amostragem não depende do `loop()`: um timer de hardware acorda a tarefa de captura, que tem prioridade maior. O `delay(1)` só libera CPU para tarefas de prioridade menor.

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

**Perguntas prováveis.**
1. *Como o dashboard detecta que o ESP32 caiu?* Cada pedido tem timeout de 2 s (`AbortController`). Com duas falhas seguidas, o selo vira DESCONECTADO e os botões são desabilitados. O laço nunca para; quando o ESP32 volta, o próximo pedido dá certo e o selo volta a CONECTADO sozinho.
2. *Por que os pedidos são sequenciais e não em paralelo?* O `WebServer` do ESP32 atende um cliente por vez. Pedidos paralelos só ficariam na fila e aumentariam o risco de timeout.
3. *Como funciona sem internet?* Não há CDN, fonte externa nem build. São três arquivos estáticos, que abrem por duplo clique.
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
3. **Diagnóstico**: regressão logística em 3 classes.
4. Para cada um, escolhe **C** pela F1-macro na **validação**, retreina em treino+validação e avalia no **teste**.
5. Escolhe o **limiar de confiança** na validação, simulando o botão (grupos de 5 s).
6. Roda o teste de robustez com áudio degradado e o `real_test` (knock real).
7. Salva `models/classificador.joblib`, `classes.json` e `docs/metricas_ia.md`.

### `server.py` — serviço local

**Fluxo.** Thread `laco_ao_vivo()`: a cada ~1 s baixa 1,5 s de áudio e analisa. Suaviza com maioria de 3 em 5 e, se "IA comanda os LEDs" estiver ligado, chama `/atuador` quando o estado muda. As rotas `/api/*` atendem o dashboard. `diagnosticar()` captura 5 janelas de 1 s, descarta as silenciosas, **concatena** e analisa. Depois monta o cartão a partir de `diagnosticos.json` e comanda o atuador. `calibrar_silencio()` ajusta o limiar de "sinal fraco".

### `record.py` — coleta de dados próprios

Baixa 1 s por segundo do ESP32, junta tudo e salva em `data/own/<classe>/`. Na próxima preparação, cada arquivo vira um grupo.

### `fontes.json` / `diagnosticos.json`

`fontes.json` diz qual pasta vira qual classe. Isso permite mudar o dataset sem mexer no código. `diagnosticos.json` é a base de conhecimento exibida no cartão: nome, causas, o que verificar, urgência e o aviso.

**Perguntas prováveis (IA).**
1. *O que é o YAMNet e por que usá-lo?* Uma rede neural do Google treinada em ~2 milhões de áudios do YouTube (AudioSet, 521 classes). Usamos a penúltima camada (**embedding** de 1024 números) como "resumo do som" e treinamos em cima um classificador simples (regressão logística). Isso é *transfer learning*: com poucos dados, aproveitamos o que a rede já aprendeu sobre sons.
2. *Como vocês garantem que a métrica não está inflada?* (a) A divisão é **por gravação**: trechos da mesma gravação nunca ficam em treino e teste. (b) O hiperparâmetro e o limiar são escolhidos na **validação**; o teste só é olhado no fim. (c) Reportamos também um teste com áudio degradado e um teste com knock real (AudioSet) que nunca entrou no treino. (d) Mostramos o acerto **por fonte**.
3. *Como o sistema sabe que o som é de carro?* Duas camadas. Primeiro, um **porteiro** treinado com exemplos de carro e de não-carro (animais, sirenes, tiros, furadeira, ruído sintético). Depois, um **veto** usando as próprias classes do YAMNet para fala, música e animais, que não temos como negativos treinados. Só se passar pelos dois o diagnóstico acontece.
4. *O que acontece quando o modelo não tem certeza?* Se a maior probabilidade ficar abaixo de 60%, o resultado é "**inconclusivo**" e o sistema pede para repetir. Ele não finge certeza. Esse limiar foi escolhido na validação: no teste, ele responde ~79% das vezes com ~86% de acerto.
5. *Qual foi o maior problema encontrado nos dados?* Os WAVs segmentados de um dos datasets eram **ruído branco** (corrompidos). A primeira versão do modelo parecia ótima numa classe (100%), mas tinha aprendido "ruído". Descobrimos ao ver o YAMNet classificar um gato como "chuva", confirmamos pela autocorrelação, trocamos pelas gravações originais e criamos um filtro automático.

Outras que podem cair: *por que regressão logística e não uma rede maior?* Poucos dados, treino em segundos, fácil de explicar, e o embedding já faz o trabalho pesado. *Por que "falha_outros" não é diagnosticada?* Só ~4 min de 29 falhas diferentes: no teste, acerto de 0%. Preferimos não exibir um diagnóstico em que não confiamos. *Por que 16 kHz?* É a taxa que o YAMNet exige, e cobre a faixa de interesse (até 8 kHz).

---

## Parte 4 — Ferramentas (`tools/`)

- **`mock_esp32.py`**: simulador com a mesma API do firmware (mesmas validações, mesma lógica do atuador e do modo auto). Gera tom + ruído ou toca WAVs reais. Permite desenvolver e demonstrar sem a placa. *Pergunta: "como vocês testaram sem hardware?"* Com ele: o mesmo roteiro de testes da placa passa 100% contra o simulador, e a IA foi testada de ponta a ponta com áudio de teste tocado por ele.
- **`teste_fase1.py`**: testes de aceitação do firmware (`rotas`, `critico`, `resistencia`), com resultado [OK]/[FALHA].
- **`baixar_yamnet.py`**: baixa o YAMNet uma vez e prova que ele carrega **offline**, rodando a verificação num processo em que qualquer conexão de rede dá erro.
- **`docs/generate_diagrams.ps1`**: desenha os diagramas em SVG e PNG a partir de uma única descrição.

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

## Fase 2 — dashboard e simulador

- **Dashboard em JS puro** (`index.html`/`app.js`/`style.css`), sem framework, CDN ou build. Abre por duplo clique (`file://`) ou servido pela IA em `localhost:5000`. Gráficos em `<canvas>` desenhados à mão, com FFT radix-2 própria para o espectro.
- **Polling sequencial** (`/status` e depois `/sensor`, a cada 1 s), porque o `WebServer` do ESP32 atende um cliente por vez. Timeout de 2 s com `AbortController`. **Duas falhas seguidas** mostram DESCONECTADO (uma só causaria pisca-pisca por perda de pacote). O laço nunca para, então a reconexão é automática.
- O áudio (forma de onda/espectro) só é baixado **sob demanda** ou a cada 5 s, se marcado, para não disputar o ESP32 com o serviço de IA.
- Endereço do ESP32: `?esp32=` na URL > `localStorage` > `192.168.4.1`. Ao mudar, o dashboard avisa o serviço de IA (`/api/config?esp32=`).
- Dados da rede entram na página só por `textContent`, nunca `innerHTML`.
- Visual para projetor: fundo escuro, fontes grandes, estado sempre em **texto e cor**.
- **Simulador `tools/mock_esp32.py`** (só biblioteca padrão), com a mesma API, as mesmas validações e a mesma lógica do atuador e do modo auto do firmware. Pode tocar WAVs reais (`--wav-dir`, `--padrao`) para testar a IA de ponta a ponta sem placa. Passa em 100% do `teste_fase1.py rotas`.

## Fase 3 — IA

- **YAMNet + regressão logística** (scikit-learn) sobre os embeddings de 1024 dimensões. Modelo pequeno (~60 KB), versionado; o YAMNet (~18 MB) é baixado uma vez por `tools/baixar_yamnet.py` e roda offline (verificado com rede bloqueada no processo de teste). O TensorFlow 2.21 instalou no Python 3.11, então o fallback MFCC + RandomForest não foi necessário.
- **Três perguntas em sequência**, pedidas pela equipe ("identificar se o som é realmente de um carro"):
  1. *Tem som?* RMS bruto contra um limiar, calibrável pelo botão "Calibrar silêncio" (o ruído real do MAX9814 com AGC só é conhecido na placa).
  2. *É carro?* Um **porteiro** treinado (`carro` × `nao_carro`) mais um **veto do YAMNet**: fala, música, animais, chuva, sirene etc. ≥ 0,5 **e** som de veículo < 0,2. O veto existe porque não há fala nem música nos dados negativos. A condição "veículo < 0,2" evita vetar motor com alguém falando por cima.
  3. *Qual o estado?* Diagnóstico em **3 classes**: `normal`, `falha_batida_pino`, `falha_ignicao`.
- **`falha_outros` não é diagnosticada.** Os originais das falhas mecânicas do amrrashed somam só ~4 min, em 29 gravações de falhas muito diferentes (rolamento, freio, direção...). Testada como 4ª classe, teve **0% de acerto** no teste. Essas gravações entram só como exemplos de "é carro" no porteiro (`classes_somente_porteiro` em `fontes.json`). Trabalho futuro.
- **Os WAVs segmentados do amrrashed estão corrompidos**: cabeçalho válido, conteúdo de **ruído branco em escala cheia** (autocorrelação ≈ 0, pico 1,0; áudio real fica entre 0,8 e 0,97). Foram descobertos porque o YAMNet "ouvia" chuva/spray em gravações de gato. A primeira versão do modelo, treinada com eles, parecia ótima (100% em `falha_outros`), mas tinha aprendido "ruído branco". Usamos as gravações originais (`.m4a`, decodificadas com o ffmpeg do pacote `imageio-ffmpeg`, só na preparação). O `prepare_dataset.py` agora **descarta automaticamente** trechos com esse padrão, o que protege também os datasets do Kaggle.
- **Ruído sintético como `nao_carro`** (branco, rosa, marrom, zumbido de 60 Hz): sem isso, um chiado poderia virar "carro com falha". No teste de ponta a ponta, um tom puro de 120 Hz passou de "normal 99%" para "não é carro".
- **Divisão por gravação** (grupo) em 70/15/15. Para o kwerimoto, usamos o split do autor, que já separa por vídeo. **C** e **limiar de confiança** são escolhidos na **validação**; o teste só é usado no relatório final.
- **Pesos**: cada classe pesa igual. Dentro da classe, cada fonte pesa pela **raiz quadrada** do seu tamanho. Com peso igual por fonte, 1 trecho isolado de uma fonte passava a valer o mesmo que 76 de outra.
- **Só quadros cheios do YAMNet**: ele completa o fim do áudio com zeros e cria um quadro parcial. Com 1 s de áudio, metade dos quadros era "meio silêncio", e isso derrubava a confiança ao vivo (saudável saía 42–47% → inconclusivo). Depois da correção, 17 de 18 diagnósticos de ponta a ponta acertaram; o 18º deu "inconclusivo".
- **Diagnóstico de 5 s**: as janelas de 1 s com som são **concatenadas** e analisadas juntas (~9 quadros), o mesmo formato da métrica "simulação do botão DIAGNOSTICAR". **Ao vivo**: ver Rodada 2 (memória de 5 s).
- **Suavização ao vivo**: maioria de 3 dos últimos 5 votos *confiantes*. Silêncio, "não é carro" e votos incertos não mudam o estado, o que dá histerese natural. O `/atuador` só é chamado quando o estado muda. A opção "IA comanda os LEDs" vem **desligada** por padrão, para não brigar com os botões manuais. No simulador, foram 60 s de silêncio com a opção ligada: 0 alertas.
- **Aumento de dados**: uma cópia de cada trecho de treino com passa-faixa 150–6000 Hz e ruído (SNR 15–30 dB). Avaliação de robustez **separada** e mais dura: 250–5000 Hz, SNR 12 dB, saturação e 12 bits. Ela derruba a acurácia de ~79% para ~72%.
- **Servidor com `http.server`** da biblioteca padrão (sem Flask): menos dependências e menos coisas para explicar. Uma trava garante que o serviço nunca faz dois pedidos simultâneos ao ESP32.
- **Base de conhecimento** (`diagnosticos.json`): texto conservador, sempre com o aviso "apoio à decisão, não substitui um mecânico". **A equipe deve revisar.**

## Rodada 2 da IA (09/11) — mais dados, encontrados pela própria equipe/assistente

- **MyDataSet** (Hugging Face, gravações de celular): adicionadas **`falha_correia`** (59 arquivos) e **`falha_tucho`** (68). As partes `healthy`/`misfire` desse dataset não foram usadas, porque já estão dentro do kwerimoto (duplicação entre treino e teste).
- **ESC-50** (CC BY-NC): 1755 trechos de sons ambientais como `nao_carro`, agrupados pelo clipe de origem. Ficaram de fora as categorias ambíguas (motor, buzina, trem, avião, helicóptero, motosserra). O porteiro agora é avaliado também contra sons de sala (palmas, risada, teclado, batida em porta...).
- **OtoMobile** avaliado e descartado: 65 gravações para 12 falhas (~5 por classe). **Kaggle** não foi usado: exige login.
- **Aumento de dados com a cadeia de captura**: a cópia de treino agora sorteia a faixa do alto-falante (100–300 Hz a 4–7 kHz), o ruído (SNR 10–30 dB) e, com 50% de chance cada, saturação e quantização de 12 bits. O teste de robustez continua com parâmetros **fixos** e só em trechos de teste. Com isso, a aceitação do porteiro em áudio degradado foi de 79% para 82% e o diagnóstico degradado de 71% para 73%.
- **Comparação antes de trocar o modelo**: só aceitamos o modelo novo porque ele não piorou nas métricas que importam para a demo (ver tabela no histórico de commits). O modelo anterior está na tag `v1.0-pre-montagem`.
- **Kit de demonstração** (`tools/montar_sons_demo.py`): trechos de teste que o pipeline acerta em **qualquer** janela de 5 s. A primeira versão validava só os 5 s iniciais e falhou no tucho (inconclusivo); depois da correção, acertou 24 de 24 no simulador. Na apresentação, dizer que são exemplos escolhidos; as métricas honestas são as do `metricas_ia.md`.
- **Modo ao vivo com memória de 5 s**: analisar só 1–1,5 s por vez fazia o resultado oscilar. Tocando knock, o painel alternava entre "batida", "normal" e "fala", e a decisão estabilizada chegou a ficar em NORMAL. Agora o serviço guarda as últimas 5 janelas de 1 s e analisa tudo junto a cada segundo (mesmo formato do botão). Silêncio, erro de rede, diagnóstico ou troca de ESP32 zeram a memória. No simulador, as 6 classes do kit deram 12 de 12 leituras corretas ao vivo.
- **Bug corrigido — alerta antigo reenviado**: a decisão estabilizada ficava guardada. Ao ligar "IA comanda os LEDs" depois de um alerta antigo, o LED vermelho acendia mesmo em silêncio (59 de 60 leituras no teste). Agora ligar/desligar a opção ou trocar de ESP32 zera a decisão. Reteste no mesmo cenário: 0 de 60.
- **Mensagem "não é carro"**: o nome do som só aparece quando o YAMNet o reconheceu claramente (veto). Antes podia sair "não é motor de carro (veículo)".

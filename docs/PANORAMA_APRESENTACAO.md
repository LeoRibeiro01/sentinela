# SENTINELA — Panorama completo para a apresentação

Material-base para os slides e para a defesa. Organizado na ordem do **regulamento V1.2** (o que a banca vai conferir), com o que mostrar ao vivo, como cada parte funciona e os números medidos na placa. Valores entre parênteses vêm de testes reais (`docs/evidencias/`, `docs/DECISOES.md`).

---

## 1. Em uma frase

**O SENTINELA escuta o motor:** um microfone ligado a um ESP32 capta o som; o ESP32 é o **servidor** da rede (porta TCP 80), entrega a própria página web, as leituras e o áudio, recebe comandos para uma **tela OLED**, LEDs e buzzer, e guarda um **log com data e hora** na memória flash. Um serviço de IA no notebook ouve o áudio pela rede, diz se é um motor e qual a falha provável, e manda o resultado para a tela da placa.

Problema que resolve: ruídos anormais são o primeiro sintoma de muitas falhas (detonação, falha de ignição, correia gasta, tuchos), mas o motorista não sabe identificá-los nem descrevê-los ao mecânico.

---

## 2. Requisitos do regulamento × como o SENTINELA atende (slide principal)

| Requisito (V1.2) | Como atendemos | O que mostrar ao vivo |
|---|---|---|
| ESP32 **obrigatoriamente servidor** (listen, aceita conexões, responde, passivo) | `WebServer` na **porta TCP 80**; a placa nunca inicia conexão com os clientes | `Test-NetConnection <ip> -Port 80` → `True`; porta 81 → `False` |
| Clientes conectam via Wi-Fi | Notebook e celular na mesma rede (hotspot) ou na rede própria `SENTINELA` | Abrir `http://<ip>/` no PC **e** no celular |
| Conectar-se a uma rede Wi-Fi e **reconectar com log de data e hora** | Modo estação + reconexão a cada 15 s, cada etapa registrada no log | Desligar o hotspot ~30 s → log mostra `PERDIDA` e `RECONECTADO após N s` |
| Servidor TCP/HTTP/UDP | **HTTP/1.1 sobre TCP** (servidor web embarcado) | `curl -v` mostrando conexão e cabeçalhos |
| Clientes **consultam o sensor** | `/sensor` (nível, RMS, pico) e `/audio.wav` (áudio real) | Bater palma → nível sobe no dashboard |
| Clientes **enviam comandos** | `/atuador`, `/config`, `/wifi`, `/relogio` | Botões do dashboard → tela e LEDs mudam |
| **Log persistente na flash** com ERRO / AVISO / INFO e data/hora | LittleFS (`/log.txt`), rota `/log`, painel no dashboard | Apertar EN (reinício) → log antigo continua lá + "Boot #N" |
| **IP e MAC**, status da conexão, dados em tempo real | `/status` + cartão Sistema + rodapé da tela OLED | Cartão Sistema; tela mostrando o IP |
| Uso explícito da pilha TCP/IP e de portas | Wi-Fi → IPv4 (DHCP/ARP/ICMP) → TCP 80 → HTTP; auxiliares UDP 123 (NTP) e 5353 (mDNS) | Tabela ARP com o MAC da placa; ping |
| Arquitetura cliente-servidor documentada | README, relatório, `API.md`, diagrama | Slide da arquitetura |
| Código em **repositório público** | github.com/LeoRibeiro01/sentinela | Mostrar o repositório |
| ≥ 1 sensor | Microfone **GY-MAX9814** (GPIO34, 16 kHz) | — |
| ≥ 1 atuador **que não seja LED nem buzzer** | **Tela OLED SSD1306 0,96" I2C**, comandada pela rede | `/atuador?estado=alerta&falha=Batida de pino` → tela muda |
| Testes com evidência (ping, porta, cliente-servidor, sensor/atuador) | `tools/coletar_evidencias.ps1`: **19 de 19 aprovados** na placa | Pasta `docs/evidencias/2026-11-13_091511/` |
| Relatório ABNT com 5 projetos semelhantes | `docs/RELATORIO_TDE.md` / `.docx` com **6** projetos (diagrama + código + bibliotecas) | — |

---

## 3. Arquitetura (slide)

Figura: `docs/arquitetura.png`.

```text
   [Microfone MAX9814] ──analógico──►  ┌──────────── ESP32 (SERVIDOR, TCP 80) ────────────┐
                                        │ Captura 16 kHz (núcleo 1)                        │
   [Tela OLED] ◄──I2C──                 │ HTTP + log + Wi-Fi (núcleo 0)                    │
   [LEDs, buzzer] ◄──GPIO──             │ Log na flash · Wi-Fi estação + AP "SENTINELA"    │
                                        └──────────────────────┬───────────────────────────┘
                                                               │ Wi-Fi (hotspot / roteador)
                         ┌─────────────────────────────────────┼──────────────────────────┐
                         ▼                                     ▼                          ▼
          Navegador (PC ou celular)                 Serviço de IA (notebook)        curl / testes
          página vem DA PLACA                       puxa /audio.wav, classifica,    (evidências)
          polling 1 s                               manda /atuador?...&falha=
```

Pontos para falar:
- **O ESP32 é o servidor**; navegador, IA e ferramentas de teste são **clientes**.
- **A página web mora na placa** (gravada na flash, comprimida, ~17 KB). Placa desligada = página não abre.
- **Duas redes ao mesmo tempo (AP+STA):** a placa entra no hotspot (requisito) e mantém a própria rede `SENTINELA` (192.168.4.1) como plano B.
- **Núcleo obrigatório não depende da IA**: se o serviço de IA cair, sensor, comandos, log e tela continuam.

---

## 4. Hardware e pinagem (slide)

Figura: `docs/esquematico.png` + foto da montagem.

| Componente | Função | Pino do ESP32 |
|---|---|---|
| ESP32 DevKit v1 (WROOM-32) | Servidor, aquisição, controle | — |
| GY-MAX9814 | **Sensor**: microfone com ganho automático (ganho fixo 40 dB) | OUT → **GPIO34** (ADC1); VDD → 3V3 |
| OLED SSD1306 0,96" I2C | **Atuador**: mostra estado, falha, IP, hora | SDA → **GPIO21**, SCL → **GPIO22**, VCC → 3V3 |
| LED verde / vermelho (220 Ω) | Sinalização normal / alerta | GPIO16 / GPIO17 |
| Buzzer ativo 5 V via transistor BC548 (1 kΩ na base) | Bipe curto ao fim do diagnóstico | GPIO18; (+) no VIN |

Por que GPIO34: é do **ADC1** — o ADC2 do ESP32 fica ocupado pelo rádio Wi-Fi.
Por que transistor no buzzer: o buzzer de 5 V pede mais corrente que um pino do ESP32 fornece com segurança.

---

## 5. Como cada parte funciona por dentro

### 5.1 Aquisição do som (sensor)
- Um **timer de hardware** dispara 16 000 vezes por segundo e acorda uma tarefa no **núcleo 1** que lê o ADC.
- O nível DC (~1,25 V do microfone) é removido por média móvel; as amostras vão para um **buffer circular de ~2 s** (64 KB).
- A cada 250 ms calcula **RMS, pico, nível 0–100** (RMS 600 = 100) e saturação.
- Medido: **15 999–16 000 Hz**, maior intervalo entre amostras ~80 µs.

### 5.2 Servidor HTTP (o coração do requisito)
- Tarefa principal no **núcleo 0**, ~1000 voltas/s; resposta típica ~140 ms.
- Rotas: `/` (página), `/status`, `/sensor`, `/audio.wav`, `/atuador`, `/config`, `/log`, `/wifi`, `/relogio`, `/info`.
- Valida tudo: parâmetro inválido → **400**, rota inexistente → **404**, ambos em JSON e registrados no log com o IP de quem pediu.
- O áudio sai como **WAV** gerado na hora, enviado em blocos de 512 bytes (nunca copia 64 KB na RAM).

### 5.3 Wi-Fi e reconexão
- Rede da placa configurada pelo dashboard (`/wifi`), salva na memória não volátil (NVS).
- Se cair: tenta de novo **a cada 15 s, para sempre**, sem travar nada; registra a queda, as tentativas e o tempo até reconectar.
- Hora certa: **NTP** pela internet ou, sem internet, o próprio dashboard envia a hora do aparelho (`/relogio`).
- Medido: reconexão em **32 s** no teste (e 24 s em queda espontânea do hotspot).

### 5.4 Log persistente
- Arquivo `/log.txt` no **LittleFS** (sistema de arquivos na flash); ao passar de 48 KB vira `/log_antigo.txt`.
- Qualquer parte do sistema registra numa **fila**; só a tarefa principal escreve na flash (sem conflito).
- Cada evento é gravado **na hora**. Antes de a placa saber a hora, a linha sai como `sem hora (+Ns)` e, quando a hora chega, uma linha diz "este boot começou às HH:MM:SS".
- Registra: boot e motivo do reinício (reinício inesperado = **ERRO**), rede, quedas, clientes, comandos, pedidos inválidos, tela detectada/perdida, memória baixa.

### 5.5 Tela OLED (atuador)
- Tarefa própria (4 quadros/s). Mostra: **SENTINELA + hora** · **estado em letras grandes** (ALERTA pisca) · **texto da falha** (2 linhas) · **IP** · **barra de nível**.
- Procura a tela sozinha a cada 3 s: o sistema funciona sem ela e a reconhece quando é ligada.

### 5.6 Inteligência artificial (diferencial)
- Roda no notebook (Python), **cliente** da placa: puxa 1 s de áudio por segundo.
- **YAMNet** (rede do Google treinada em 2 milhões de áudios) transforma o som em 1024 números; dois classificadores simples decidem:
  1. **"É motor de carro?"** (porteiro, 93% de acerto no teste)
  2. **Qual estado:** normal · batida de pino · falha de ignição · correia · tucho/balancim (**81,7%** no teste, separado por gravação)
- Abaixo de 60% de confiança responde **"inconclusivo"** (não finge certeza); quase silêncio → **"sinal fraco"**.
- Ao fim do diagnóstico manda à placa: `/atuador?estado=alerta&falha=Batida de pino (78%)&bip=1` → tela + LED vermelho + **bipe curto**.
- Teste com som de fora do treino (correia tirada de rede social): **acertou** (teste isolado; a métrica oficial é a do conjunto de teste).

---

## 6. O dashboard, elemento por elemento

Abre em `http://<ip-da-placa>/`. A página **vem da placa**; consulta a placa a cada 1 s (`/status` e `/sensor`, sempre em sequência, porque o servidor atende um cliente por vez) e o log a cada 15 s.

### Topo
- **Emblema + SENTINELA:** identidade visual (escudo = proteção; olho = vigilância).
- **Selo ESP32: CONECTADO / DESCONECTADO:** cada pedido espera no máximo 2 s; **duas falhas seguidas** = DESCONECTADO. O laço nunca para, então reconecta sozinho.
- **Selo IA: ONLINE / OFFLINE:** se o serviço de IA do notebook responde. No celular aparece OFFLINE (a IA roda no notebook) e o resto funciona normalmente.
- **Tela "ESP32 DESCONECTADO":** se a placa cai, a interface inteira some atrás desse aviso; quando a placa volta, a página é **recarregada a partir da placa** (prova de que ela é servida pelo ESP32).

### Cartão Microfone (sensor)
- **Número grande "nível" (0–100):** intensidade do som na última janela de 250 ms. É uma escala relativa (RMS 600 = 100), **não é decibel**.
- **Barra:** verde até 40, amarela até 70, vermelha acima.
- **RMS:** "energia média" do som em contagens do conversor (sem o nível DC). **Pico:** maior desvio da janela. **Saturação:** "SIM" se o sinal bateu no limite do conversor (som alto demais).
- **Gráfico de 60 s:** um ponto por segundo; **lacunas** = momentos em que a placa não respondeu.

### Cartão Atuadores
- **Três círculos (Verde, Vermelho, Buzzer):** acendem conforme o estado **real** informado pela placa (não é a página adivinhando).
- **Estado:** NORMAL, ALERTA, DESLIGADO ou TESTE.
- **Espelho da tela OLED:** desenho do que a tela física está mostrando (estado, falha, hora, IP); útil para a plateia que está longe da placa.
- **"Tela OLED: conectada / não detectada":** se a placa encontrou a tela no I2C.
- **Texto da falha na tela (opcional):** o texto digitado vai junto com Normal/Alerta e aparece na tela física.
- **Botões:** **Normal** (verde) · **Alerta** (vermelho + tela "ALERTA", sem apito) · **Bipe (buzzer)** (apito leve de 150 ms) · **Teste** (pisca verde/vermelho + bipe, ~2 s, depois volta) · **Desligar**.
- **Modo Manual / Automático + Limiar + Aplicar:** no automático, a **própria placa** liga o alerta quando o nível passa do limiar por ~0,75 s e volta ao normal após ~2 s abaixo — é o plano B sem IA. **Na apresentação, deixar em Manual** (o barulho da sala dispara o automático).
- **Linha de mensagem:** confirma o comando enviado ("OK: …") ou o erro.

### Cartão Sistema
- **Data e hora (ESP32):** relógio da placa (NTP ou navegador).
- **Rede Wi-Fi:** nome da rede e sinal em dBm (−30 = ótimo, −70 = fraco), ou "DESCONECTADA, tentando".
- **IP na rede Wi-Fi / MAC (estação):** endereço da placa na rede do hotspot e o MAC dessa interface — **requisito do regulamento**.
- **Ponto de acesso / MAC (AP):** a rede própria `SENTINELA` (192.168.4.1) e o MAC dela (o ESP32 tem um MAC por interface).
- **Boot nº:** quantas vezes a placa ligou (salvo na memória não volátil).
- **Ligado há:** tempo desde o último boot. **Taxa de amostragem:** amostras de áudio lidas no último segundo (alvo 16 000 Hz). **Memória livre:** RAM disponível. **Amostras perdidas:** leituras que não aconteceram (ideal: quase zero). **Clientes no Wi-Fi:** aparelhos conectados à rede `SENTINELA`. **Última resposta:** hora da última leitura bem-sucedida.
- **Configurar rede Wi-Fi da placa:** nome e senha da rede; "Esquecer rede" volta a usar só a `SENTINELA`.

### Cartão Diagnóstico por IA
- **DIAGNOSTICAR (5 s):** captura 5 janelas de 1 s, descarta as silenciosas, analisa e mostra o resultado; ao fim a placa dá um **bipe** e a tela mostra a falha.
- **Barra de progresso:** "Capturando…" e depois "Analisando…".
- **Ranking:** porcentagem de cada classe = **probabilidade estimada pelo modelo**; a primeira em destaque.
- **Cartão do diagnóstico:** título, **causas prováveis**, **o que verificar**, **urgência** (baixa/média/alta) e o aviso "apoio à decisão, não substitui um mecânico".
- **Modo demo (animais):** a IA também reconhece gato, cachorro, pássaro… (para a plateia testar).
- **IA comanda os LEDs (ao vivo):** liga o modo contínuo — a IA decide a cada segundo (maioria de 3 em 5) e só manda comando quando o estado muda.
- **Calibrar silêncio (3 s):** mede o ruído da sala e ajusta o que é "silêncio" — fazer antes da demonstração.
- **Ao vivo (a cada ~1 s):** o que a IA está ouvindo agora; **Decisão estabilizada**; **histórico** das últimas leituras.

### Cartão Log do sistema
- Lista das últimas 50 linhas do log **da flash da placa**, mais recente no topo; **amarelo = AVISO**, **vermelho = ERRO**, cinza = INFO.
- **Filtro por nível**, **Atualizar** e **Baixar log completo** (arquivo `.txt` direto da placa).

### Cartão Último trecho de áudio
- **Capturar 1 s:** baixa `/audio.wav` da placa. **"a cada 5 s":** captura automática.
- **Forma de onda:** o sinal no tempo. **Espectro 0–4 kHz:** quais frequências compõem o som (FFT de 2048 pontos com janela de Hann), com a frequência de pico.
- **Player:** ouvir exatamente o que o microfone captou.

---

## 7. Testes e evidências (slide com números)

Placa real, 13/11/2026, rede "iPhone" (IP 172.20.10.8). Pasta `docs/evidencias/2026-11-13_091511/`.

| Teste | Resultado |
|---|---|
| Ping | 9/10 respostas, 9–102 ms |
| ARP | MAC da placa visto pela rede = MAC informado pela placa (`b0:cb:d8:cd:83:54`) |
| Porta TCP 80 | aberta (porta 81 fechada) |
| Socket TCP "à mão" | pedido HTTP em texto puro → `HTTP/1.1 200 OK` |
| Rotas, sensor, áudio, atuadores, erros 400/404, log | todos OK |
| **Reconexão Wi-Fi** | caiu 09:17:23 → reconectou 09:17:56 (**32 s**), registrado no log |
| **Total** | **19 de 19** |

Outros números: servidor no ar **0,34 s** após ligar · amostragem **16 000 Hz** · resposta HTTP ~140 ms · IA **81,7%** (5 classes) e **93%** no "é carro?".

---

## 8. Problemas reais que resolvemos (bons para a defesa)

| Problema | Diagnóstico | Solução |
|---|---|---|
| HTTP lento/expirando | Medimos ~22 voltas/s no laço: a captura (16 kHz, núcleo 1) roubava a CPU | Servidor numa tarefa no **núcleo 0** → ~1000 voltas/s, ~140 ms |
| Navegador travava o servidor por 5 s | Chrome abre conexões "de reserva" sem pedido; o servidor atende um por vez | `servidor_rapido.h`: descarta conexão parada em 300 ms |
| Boot de 29 s | Medição de cada etapa: tudo depois da captura ficava sem CPU | Captura passou a ser a **última** etapa → **0,34 s** |
| Buzzer mudo | Resistor ligado no emissor do transistor, base solta | Resistor na **base** (BC548: C-B-E) |
| Microfone lendo zero | Leitura constante 0 = sem alimentação (jumper no pino GAIN) | Jumper no **VDD** |
| Eventos do boot sumiam do log | Ficavam esperando a hora na RAM; reinício rápido apagava | Gravação **imediata** + linha de referência de horário |
| Apito contínuo incomodando | Modo automático + barulho da sala = alerta com apito | Alerta sem som; **bipe curto** só no fim do diagnóstico |
| Quedas do hotspot | Log: motivo 200 (*beacon timeout*) — o iPhone para de anunciar a rede ao economizar energia | Reconexão automática (24–32 s); deixar a tela do Acesso Pessoal aberta |
| IA com 10 classes | Dados do YouTube: acurácia caiu de 81,7% para 48,7% | Experimento **descartado**, registrado (decisão baseada em medição) |

---

## 9. Limitações e trabalhos futuros (honestidade conta ponto)

- Servidor atende **um cliente por vez** (por isso o polling sequencial).
- **HTTP sem criptografia** e sem login — aceitável em rede local de demonstração; futuro: HTTPS e autenticação.
- Ruídos de suspensão/freio só aparecem com o carro andando; o microfone fica no motor.
- IA treinada com dados da internet; o próximo passo é **gravar motores reais pelo próprio microfone** (`record.py`).
- Futuro: WebSocket/MQTT (sem polling), vários microfones para localizar a falha, IA dentro do ESP32 (TinyML).

---

## 10. Sugestão de roteiro de slides (~10–12 min)

1. **Título** — SENTINELA, equipe, disciplina.
2. **Problema** — som como sintoma; motorista não sabe descrever.
3. **Solução em uma frase** + foto da montagem.
4. **Arquitetura cliente-servidor** (seção 3) — "o ESP32 é o servidor".
5. **Pilha TCP/IP no projeto** — Wi-Fi → IP → TCP 80 → HTTP (+ ARP, ICMP, NTP, mDNS).
6. **Hardware e pinagem** (seção 4) — sensor e atuador OLED.
7. **Requisitos × atendimento** (tabela da seção 2) — slide-chave para a banca.
8. **Log e reconexão** — trecho real do log com PERDIDA/RECONECTADO.
9. **Dashboard** — print anotado (seção 6).
10. **IA** — fluxo "é carro? → qual falha? → inconclusivo".
11. **Testes e evidências** — 19 de 19 (seção 7).
12. **Problemas resolvidos** (seção 8) e **trabalhos futuros**.
13. **Demonstração ao vivo**.

## 11. Roteiro da demonstração ao vivo (~4 min)

1. Hotspot ligado (tela de Acesso Pessoal aberta, "Maximizar Compatibilidade"). Placa ligada → tela mostra `IP 172.20.10.x`.
2. Abrir `http://<ip>/` no notebook **e** no celular → página vem da placa; mostrar IP, MAC, hora no cartão Sistema.
3. Bater palma → nível sobe; "Capturar 1 s" → forma de onda e espectro.
4. Botões Normal / Alerta (com texto "Batida de pino") / Bipe → tela, LEDs e buzzer mudam.
5. `Test-NetConnection <ip> -Port 80` e `curl.exe -v http://<ip>/status` num terminal.
6. **Calibrar silêncio** → tocar `falha_batida_pino_1.wav` perto do microfone → **DIAGNOSTICAR** → bipe + tela com a falha.
7. **Reconexão:** desligar o hotspot ~30 s → tela vai para `AP 192.168.4.1` → religar → volta; mostrar o log com data e hora.
8. **Página depende da placa:** desligar o USB → página some; religar → volta sozinha.

Plano B: se o hotspot falhar, tudo funciona pela rede `SENTINELA` (192.168.4.1); se a IA falhar, o núcleo obrigatório continua.

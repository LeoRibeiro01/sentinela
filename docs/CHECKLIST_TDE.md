# Checklist do regulamento (TDE V1.2) × SENTINELA

Cada item do documento "TDE – Conectividade de Sistemas Ciberfísicos V1.2", onde o sistema o atende e como provar na apresentação.
Legenda: ✅ atendido · 🔶 depende de ação da equipe (indicada) · ⏳ verificar com a placa/tela.

## 2. Objetivo

| Item | Situação | Onde / como provar |
|---|---|---|
| ESP32 funciona obrigatoriamente como servidor | ✅ | `WebServer` na porta TCP 80 (`esp32_server.ino`, `servidor.begin()`); `Test-NetConnection -Port 80` |
| Clientes estabelecem conexão com o ESP via Wi-Fi | ✅ | PC e celular pela rede da estação ou pela rede `SENTINELA`; log registra entrada de clientes no AP |
| Dados de sensores acessados remotamente | ✅ | `GET /sensor`, `GET /audio.wav`, painel Microfone |
| Atuadores acionados via rede | ✅ | `GET /atuador?estado=...&falha=...` (tela OLED, LEDs, buzzer) |

## 3.1 Arquitetura

| Item | Situação | Onde / como provar |
|---|---|---|
| Abrir uma porta de escuta (listen) | ✅ | Porta 80; evidência `03_porta_tcp.txt` (80 aberta × 81 fechada) |
| Aceitar conexões externas | ✅ | `04_socket_tcp.txt` (cliente TCP escrito à mão), `05_rotas_consulta.txt` (`curl -v` mostra o handshake) |
| Responder a requisições | ✅ | Todas as rotas; erros 400/404 em JSON (`09_erros.txt`) |
| Permanecer passivo aguardando conexões | ✅ | O ESP32 nunca inicia conexões com clientes; `tarefaPrincipal` só chama `handleClient()` |
| Não ser exclusivamente cliente | ✅ | (Único papel de cliente: NTP, opcional, para a hora) |

## 3.2 Requisitos funcionais

| Item | Situação | Onde / como provar |
|---|---|---|
| 1. Conectar-se a uma rede Wi-Fi | ✅ ⏳ | `rede.cpp`, modo estação; rede configurada pelo dashboard (`/wifi`) e salva na NVS. Testar com o hotspot (MONTAGEM seção 4) |
| 1. Reconectar ao perder a conexão | ✅ ⏳ | `processarRede()`: nova tentativa a cada 15 s. Teste: desligar e religar o hotspot |
| 1. Gravar em log a data e a hora da queda/reconexão | ✅ ⏳ | Linhas `[AVISO] ... PERDIDA` e `[INFO] ... RECONECTADO após N s` com data/hora (NTP ou relógio do navegador) |
| 2. Servidor HTTP embarcado | ✅ | `WebServer` + `servidor_rapido.h`; a interface web é servida pela placa (`/`) |
| 3. Clientes consultam dados do sensor | ✅ | `/sensor`, `/audio.wav`, `/status` |
| 3. Clientes enviam comandos | ✅ | `/atuador`, `/config`, `/wifi`, `/relogio` |
| 3. Log persistente em flash com ERRO/AVISO/INFO e data/hora | ✅ ⏳ | `registro_log.cpp` (LittleFS); `GET /log`; painel "Log do sistema" com filtro por nível e download. Teste: reiniciar (EN) e ver o log antigo continuar lá |
| 4. Endereço IP e MAC do dispositivo | ✅ | `/status` → `rede.sta_ip`, `rede.sta_mac`, `rede.ap_ip`, `rede.ap_mac`; cartão Sistema; IP também na tela OLED |
| 4. Status da conexão | ✅ | Selo CONECTADO/DESCONECTADO (cliente ↔ servidor); `rede.sta_conectado` e `rssi` (placa ↔ roteador) |
| 4. Dados coletados em tempo real | ✅ | Polling de 1 s; nível ao vivo e histórico de 60 s; forma de onda e espectro |

## 3.3 Requisitos técnicos

| Item | Situação | Onde / como provar |
|---|---|---|
| Uso explícito da pilha TCP/IP | ✅ | Wi-Fi 802.11 → IPv4 (DHCP na estação, IP fixo no AP) → TCP porta 80 → HTTP/1.1. ARP (`02_arp.txt`), ICMP (`01_ping.txt`), mDNS/UDP 5353 e NTP/UDP 123 como serviços auxiliares |
| Uso de portas de comunicação | ✅ | TCP 80 (servidor da placa), TCP 5000 (serviço de IA local), UDP 123 (NTP), UDP 5353 (mDNS) |
| Arquitetura cliente-servidor documentada | ✅ | README (Arquitetura), `docs/RELATORIO_TDE.md` cap. 3, `docs/API.md`, diagrama `docs/arquitetura.png` |
| **Código em repositório público no GitHub** | 🔶 | O repositório ainda **não tem remoto**. A equipe precisa criar o repositório público e fazer o push (ver "Pendências") |
| Projeto físico montado e funcional | 🔶 ⏳ | Montagem com a tela OLED (`docs/MONTAGEM_SEGUNDA.md`) |

## 3.4 Requisitos de hardware

| Item | Situação | Onde / como provar |
|---|---|---|
| Mínimo de 1 sensor | ✅ | Microfone GY-MAX9814 no GPIO34 (ADC1), 16 kHz |
| **Mínimo de 1 atuador que não seja LED nem buzzer** | ✅ ⏳ | **Tela OLED SSD1306 I2C** (GPIO21/22): muda de estado por comando de rede e mostra estado e falha. Código pronto; a tela chega na montagem |
| Montagem física organizada e funcional | 🔶 | Protoboard conforme a tabela de pinos; fios curtos; tela visível para a banca |
| Demonstração em rede real | ✅ ⏳ | Hotspot do celular (rede real com DHCP) + rede `SENTINELA` |

## 4–5. Relatório (ABNT)

| Item | Situação | Onde |
|---|---|---|
| Sistemas ciberfísicos, OSI e TCP/IP, cliente-servidor, TCP e UDP, sockets, protocolo usado | ✅ | `docs/RELATORIO_TDE.md`, cap. 2 |
| Mínimo de 5 projetos semelhantes com diagramas, código e bibliotecas | ✅ | `docs/RELATORIO_TDE.md`, seção 2.7 (6 projetos, com hardware, pinos e bibliotecas) |
| Estrutura: introdução … referências | ✅ | `docs/RELATORIO_TDE.md` |
| Normas ABNT (formatação) | 🔶 | O conteúdo segue a NBR 6023 (referências) e a NBR 14724 (estrutura). A **formatação final** (capa, folha de rosto, margens 3/2 cm, Times/Arial 12, espaçamento 1,5, paginação) deve ser aplicada no editor de texto: `tools/gerar_relatorio_docx.py` gera um .docx já com margens, fonte, espaçamento e títulos numerados |

## 6. Testes e validação (com evidências)

| Item | Situação | Onde |
|---|---|---|
| Conectividade (ping) | ✅ ⏳ | `tools/coletar_evidencias.ps1` → `01_ping.txt` |
| Acesso à porta do servidor | ✅ ⏳ | `03_porta_tcp.txt` |
| Comunicação cliente-servidor | ✅ ⏳ | `04_socket_tcp.txt` (socket "telnet"), `05_rotas_consulta.txt` (`curl -v`) |
| Sensor e atuador via rede | ✅ ⏳ | `06_sensor_tempo_real.txt`, `07_audio_1s.wav`, `08_atuadores.txt` |
| Wireshark (opcional) | 🔶 | Captura com filtro `ip.addr == <placa> && tcp.port == 80` (MONTAGEM seção 6) |

## 8. Defesa técnica

Cada integrante deve saber explicar: o fluxo de um pedido HTTP do navegador até o handler e a resposta (`docs/EXPLICACAO_CODIGO.md`); por que a placa é servidor e não cliente; o modo AP+STA e a reconexão; o log (fila → tarefa principal → LittleFS); a amostragem por timer no núcleo 1 e o HTTP no núcleo 0; a tela no I2C. Perguntas prováveis com respostas estão em `docs/EXPLICACAO_CODIGO.md`.

## Pendências da equipe

1. **Gravar o firmware v2.0 na placa** (segurando BOOT) e rodar os testes da `MONTAGEM_SEGUNDA.md`, seções 5 e 6.
2. **Montar a tela OLED** (VCC 3V3, GND, SDA 21, SCL 22).
3. **Coletar as evidências na placa** com `coletar_evidencias.ps1` e fazer commit da pasta `docs/evidencias/`.
4. **Criar o repositório público no GitHub** e fazer o push (o histórico local já está pronto).
5. Preencher os **RAs** no README e no relatório; revisar o relatório e aplicar a formatação ABNT final.
6. Testar a reconexão desligando o hotspot e guardar o trecho do log como evidência.

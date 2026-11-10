# Montagem final e testes de aceitação — passo a passo

Guia para o dia da montagem final (tela OLED SSD1306 incluída) e para a apresentação. O firmware **já está pronto para a tela**: ele a procura no I2C a cada 3 s, funciona sem ela e a reconhece quando for ligada (o log registra "Tela OLED detectada").

Tempo estimado: 15 min de gravação do firmware + 20 min de montagem + 30 min de testes.

## 1. Tabela de pinos (fonte da verdade)

| Componente | Pino do componente | Liga em | Observação |
|---|---|---|---|
| MAX9814 (sensor) | VDD | 3V3 | **Nunca** em 5 V/VIN |
| MAX9814 | GND | GND | |
| MAX9814 | OUT | GPIO34 | Entrada analógica (ADC1) |
| MAX9814 | GAIN | VDD | Ganho fixo de 40 dB |
| MAX9814 | AR | — | Solto |
| **OLED SSD1306 (atuador)** | **VCC** | **3V3** | Módulo I2C de 4 pinos. A ordem dos pinos varia (GND-VCC-SCL-SDA ou VCC-GND-SCL-SDA): **leia a serigrafia** |
| OLED | **GND** | GND | |
| OLED | **SCL** | **GPIO22** | Clock do I2C |
| OLED | **SDA** | **GPIO21** | Dados do I2C |
| LED verde | ânodo (perna **longa**) | GPIO16 via **220 Ω** | Cátodo no GND |
| LED vermelho | ânodo (perna **longa**) | GPIO17 via **220 Ω** | Cátodo no GND |
| Transistor BC548 | base (meio) | GPIO18 via **1 kΩ** | Face lisa para você: **C – B – E** |
| BC548 | emissor (direita) | GND | Só o GND nessa coluna |
| BC548 | coletor (esquerda) | buzzer (−) | |
| Buzzer ativo 5 V | (+) | **VIN** (5 V) | |

> Erro já cometido em 09/11: o resistor de 1 kΩ estava na coluna do **emissor** e a base ficou solta, então o buzzer não apitava. O resistor tem que terminar na coluna da perna do **meio** (base).

### Diagrama de ligação

```
            ESP32 DevKit v1
   GPIO16 ──[220Ω]──►|── GND            LED verde
   GPIO17 ──[220Ω]──►|── GND            LED vermelho
   VIN (5V) ── (+) BUZZER (−) ── coletor ┐
   GPIO18 ──[1kΩ]──────────────── base   ├ BC548
   GND ──────────────────────── emissor  ┘
   3V3 ── VDD  MAX9814   GND ── GND   OUT ── GPIO34   GAIN ── VDD
   3V3 ── VCC  OLED      GND ── GND   SDA ── GPIO21   SCL ── GPIO22
```

## 2. Gravar o firmware novo (uma vez)

O firmware da apresentação (v2.0) tem o dashboard embutido, o log na flash, o Wi-Fi AP+STA e a tela OLED.

```powershell
.venv\Scripts\python tools\gerar_pagina_esp32.py      # só se src\client mudou
$cli = ".tools\arduino-cli\arduino-cli.exe"; $cfg = ".tools\arduino-cli\arduino-cli.yaml"
& $cli --config-file $cfg compile --fqbn esp32:esp32:esp32 src/esp32/esp32_server
& $cli --config-file $cfg upload -p COM6 --fqbn esp32:esp32:esp32 src/esp32/esp32_server
```

**Nesta placa:** segure o botão **BOOT** durante todo o upload (ela não entra sozinha em modo de gravação). Solte quando aparecer "Hard resetting" e aperte **EN** uma vez. Na primeira vez, o boot demora ~2 s a mais porque o LittleFS formata a área do log.

## 3. Ordem de montagem e energização

1. **Desligue o USB** da placa.
2. Trilho de **GND** da protoboard ligado ao GND do ESP32; trilho de **3V3** ligado ao 3V3 (MAX9814 e OLED); **VIN** só no (+) do buzzer.
3. Monte o **OLED**: VCC→3V3, GND→GND, SDA→GPIO21, SCL→GPIO22.
4. Confira: **nada de 5 V/VIN no MAX9814, no OLED nem em GPIO**.
5. Ligue o USB. Em ~3 s a tela mostra `SENTINELA`, `DESLIGADO`, "Aguardando comando" e, no rodapé, `AP 192.168.4.1` (ou `IP x.x.x.x` se já houver rede configurada).

## 4. Rede para a apresentação

O regulamento pede que a placa **se conecte a uma rede Wi-Fi** e se reconecte sozinha. Recomendado: **hotspot do celular de um integrante** (a rede da faculdade costuma isolar dispositivos e o eduroam exige login, que o ESP32 não faz).

1. Ligue o hotspot (2,4 GHz; anote nome e senha).
2. Conecte o notebook (ou celular) ao Wi-Fi **SENTINELA** (senha `sentinela123`) e abra **http://192.168.4.1/**.
3. *Sistema → Configurar rede Wi-Fi da placa* → nome e senha do hotspot → **Salvar e conectar**.
4. Em poucos segundos a tela OLED mostra `IP 192.168.x.x`. Conecte o notebook e os celulares ao **hotspot** e abra `http://<esse IP>/`.
5. A rede fica salva: nas próximas vezes, basta ligar o hotspot antes da placa.

Se o hotspot falhar, tudo continua funcionando pela rede `SENTINELA` (192.168.4.1).

## 5. Testes de cada atuador

```powershell
$ip = "192.168.4.1"   # ou o IP mostrado na tela
curl.exe "http://$ip/atuador?estado=teste"                              # pisca, BEEP; tela "TESTE"
curl.exe "http://$ip/atuador?estado=normal"                             # verde; tela "NORMAL / Motor normal"
curl.exe "http://$ip/atuador?estado=alerta&falha=Batida%20de%20pino"    # vermelho + buzzer; tela "ALERTA" piscando + "Batida de pino"
curl.exe "http://$ip/atuador?estado=off"                                # tudo apagado; tela "DESLIGADO"
```

| Sintoma | Causa provável | Ação |
|---|---|---|
| Tela apagada e log com "Tela OLED não encontrada" | SDA/SCL trocados, VCC/GND trocados ou fio solto | Confira a serigrafia do módulo; troque SDA↔SCL |
| Tela com chuvisco/lixo | Módulo SH1106 (não SSD1306) | Plano B: o espelho da tela no dashboard mostra o mesmo conteúdo |
| Buzzer mudo, LEDs ok | Resistor na coluna errada do transistor | Seção 1 (C-B-E, resistor na base) |

## 6. Testes de aceitação e evidências (regulamento V1.2, seção 6)

Com a placa na rede, rode **um comando** que gera todas as evidências de rede:

```powershell
powershell -ExecutionPolicy Bypass -File tools\coletar_evidencias.ps1 -Alvo <ip-da-placa>
```

Saída em `docs\evidencias\<data>\` (ping, ARP, porta TCP 80, socket TCP "telnet", `curl -v` de cada rota, atuadores, erros 400/404, log) com `RESUMO.md`. Faça **commit** dessa pasta: é a evidência pedida no relatório.

| # | Teste | Como | Passou? |
|---|---|---|---|
| 1 | Placa conecta ao Wi-Fi e mostra IP na tela | Seção 4 | ☐ |
| 2 | **Reconexão com log**: desligue o hotspot ~30 s e religue | `/log` mostra "PERDIDA" e "RECONECTADO após N s" com data/hora | ☐ |
| 3 | Página só existe com a placa ligada | Desligue a placa: a página some ("ESP32 DESCONECTADO"); F5 não abre; religue: volta sozinha | ☐ |
| 4 | Acesso pelo PC **e** pelo celular | `http://<ip>/` nos dois | ☐ |
| 5 | Sensor reage a palma e voz; áudio toca | Painel Microfone + "Capturar 1 s" | ☐ |
| 6 | Tela OLED, LEDs e buzzer por comando de rede | Botões e campo "Texto da falha" | ☐ |
| 7 | Log persistente: sobrevive a reinício | Aperte EN; o log continua com as linhas antigas + "Boot #N" | ☐ |
| 8 | IP, MAC e status da conexão visíveis | Cartão Sistema do dashboard e `/status` | ☐ |
| 9 | Evidências coletadas | `coletar_evidencias.ps1` com todas as linhas `[OK]` | ☐ |
| 10 | 30 min sem reiniciar | `python tools\teste_fase1.py resistencia --host <ip> --minutos 30` | ☐ |

Para a evidência com **Wireshark** (opcional): capture na interface Wi-Fi com o filtro `ip.addr == <ip-da-placa> && tcp.port == 80`, faça um `curl` e mostre o handshake SYN / SYN-ACK / ACK, o GET e a resposta HTTP.

## 7. IA (opcional, diferencial)

Duplo clique em **`tools\iniciar_ia.bat`** (pergunta nada; usa `192.168.4.1`). Se a placa estiver no hotspot, rode `.venv\Scripts\python src\ai\server.py --esp32 <ip-da-placa>`. No Chrome/Edge, aceite "acessar dispositivos da rede local" se aparecer.

1. **Calibrar silêncio** com a sala quieta.
2. Marque "IA comanda os LEDs": em 2 min de silêncio nada de alerta.
3. Toque o kit `data\demo_sons\<classe>\` perto do microfone e clique **DIAGNOSTICAR (5 s)**: a tela OLED mostra a falha e a porcentagem.

## 8. Power bank

- O AP aparece em até 15 s. Alguns power banks desligam com consumo baixo (~100–170 mA): se a placa apagar sozinha, use o USB do notebook.
- Se a placa não subir o AP ao ligar no power bank, aperte **EN** uma vez.

## 9. Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| Wi-Fi `SENTINELA` não aparece | Placa reiniciando / sem firmware | Aperte EN; veja o monitor serial |
| Placa não conecta ao hotspot | Hotspot em 5 GHz, senha errada ou rede com login (eduroam) | Use 2,4 GHz; confira em `/log` ("Sem conexão com ...") |
| Dashboard "ESP32 DESCONECTADO" | Notebook saiu da rede da placa | Reconecte ao Wi-Fi certo |
| Log com "sem hora" | Placa sem internet e nenhum dashboard aberto ainda | Abra o dashboard: ele acerta o relógio sozinho |
| Painel IA "OFFLINE" | `server.py` parado, ou aberto no celular | Normal no celular; no notebook rode o serviço |
| Placa reinicia ao apitar | Queda de tensão | USB do notebook; buzzer no VIN, nunca no 3V3 |

## 10. Plano B (ordem de recuo)

1. **Hotspot falhou** → tudo pela rede `SENTINELA` (192.168.4.1). A reconexão pode ser demonstrada desligando e religando o próprio ponto de acesso do notebook/celular de teste, ou mostrando o log de um teste anterior.
2. **IA falhou** → núcleo obrigatório: dashboard + sensor + comandos + log + modo `auto` por nível.
3. **Tela OLED não funciona** → o espelho da tela no dashboard mostra exatamente o que ela exibiria; mostre o log com o aviso e explique a detecção automática.
4. **Placa queimou** → grave o firmware na reserva (seção 2, ~2 min).

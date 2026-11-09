# Montagem de segunda-feira — passo a passo

**Nenhuma mudança de código é necessária.** O firmware já configura GPIO16/17/18 como saída (sem nada ligado, isso é inofensivo) e o LED azul da placa (GPIO2) espelha o alerta. Segunda é só ligar fios, testar e validar.

Tempo estimado: 30 min de montagem + 30 min de testes + 30 min de gravação/ajuste da IA (opcional, mas recomendado).

## 1. Tabela de pinos (fonte da verdade)

| Componente | Pino do componente | Liga em | Observação |
|---|---|---|---|
| MAX9814 (já montado) | VDD | 3V3 | **Nunca** em 5 V/VIN |
| MAX9814 | GND | GND | |
| MAX9814 | OUT | GPIO34 | Entrada analógica (ADC1) |
| MAX9814 | GAIN | VDD | Ganho fixo de 40 dB; não mexer entre gravações |
| MAX9814 | AR | — | Solto |
| LED verde | ânodo (perna **longa**) | GPIO16 via resistor **220 Ω** | Cátodo (perna curta, lado chanfrado) no GND |
| LED vermelho | ânodo (perna **longa**) | GPIO17 via resistor **220 Ω** | Cátodo no GND |
| Transistor NPN | base | GPIO18 via resistor **1 kΩ** | |
| Transistor NPN | emissor | GND | |
| Transistor NPN | coletor | buzzer (−) | |
| Buzzer ativo 5 V | (+) (perna longa / marcado "+") | **VIN** (5 V) | Corrente do buzzer passa pelo transistor, não pelo GPIO |

Use **um** LED de cada cor e **um** buzzer. As peças extras são reserva.

### Pinagem do transistor (confira qual veio!)

Segure o transistor com a **face reta virada para você** e as pernas para baixo:

| Modelo | Esquerda | Meio | Direita |
|---|---|---|---|
| **BC548** | Coletor | Base | Emissor |
| **2N2222** (cápsula plástica TO-92, "PN2222"/"2N2222A") | Emissor | Base | Coletor |

São **invertidos** entre si. Se o buzzer não apitar no teste, a primeira suspeita é o transistor ao contrário. (O 2N2222 em cápsula metálica tem outra pinagem: a perna ao lado da "aba" é o emissor.)

### Diagrama de ligação (protoboard)

```
            ESP32 DevKit v1
   GPIO16 ──[220Ω]──►|── GND        (LED verde: ►| = ânodo→cátodo)
   GPIO17 ──[220Ω]──►|── GND        (LED vermelho)

   VIN (5V) ───────────── (+) BUZZER (−) ──┐
                                           │ coletor
   GPIO18 ──[1kΩ]──────────────────── base  NPN
                                           │ emissor
   GND ────────────────────────────────────┘

   3V3 ── VDD  MAX9814   GND ── GND   OUT ── GPIO34   GAIN ── VDD
```

## 2. Ordem de montagem e energização

1. **Desligue o cabo USB** da placa.
2. Ligue o trilho de **GND** da protoboard ao GND do ESP32. Todos os GND (LEDs, emissor, MAX9814) vão nele.
3. Monte o **LED verde** (GPIO16 → 220 Ω → perna longa; perna curta → GND).
4. Monte o **LED vermelho** (GPIO17, igual ao verde).
5. Monte o **transistor + buzzer**: base ← 1 kΩ ← GPIO18; emissor → GND; coletor → (−) do buzzer; (+) do buzzer → VIN.
6. Confira com a tabela: **nada de 5 V/VIN no MAX9814 nem em GPIO**. VIN só no (+) do buzzer.
7. Ligue o **USB do notebook** (não o power bank ainda). O LED vermelho da placa acende; após ~2 s o Wi-Fi `SENTINELA` aparece. Nenhum LED externo deve acender sozinho (o firmware começa em `off`).
8. Só depois de tudo validado, teste com o **power bank** (seção 5).

## 3. Testes de cada atuador

Conecte o notebook ao Wi-Fi **SENTINELA** (senha `sentinela123`) e rode, no PowerShell, na pasta do projeto:

```powershell
curl.exe "http://192.168.4.1/atuador?estado=teste"     # ~2 s: verde, vermelho, verde, vermelho, BEEP, pausa
curl.exe "http://192.168.4.1/atuador?estado=normal"    # só o verde aceso
curl.exe "http://192.168.4.1/atuador?estado=alerta"    # vermelho + buzzer + LED azul da placa
curl.exe "http://192.168.4.1/atuador?estado=alerta&buzzer=0"   # vermelho sem apito
curl.exe "http://192.168.4.1/atuador?estado=off"       # tudo apagado
```

| Comando | Esperado | Se falhar |
|---|---|---|
| `teste` | pisca verde/vermelho 2×, beep de 0,5 s | ver linhas abaixo |
| `normal` | verde aceso | LED invertido (perna longa no GPIO) ou resistor fora da trilha certa |
| `alerta` | vermelho + **apito contínuo** + LED azul da placa | sem apito: transistor invertido (ver tabela), buzzer (+)/(−) invertido ou sem VIN |
| `off` | tudo apagado | apito contínuo em `off`: coletor/emissor trocados |

Depois, rode o teste automático completo: `python tools\teste_fase1.py rotas` (todas as linhas `[OK]`).

## 4. Testes de aceitação (seção 9 do CLAUDE.md)

Abra o dashboard: **duplo clique em `src\client\index.html`** (funciona sem a IA), ou suba a IA (seção 6) e abra `http://localhost:5000/`.

| # | Teste | Como | Passou? |
|---|---|---|---|
| 1 | Liga no power bank; AP em até 15 s; dashboard conecta | Cronometre do plugue até o Wi-Fi aparecer | ☐ |
| 2 | `/sensor` reage a palma e voz; `/audio.wav` toca | Painel "Microfone" + botão "Capturar 1 s" e ▶ | ☐ |
| 3 | Botões acendem verde/vermelho e acionam o buzzer | Botões Normal / Alerta / Buzzer / Teste | ☐ |
| 4 | IA estável no playback de falhas e **sem alerta falso em 2 min de silêncio** | Seção 6 | ☐ |
| 5 | Derrubar e religar: "DESCONECTADO" e reconecta sozinho | Aperte EN na placa; o selo fica vermelho em ~3 s e volta verde sozinho | ☐ |
| 6 | 30 min sem reiniciar | `python tools\teste_fase1.py resistencia --minutos 30` | ☐ |

## 5. Power bank

- Ligue a placa no power bank pelo mesmo cabo micro-USB. O AP deve aparecer em até 15 s.
- Alguns power banks **desligam sozinhos** quando o consumo é baixo (o ESP32 consome ~100–170 mA). Se o AP sumir depois de 30 s a alguns minutos, o power bank desligou. **Plano B:** alimentar pelo USB do notebook (funciona igual).
- O buzzer de 5 V vem do VIN, que no USB fica em ~4,7 V: normal e suficiente.

## 6. IA na segunda (com a placa e os atuadores)

```powershell
.venv\Scripts\activate
python src\ai\server.py
```

Abra `http://localhost:5000/`.

1. **Calibre o silêncio:** com a sala quieta, clique em **Calibrar silêncio (3 s)**.
2. **Silêncio por 2 min (aceitação 4):** marque "IA comanda os LEDs"; em silêncio o painel ao vivo deve mostrar "Silêncio / sinal fraco" ou "Não é motor de carro" e o LED **não** pode ir para vermelho.
3. **Playback:** toque no celular, a ~10 cm do microfone, um som de falha (ex.: arquivos de `data\raw\kwerimoto\prepared\test\engine_knock\`) e clique **DIAGNOSTICAR (5 s)**. Repita com `healthy` e com sua voz (deve dar "não é carro").
4. **Se o resultado ao vivo estiver ruim** (é o risco mais provável: o som do celular captado pelo MAX9814 é diferente dos datasets), grave 60 s de cada classe pela própria placa e retreine (≈ 5–10 min no total):

```powershell
python src\ai\record.py --classe normal --segundos 60              # som de motor normal tocado no celular
python src\ai\record.py --classe falha_batida_pino --segundos 60   # knock tocado no celular
python src\ai\record.py --classe falha_ignicao --segundos 60       # misfire tocado no celular
python src\ai\record.py --classe nao_carro --segundos 60           # conversa, palmas, ambiente da sala
python src\ai\prepare_dataset.py
python src\ai\train.py
```

Reinicie o `server.py` para ele carregar o modelo novo.

## 7. Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| Wi-Fi `SENTINELA` não aparece | Placa sem firmware / reiniciando | Abra o monitor serial (ver `docs/FASE_1_TESTES.md`); aperte EN |
| Placa reinicia ao acionar o buzzer | Queda de tensão (power bank/cabo fraco) | Use o USB do notebook; confira se o buzzer está no VIN e **não** no 3V3 |
| LED muito fraco | Resistor de 1 kΩ no lugar do de 220 Ω | Troque (220 Ω = vermelho-vermelho-marrom; 1 kΩ = marrom-preto-vermelho) |
| Buzzer apita sempre | Transistor invertido ou base sem resistor | Confira a pinagem na seção 1 |
| Dashboard "DESCONECTADO" | Windows trocou de rede | Reconecte ao `SENTINELA`; desative "conectar automaticamente" nas outras redes |
| Painel IA "OFFLINE" | `server.py` não está rodando | Rode o comando da seção 6; o resto do dashboard funciona sem ele |
| IA "sinal fraco" com som alto | Limiar de silêncio alto | Clique "Calibrar silêncio" em silêncio |
| IA diz "não é carro" para som de motor | Áudio muito diferente do treino | Grave com `record.py` e retreine (seção 6.4) |

## 8. Plano B (ordem de recuo)

1. **IA falhou ao vivo** → apresente o núcleo obrigatório: dashboard + sensor + comandos dos atuadores + modo `auto` por nível (`Modo: Automático`, limiar ~45). Mostre as métricas de `docs/metricas_ia.md` e um diagnóstico com o simulador tocando arquivos do dataset (abaixo).
2. **Atuadores não funcionam** → o LED azul da placa (GPIO2) mostra o alerta e o dashboard mostra o estado de cada saída.
3. **Placa queimou** → grave o firmware na reserva (`docs/FASE_1_TESTES.md`, comandos de upload). Leva ~2 min.
4. **Sem placa nenhuma** → simulador: `python tools\mock_esp32.py --wav-dir data\raw\kwerimoto\prepared\test\engine_knock` + `python src\ai\server.py --esp32 127.0.0.1:8080` e no dashboard use o endereço `127.0.0.1:8080`.

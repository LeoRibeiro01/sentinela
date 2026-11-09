# Métricas da IA

Gerado por `src/ai/train.py` em 09/11/2026 08:51. Avaliação por **trecho** (média das probabilidades dos quadros de 0,96 s) no conjunto de **teste**, separado por gravação e nunca usado para escolher hiperparâmetros ou limiares.

## Dados (trechos de até 10 s)

| classe | treino | validação | teste | real_test | fontes |
|---|---:|---:|---:|---:|---|
| normal | 246 | 52 | 52 | 0 | kwerimoto |
| falha_batida_pino | 397 | 85 | 82 | 38 | kwerimoto |
| falha_ignicao | 77 | 16 | 16 | 0 | amrrashed, kwerimoto |
| falha_correia | 40 | 9 | 9 | 0 | mydataset |
| falha_tucho | 50 | 14 | 10 | 0 | mydataset |
| falha_outros | 28 | 4 | 5 | 0 | amrrashed |
| nao_carro | 1343 | 309 | 274 | 0 | amrrashed, esc50, sintetico |

Treino usa também uma cópia aumentada de cada trecho (passa-faixa 150–6000 Hz + ruído, SNR 15–30 dB). Pesos balanceados por classe e, dentro da classe, pela raiz do tamanho de cada fonte. `falha_outros` (falhas mecânicas variadas, ~4 min) só ensina o porteiro: é pouco para virar diagnóstico.

## Escolha do hiperparâmetro C (F1-macro na validação)

| modelo | valor | F1 |
|---|---|---:|
| porteiro | C = 0.01 | 0.923 |
| porteiro | C = 0.1 | 0.923 |
| porteiro | C = 1.0 | 0.923 |
| diagnóstico | C = 0.01 | 0.773 |
| diagnóstico | C = 0.1 | 0.770 |
| diagnóstico | C = 1.0 | 0.775 |

## 1. Porteiro: é som de carro?

C escolhido: 0.01. **Acurácia no teste: 94.0%** só com o classificador; **93.1%** com o veto do YAMNet (fala, música, animais, chuva...), que é como roda ao vivo.

| classe | precisão | revocação | F1 | trechos |
|---|---:|---:|---:|---:|
| carro | 0.91 | 0.94 | 0.92 | 174 |
| nao_carro | 0.96 | 0.94 | 0.95 | 274 |

| real \ previsto | carro | nao_carro |
|---|---|---|
| **carro** | 163 | 11 |
| **nao_carro** | 16 | 258 |

Acertos por classe e fonte (teste):

| classe | fonte | trechos | só porteiro | porteiro + veto |
|---|---|---:|---:|---:|
| falha_batida_pino | kwerimoto | 82 | 93% | 91% |
| falha_correia | mydataset | 9 | 100% | 100% |
| falha_ignicao | kwerimoto | 16 | 100% | 100% |
| falha_outros | amrrashed | 5 | 80% | 80% |
| falha_tucho | mydataset | 10 | 100% | 100% |
| nao_carro | amrrashed | 18 | 94% | 94% |
| nao_carro | esc50 | 249 | 94% | 94% |
| nao_carro | sintetico | 7 | 100% | 100% |
| normal | kwerimoto | 52 | 92% | 85% |

Os negativos (`nao_carro`) vêm só do amrrashed (animais, clima, sirenes, tiros, obras). Fala e música não têm exemplos de treino e dependem do veto do YAMNet.

## 2. Diagnóstico (5 classes)

C escolhido: 1.0. **Acurácia no teste: 81.7%** · F1-macro: 0.868.

| classe | precisão | revocação | F1 | trechos |
|---|---:|---:|---:|---:|
| normal | 0.70 | 0.88 | 0.78 | 52 |
| falha_batida_pino | 0.92 | 0.71 | 0.80 | 82 |
| falha_ignicao | 0.76 | 1.00 | 0.86 | 16 |
| falha_correia | 1.00 | 0.89 | 0.94 | 9 |
| falha_tucho | 0.91 | 1.00 | 0.95 | 10 |

Matriz de confusão (trechos de teste):

| real \ previsto | normal | falha_batida_pino | falha_ignicao | falha_correia | falha_tucho |
|---|---|---|---|---|---|
| **normal** | 46 | 4 | 1 | 0 | 1 |
| **falha_batida_pino** | 20 | 58 | 4 | 0 | 0 |
| **falha_ignicao** | 0 | 0 | 16 | 0 | 0 |
| **falha_correia** | 0 | 1 | 0 | 8 | 0 |
| **falha_tucho** | 0 | 0 | 0 | 0 | 10 |

Acerto por classe e fonte (teste):

| classe | fonte | trechos | acerto |
|---|---|---:|---:|
| falha_batida_pino | kwerimoto | 82 | 71% |
| falha_correia | mydataset | 9 | 89% |
| falha_ignicao | kwerimoto | 16 | 100% |
| falha_tucho | mydataset | 10 | 100% |
| normal | kwerimoto | 52 | 88% |

### Normal × falha (o que aciona o alerta)

Precisão 94.2% · revocação 82.9% · F1 0.882.

### Simulação do botão DIAGNOSTICAR (grupos de ~5 s = 10 quadros)

Acurácia em 169 grupos de teste: **81.1%**.

| classe | precisão | revocação | F1 | trechos |
|---|---:|---:|---:|---:|
| normal | 0.70 | 0.85 | 0.77 | 52 |
| falha_batida_pino | 0.89 | 0.72 | 0.80 | 82 |
| falha_ignicao | 0.80 | 1.00 | 0.89 | 16 |
| falha_correia | 1.00 | 0.89 | 0.94 | 9 |
| falha_tucho | 0.83 | 1.00 | 0.91 | 10 |

### Limiar de confiança ("inconclusivo")

Curva no teste (grupos de 5 s):

| limiar | trechos respondidos | acurácia nos respondidos |
|---:|---:|---:|
| 40% | 98% | 81.8% |
| 50% | 93% | 83.5% |
| 60% | 76% | 89.1% |
| 70% | 54% | 90.2% |
| 80% | 37% | 95.2% |
| 90% | 18% | 100.0% |

Limiar escolhido **na validação**: **60%** (menor limiar com ≥ 90% de acerto respondendo ≥ 60% dos grupos). No teste ele responde 76% dos diagnósticos com 89.1% de acerto; o resto vira "inconclusivo" (o sistema não finge certeza). O serviço permite ajustar o limiar.

### Robustez: teste com áudio degradado (simula celular + MAX9814 + ADC de 12 bits)

Trechos de teste filtrados em 250–5000 Hz, ruído com SNR de 12 dB, saturação leve e quantização de 12 bits (degradação mais forte e diferente da usada no aumento de dados do treino), em pedaços de 5 s.

- acurácia: **72.5%** em 204 pedaços (sem degradação: 81.1%)
- com o limiar de 60%: responde 64% com 81.7% de acerto
- porteiro reconhece como carro: 82.4%

| real \ previsto | normal | falha_batida_pino | falha_ignicao | falha_correia | falha_tucho |
|---|---|---|---|---|---|
| **normal** | 51 | 7 | 2 | 0 | 1 |
| **falha_batida_pino** | 34 | 66 | 6 | 0 | 2 |
| **falha_ignicao** | 2 | 0 | 14 | 0 | 0 |
| **falha_correia** | 0 | 0 | 0 | 9 | 0 |
| **falha_tucho** | 0 | 0 | 2 | 0 | 8 |

### Knock real nunca visto (`real_test`, 38 clipes do AudioSet)

- classificado como `falha_batida_pino`: **89.5%**
- classificado como alguma falha (alerta acionado): 94.7%
- reconhecido como carro pelo porteiro: 100.0%

## Leitura honesta

- Os dados vêm de gravações da internet, e parte do knock/normal é **sintética** (Revix). O áudio captado pelo MAX9814 a partir de um alto-falante é diferente: **espere desempenho menor ao vivo**.
- `falha_ignicao` vem praticamente de uma única fonte (16 trechos de teste): o 100% de revocação é promissor, mas a amostra é pequena.
- Falhas mecânicas variadas (rolamento, correia, escapamento...) **não** são diagnosticadas: só há ~4 min de áudio delas, de 29 gravações diferentes. Elas ensinam o porteiro ("é carro") e são trabalho futuro.
- Os WAVs segmentados do dataset amrrashed estão corrompidos (ruído branco); usamos as gravações originais.
- A melhoria mais eficaz é gravar com `record.py` (som tocado no alto-falante e captado pelo próprio MAX9814) e retreinar.
- As porcentagens são probabilidade estimada pelo modelo, não certeza.

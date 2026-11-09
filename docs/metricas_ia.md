# Métricas da IA

Gerado por `src/ai/train.py` em 08/11/2026 23:27. Avaliação por **trecho** (média das probabilidades dos quadros de 0,96 s) no conjunto de **teste**, separado por gravação e nunca usado para escolher hiperparâmetros ou limiares.

## Dados (trechos de até 10 s)

| classe | treino | validação | teste | real_test | fontes |
|---|---:|---:|---:|---:|---|
| normal | 246 | 52 | 52 | 0 | kwerimoto |
| falha_batida_pino | 397 | 85 | 82 | 38 | kwerimoto |
| falha_ignicao | 77 | 16 | 16 | 0 | amrrashed, kwerimoto |
| falha_outros | 28 | 4 | 5 | 0 | amrrashed |
| nao_carro | 113 | 33 | 25 | 0 | amrrashed, sintetico |

Treino usa também uma cópia aumentada de cada trecho (passa-faixa 150–6000 Hz + ruído, SNR 15–30 dB). Pesos balanceados por classe e, dentro da classe, pela raiz do tamanho de cada fonte. `falha_outros` (falhas mecânicas variadas, ~4 min) só ensina o porteiro: é pouco para virar diagnóstico.

## Escolha do hiperparâmetro C (F1-macro na validação)

| modelo | valor | F1 |
|---|---|---:|
| porteiro | C = 0.01 | 0.925 |
| porteiro | C = 0.1 | 0.933 |
| porteiro | C = 1.0 | 0.914 |
| diagnóstico | C = 0.01 | 0.751 |
| diagnóstico | C = 0.1 | 0.759 |
| diagnóstico | C = 1.0 | 0.769 |

## 1. Porteiro: é som de carro?

C escolhido: 0.1. **Acurácia no teste: 95.6%** só com o classificador; **93.9%** com o veto do YAMNet (fala, música, animais, chuva...), que é como roda ao vivo.

| classe | precisão | revocação | F1 | trechos |
|---|---:|---:|---:|---:|
| carro | 0.96 | 0.99 | 0.97 | 155 |
| nao_carro | 0.90 | 0.76 | 0.83 | 25 |

| real \ previsto | carro | nao_carro |
|---|---|---|
| **carro** | 153 | 2 |
| **nao_carro** | 6 | 19 |

Acertos por classe e fonte (teste):

| classe | fonte | trechos | só porteiro | porteiro + veto |
|---|---|---:|---:|---:|
| falha_batida_pino | kwerimoto | 82 | 98% | 95% |
| falha_ignicao | kwerimoto | 16 | 100% | 100% |
| falha_outros | amrrashed | 5 | 100% | 100% |
| nao_carro | amrrashed | 18 | 67% | 89% |
| nao_carro | sintetico | 7 | 100% | 100% |
| normal | kwerimoto | 52 | 100% | 90% |

Os negativos (`nao_carro`) vêm só do amrrashed (animais, clima, sirenes, tiros, obras). Fala e música não têm exemplos de treino e dependem do veto do YAMNet.

## 2. Diagnóstico (3 classes)

C escolhido: 1.0. **Acurácia no teste: 80.7%** · F1-macro: 0.819.

| classe | precisão | revocação | F1 | trechos |
|---|---:|---:|---:|---:|
| normal | 0.71 | 0.87 | 0.78 | 52 |
| falha_batida_pino | 0.91 | 0.73 | 0.81 | 82 |
| falha_ignicao | 0.76 | 1.00 | 0.86 | 16 |

Matriz de confusão (trechos de teste):

| real \ previsto | normal | falha_batida_pino | falha_ignicao |
|---|---|---|---|
| **normal** | 45 | 6 | 1 |
| **falha_batida_pino** | 18 | 60 | 4 |
| **falha_ignicao** | 0 | 0 | 16 |

Acerto por classe e fonte (teste):

| classe | fonte | trechos | acerto |
|---|---|---:|---:|
| falha_batida_pino | kwerimoto | 82 | 73% |
| falha_ignicao | kwerimoto | 16 | 100% |
| normal | kwerimoto | 52 | 87% |

### Normal × falha (o que aciona o alerta)

Precisão 92.0% · revocação 81.6% · F1 0.865.

### Simulação do botão DIAGNOSTICAR (grupos de ~5 s = 10 quadros)

Acurácia em 150 grupos de teste: **78.7%**.

| classe | precisão | revocação | F1 | trechos |
|---|---:|---:|---:|---:|
| normal | 0.68 | 0.88 | 0.77 | 52 |
| falha_batida_pino | 0.92 | 0.68 | 0.78 | 82 |
| falha_ignicao | 0.76 | 1.00 | 0.86 | 16 |

### Limiar de confiança ("inconclusivo")

Curva no teste (grupos de 5 s):

| limiar | trechos respondidos | acurácia nos respondidos |
|---:|---:|---:|
| 40% | 100% | 78.7% |
| 50% | 97% | 78.6% |
| 60% | 79% | 85.7% |
| 70% | 58% | 94.3% |
| 80% | 37% | 94.6% |
| 90% | 14% | 95.2% |

Limiar escolhido **na validação**: **60%** (menor limiar com ≥ 90% de acerto respondendo ≥ 60% dos grupos). No teste ele responde 79% dos diagnósticos com 85.7% de acerto; o resto vira "inconclusivo" (o sistema não finge certeza). O serviço permite ajustar o limiar.

### Robustez: teste com áudio degradado (simula celular + MAX9814 + ADC de 12 bits)

Trechos de teste filtrados em 250–5000 Hz, ruído com SNR de 12 dB, saturação leve e quantização de 12 bits (degradação mais forte e diferente da usada no aumento de dados do treino), em pedaços de 5 s.

- acurácia: **71.9%** em 185 pedaços (sem degradação: 78.7%)
- com o limiar de 60%: responde 63% com 78.4% de acerto
- porteiro reconhece como carro: 84.3%

| real \ previsto | normal | falha_batida_pino | falha_ignicao |
|---|---|---|---|
| **normal** | 49 | 8 | 4 |
| **falha_batida_pino** | 29 | 75 | 4 |
| **falha_ignicao** | 4 | 3 | 9 |

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

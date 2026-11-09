# Datasets de áudio (inventário)

Os áudios ficam em `data/raw/<fonte>/` e **não são versionados** (`data/` está no `.gitignore`). Cada integrante baixa na própria máquina.

## 1. kwerimoto — `data/raw/kwerimoto/`

- Origem: Hugging Face `rayyyyy007/kwerimoto-engine-sounds` (`git clone` com LFS, 08/11/2026).
- Licença: "pesquisa e educação"; o áudio pertence aos donos originais (YouTube/AudioSet, Revix). Uso no TDE é compatível.
- Formato: WAV **mono, 16 kHz, 16 bits**, clipes de até 10 s. Já está no formato do YAMNet.
- Áudios: `prepared/<split>/<classe>/*.wav`. O `manifest.csv` traz `label`, `split`, `group` (gravação/vídeo de origem), `source_dataset` e `synthetic`.

| Classe | train | validation | test | real_test | Total |
|---|---:|---:|---:|---:|---:|
| `healthy` | 246 (34,3 min) | 52 (7,2 min) | 53 (7,3 min) | — | 351 |
| `engine_knock` | 399 (57,6 min) | 86 (12,3 min) | 85 (12,0 min) | 38 (6,3 min) | 608 |
| `misfire` | 76 (8,8 min) | 16 (1,9 min) | 16 (1,9 min) | — | 108 |

Observações:
- O split do autor já separa por gravação (`group`): nenhum vídeo aparece em dois splits. Podemos reutilizá-lo para não vazar dados.
- 286 clipes de `engine_knock` e 271 de `healthy` são **sintéticos** (Revix). O `real_test` só tem knock real e serve para medir se o modelo reconhece knock de verdade.
- `misfire` é a classe mais fraca (108 clipes, ~13 min).

## 2. amrrashed — `data/raw/amrrashed/`

- Origem: GitHub `amrrashed/Sound-Based-Vehicle-Diagnostics-Emergency-Signal-Recognition` (commit `aa03be4`, 08/11/2026).
- **Problema no download:** o repositório tem 52 arquivos chamados literalmente `...` (1 byte cada, marcadores sem áudio). Esse nome é inválido no Windows e aborta o `git checkout`. Os arquivos foram extraídos com `git archive` + extrator Python que **pula só esses 52**. Todos os outros 1079 arquivos estão presentes. A pasta não é um repositório git.
- Licença: não declarada; o README diz que o material foi montado de datasets públicos e vídeos do YouTube.

### ⚠ Os WAVs segmentados estão corrompidos

Os arquivos de `Datasetver2/*_segmented_audio/` (inclusive os extraídos dos `.zip`) têm cabeçalho WAV válido, mas o conteúdo é **ruído branco em escala cheia**: autocorrelação de passo 1 ≈ 0,00 e pico 1,0, enquanto áudio real fica entre 0,8 e 0,97. A única exceção é "Emergency Vehicles". O problema foi descoberto porque o YAMNet classificava gravações de gato como "chuva/spray". **Não usamos esses arquivos.** O `prepare_dataset.py` descarta automaticamente qualquer trecho com esse padrão.

### O que usamos (gravações originais)

| Pasta | Conteúdo | Uso |
|---|---|---|
| `Datasets/DB1/<falha>/*.m4a` | 30 gravações originais de falhas (≈ 3,8 min; várias de 1–2 s) | `Engine Misfire` → `falha_ignicao`; demais → `falha_outros` (só para o porteiro "é carro") |
| `Datasets/DB2/<classe>/*` | Originais de animais, sirenes, tiros, furadeira (≈ 14 min, 66 gravações) | `nao_carro` |
| `Datasets/DB2/{bike,bus,motorcycle,train,truck,car horn,truck horn,car crashes}` | Veículos que não são carro | **Ignorados** (ambíguos para o porteiro) |
| `codes/` | Scripts Python do autor | **Não executados** |

Os `.m4a` são lidos com o ffmpeg empacotado no `imageio-ffmpeg` (só na preparação).

**Atenção:** é pouco áudio de falhas mecânicas, e muito variado. Por isso `falha_outros` não virou classe de diagnóstico (ver `docs/DECISOES.md`).

## 3. Kaggle (baixados manualmente pela equipe)

- `data/raw/ai_mechanic/`: pendente.
- `data/raw/car_diagnostics/`: pendente.

Basta extrair cada dataset na sua pasta e rodar `prepare_dataset.py`. Sem regra explícita em `src/ai/fontes.json`, as pastas são mapeadas por **palavras-chave** (`normal`/`healthy` → `normal`, `knock` → `falha_batida_pino`, `misfire` → `falha_ignicao`, etc.). O relatório lista o que foi usado, ignorado e descartado por corrupção: **confira antes de treinar**. Para promover uma nova falha a classe de diagnóstico, adicione-a em `classes_diagnostico` (e em `src/ai/diagnosticos.json`) e retreine.

## 4. Gravações da equipe — `data/own/<classe>/`

Geradas por `python src/ai/record.py --classe <classe> --segundos 60`. Cada arquivo é uma gravação (um grupo) e entra automaticamente no próximo `prepare_dataset.py`.

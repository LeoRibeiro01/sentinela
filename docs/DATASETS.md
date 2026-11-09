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

Onde está cada coisa:

| Pasta | Conteúdo | Formato |
|---|---|---|
| `Datasets/DB1/<falha>/` | **Falhas veiculares, originais**: 27 pastas, quase todas com **1 gravação** cada (31 no total) | `.m4a` (precisa de ffmpeg) |
| `Datasetver2/DB1__segmented_audio/<categoria>/` | **As mesmas falhas, segmentadas** em clipes de ~2,5 s (175 clipes; extraídos de `DB1.zip`, que continua lá) | WAV 16 kHz, a maioria **estéreo** |
| `Datasets/DB2/<classe>/` | Sons de estrada/animais/sirenes, originais (22 classes, 2–8 arquivos cada) | `.m4a`/`.mp3` |
| `Datasetver2/DB2_segmented_audio/` | `animals` (650), `Vehicles and transportation` (246), `Emergency Vehicles` (11) segmentados; mais 3 `.zip` não extraídos (construção, armas, clima) | WAV |
| `codes/` | Scripts Python do autor. **Não executamos.** | `.py` |

Classes de falha segmentadas (`Datasetver2/DB1__segmented_audio/`):

| Categoria | Clipes | Duração | Gravações de origem |
|---|---:|---:|---:|
| ENGINE AND POWERTRAIN ISSUES | 61 | 152 s | 14 |
| SUSPENSION AND STEERING ISSUES | 39 | 98 s | 8 |
| General Vehicle Sounds (34 clipes "car normal noise" + 4 "videoplayback" de conteúdo não verificado) | 38 | 95 s | 3 |
| EXHAUST AND FUEL SYSTEM ISSUE | 16 | 40 s | 4 |
| Belt and Accessory Issues | 12 | 30 s | 3 |
| Miscellaneous Issues | 5 | 12 s | 1 |
| Braking System Issues | 4 | 10 s | 1 |

**Atenção:** é pouco áudio (≈ 7 min no total) e de poucas gravações. Cada categoria mistura falhas diferentes (ex.: "Engine and Powertrain" contém rolamento de roda, transmissão, biela...). Os segmentos de uma mesma gravação **precisam ficar todos no treino ou todos na validação** (o nome antes de `_segment_N` identifica a gravação). Serve como reforço ou para o modo demonstração, mas não sustenta sozinho um classificador por categoria.

## 3. Kaggle (baixados manualmente pela equipe)

- `data/raw/ai_mechanic/`: pendente.
- `data/raw/car_diagnostics/`: pendente.

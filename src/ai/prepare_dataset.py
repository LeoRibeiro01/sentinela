"""prepare_dataset.py — Converte os datasets brutos num conjunto de treino uniforme.

Entrada:  data/raw/<fonte>/...  e  data/own/<classe>/*.wav  (gravações da equipe)
Saída:    data/train/<classe>/*.wav  (16 kHz, mono, PCM16, normalizado, ≤ 10 s)
          data/train/manifest.csv     (arquivo, classe, grupo, fonte, split)

Regras de cada fonte: src/ai/fontes.json. Fontes desconhecidas (ex.: Kaggle)
são mapeadas por palavras-chave no caminho; o relatório mostra o que foi
usado e o que foi ignorado, para conferência.

Por que "grupo"? Vários trechos saem da MESMA gravação. Se um fica no treino e
outro na validação, a métrica fica otimista (vazamento). Por isso a divisão
treino/validação/teste é feita por grupo (gravação), nunca por trecho.
As janelas de 0,96 s com 50% de sobreposição são geradas pelo próprio YAMNet
no treino (train.py); aqui guardamos trechos de até 10 s.

Proteções: trechos que parecem ruído branco em escala cheia (arquivo
corrompido) são descartados e contados no relatório. Também gera ruído
sintético (branco/rosa/marrom/zumbido) como "nao_carro".

Uso:  python src/ai/prepare_dataset.py
"""
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_util import TAXA, carregar, normalizar, parece_corrompido, rms, salvar_wav  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
PASTA_RAW = RAIZ / "data" / "raw"
PASTA_OWN = RAIZ / "data" / "own"
PASTA_SAIDA = RAIZ / "data" / "train"
EXTENSOES = {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}
TRECHO_MAX_S = 10
TRECHO_MIN_S = 0.5
SEMENTE = 42


def grupo_padrao(fonte, caminho_relativo):
    """Gravação de origem: tira sufixos de segmentação como '_segment_3'."""
    stem = re.sub(r"_segment_\d+$", "", Path(caminho_relativo).stem)
    return f"{fonte}:{Path(caminho_relativo).parent.as_posix()}/{stem}"


def classe_por_palavra(caminho, palavras):
    texto = caminho.lower().replace("-", "_")
    for classe, lista in palavras.items():
        if not classe.startswith("_") and any(p in texto for p in lista):
            return classe
    return None


def listar_itens(config):
    """Gera (arquivo, classe, grupo, fonte, split_fixo) para todas as fontes."""
    itens, ignorados = [], Counter()
    fontes_cfg = config["fontes"]
    pastas = sorted(p for p in PASTA_RAW.iterdir() if p.is_dir()) if PASTA_RAW.exists() else []
    if PASTA_OWN.exists():
        pastas.append(PASTA_OWN)
    for pasta in pastas:
        fonte = "own" if pasta == PASTA_OWN else pasta.name
        if fonte in config.get("fontes_desativadas", {}):
            continue  # testada e reprovada: não entra no treino (ver fontes.json)
        cfg = fontes_cfg.get(fonte, {"tipo": "palavras"})
        if cfg["tipo"] == "manifesto_kwerimoto":
            with open(pasta / "manifest.csv", encoding="utf-8") as f:
                for linha in csv.DictReader(f):
                    classe = cfg["rotulos"].get(linha["label"])
                    if classe:
                        itens.append((pasta / linha["file_name"], classe, f"kwerimoto:{linha['group']}",
                                      fonte, linha["split"]))
            continue
        if cfg["tipo"] == "esc50":
            # ESC-50: meta/esc50.csv diz a categoria; src_file é o clipe original (= grupo).
            with open(pasta / "meta" / "esc50.csv", encoding="utf-8") as f:
                for linha in csv.DictReader(f):
                    if linha["category"] not in cfg["excluir"]:
                        itens.append((pasta / "audio" / linha["filename"], config["classe_nao_carro"],
                                      f"esc50:{linha['src_file']}", fonte, ""))
            continue
        if cfg["tipo"] == "regras":
            vistos = set()  # a primeira regra que pega um arquivo vence
            for regra in cfg["regras"]:
                for arq in sorted(pasta.glob(regra["glob"])):
                    if arq in vistos or not arq.is_file() or arq.suffix.lower() not in EXTENSOES:
                        continue
                    vistos.add(arq)
                    rel = arq.relative_to(pasta).as_posix()
                    itens.append((arq, regra["classe"], grupo_padrao(fonte, rel), fonte, ""))
            continue
        for arq in sorted(pasta.rglob("*")):
            if not arq.is_file() or arq.suffix.lower() not in EXTENSOES:
                continue
            rel = arq.relative_to(pasta).as_posix()
            if cfg["tipo"] == "pastas":
                classe = Path(rel).parts[0]
                grupo = f"own:{rel}"  # cada gravação da equipe é um grupo
            else:
                classe = classe_por_palavra(rel, config["palavras_chave"])
                grupo = grupo_padrao(fonte, rel)
            if classe is None:
                ignorados[f"{fonte}: {Path(rel).parent.as_posix() or '.'} (sem palavra-chave)"] += 1
                continue
            itens.append((arq, classe, grupo, fonte, ""))
    return itens, ignorados


def gerar_ruido(tipo, segundos, rng):
    """Ruído sintético: branco (plano), rosa (1/f), marrom (1/f²) ou zumbido de rede."""
    n = int(segundos * TAXA)
    if tipo == "zumbido_60hz":
        t = np.arange(n) / TAXA
        sinal = sum(np.sin(2 * np.pi * 60 * k * t) / k for k in (1, 2, 3, 5))
        return (sinal + rng.normal(0, 0.05, n)).astype(np.float32)
    espectro = np.fft.rfft(rng.normal(0, 1, n))
    f = np.maximum(np.fft.rfftfreq(n, 1 / TAXA), 1.0)
    expoente = {"branco": 0.0, "rosa": 0.5, "marrom": 1.0}[tipo]
    return np.fft.irfft(espectro / f ** expoente, n).astype(np.float32)


def itens_sinteticos(config):
    cfg = config.get("ruido_sintetico")
    if not cfg:
        return []
    return [(f"sintetico:{tipo}:{i}", config["classe_nao_carro"], f"sintetico:{tipo}:{i}", "sintetico", "")
            for tipo in cfg["tipos"] for i in range(cfg["clipes_por_tipo"])]


def sortear_splits(itens):
    """Divide os GRUPOS de cada (fonte, classe) em ~70/15/15 de forma reprodutível."""
    grupos = defaultdict(set)
    for _, classe, grupo, fonte, split in itens:
        if not split:
            grupos[(fonte, classe)].add(grupo)
    destino = {}
    rng = np.random.default_rng(SEMENTE)
    for chave in sorted(grupos):
        lista = sorted(grupos[chave])
        rng.shuffle(lista)
        n = len(lista)
        n_val = max(1, round(n * 0.15)) if n >= 3 else 0
        n_teste = max(1, round(n * 0.15)) if n >= 3 else (1 if n == 2 else 0)
        for i, g in enumerate(lista):
            destino[g] = "test" if i < n_teste else "validation" if i < n_teste + n_val else "train"
    return [(a, c, g, f, s or destino[g]) for a, c, g, f, s in itens]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = json.loads((Path(__file__).parent / "fontes.json").read_text(encoding="utf-8"))
    validas = (set(config["classes_diagnostico"]) | set(config.get("classes_somente_porteiro", []))
               | {config["classe_nao_carro"]})
    itens, ignorados = listar_itens(config)
    itens += itens_sinteticos(config)
    for classe, n in Counter(c for _, c, *_ in itens if c not in validas).items():
        ignorados[f"classe desconhecida '{classe}' (veja fontes.json)"] += n
    itens = sortear_splits([i for i in itens if i[1] in validas])
    if not itens:
        sys.exit("ERRO: nenhum áudio encontrado em data/raw/ ou data/own/.")

    if PASTA_SAIDA.exists():
        shutil.rmtree(PASTA_SAIDA)  # recria do zero: o resultado depende só de data/raw + fontes.json
    rng = np.random.default_rng(SEMENTE)
    linhas, falhas, corrompidos = [], Counter(), Counter()
    for n, (arq, classe, grupo, fonte, split) in enumerate(itens, 1):
        try:
            if fonte == "sintetico":
                sinal = gerar_ruido(grupo.split(":")[1], config["ruido_sintetico"]["segundos"], rng)
            else:
                sinal = carregar(arq)
        except Exception as e:  # arquivo corrompido ou formato não suportado
            falhas[f"{fonte}: {type(e).__name__}"] += 1
            continue
        passo = TRECHO_MAX_S * TAXA
        for parte, inicio in enumerate(range(0, max(1, len(sinal)), passo)):
            trecho = sinal[inicio:inicio + passo]
            if len(trecho) < TRECHO_MIN_S * TAXA or rms(trecho) < 1e-4:  # muito curto ou silêncio digital
                continue
            if fonte != "sintetico" and parece_corrompido(trecho):
                corrompidos[f"{fonte}: {Path(str(arq)).parent.name}"] += 1
                continue
            nome = hashlib.sha1(f"{arq}|{parte}".encode()).hexdigest()[:12]
            destino = PASTA_SAIDA / classe / f"{fonte}_{nome}.wav"
            destino.parent.mkdir(parents=True, exist_ok=True)
            salvar_wav(destino, normalizar(trecho))
            linhas.append([destino.relative_to(PASTA_SAIDA).as_posix(), classe, grupo, fonte, split,
                           round(len(trecho) / TAXA, 2)])
        if n % 200 == 0:
            print(f"  {n}/{len(itens)} arquivos processados...")

    with open(PASTA_SAIDA / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arquivo", "classe", "grupo", "fonte", "split", "duracao_s"])
        w.writerows(linhas)

    print("\nResumo (trechos / minutos / grupos por split):")
    resumo = defaultdict(lambda: [0, 0.0, set()])
    for _, classe, grupo, fonte, split, dur in linhas:
        r = resumo[(classe, split)]
        r[0] += 1
        r[1] += dur
        r[2].add(grupo)
    for (classe, split), (n, dur, grupos) in sorted(resumo.items()):
        print(f"  {classe:18s} {split:11s} {n:5d} trechos {dur / 60:6.1f} min {len(grupos):4d} grupos")
    print("\nPor fonte:", dict(Counter(l[3] for l in linhas)))
    if corrompidos:
        print("\nDescartados por parecerem CORROMPIDOS (ruído branco em escala cheia):")
        for motivo, n in corrompidos.most_common():
            print(f"  {n:5d}  {motivo}")
    if ignorados:
        print("\nIgnorados (confira se está correto):")
        for motivo, n in ignorados.most_common():
            print(f"  {n:5d}  {motivo}")
    if falhas:
        print("\nArquivos que não puderam ser lidos:", dict(falhas))
    print(f"\nPronto: {len(linhas)} trechos em {PASTA_SAIDA}")


if __name__ == "__main__":
    main()

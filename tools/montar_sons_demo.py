"""montar_sons_demo.py — Monta um "kit" de sons para a demonstração ao vivo.

Escolhe, entre os trechos de TESTE (nunca usados no treino), alguns de cada classe
que o pipeline completo (porteiro + diagnóstico, igual ao server.py) acerta com
folga, e salva em data/demo_sons/<classe>/. Na apresentação, toque esses arquivos
no celular ou no alto-falante do notebook perto do microfone.

Atenção à honestidade: os sons são escolhidos porque o modelo os acerta. Diga isso
na apresentação ("exemplos do conjunto de teste"). As métricas reais estão em
docs/metricas_ia.md.

Uso:  python tools/montar_sons_demo.py [--por-classe 4]
"""
import argparse
import csv
import shutil
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src" / "ai"))
from analise import Analisador  # noqa: E402
from audio_util import carregar, salvar_wav  # noqa: E402
from yamnet_util import Yamnet  # noqa: E402

PASTA_TREINO = RAIZ / "data" / "train"
DESTINO = RAIZ / "data" / "demo_sons"


def acerta(analisador, trecho, classe):
    """True se o pipeline acerta este trecho de 5 s com folga (confiança ≥ 65%)."""
    r = analisador.analisar(trecho, limiar_silencio=0.0)
    if classe == "nao_carro":
        return r["status"] == "nao_carro"
    return (r["status"] == "ok" and analisador.classes[int(np.argmax(r["probs"]))] == classe
            and float(np.max(r["probs"])) >= 0.65)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--por-classe", type=int, default=4)
    a = p.parse_args()

    analisador = Analisador(Yamnet())
    if analisador.modelo is None:
        sys.exit("ERRO: treine o modelo antes (src/ai/train.py).")
    with open(PASTA_TREINO / "manifest.csv", encoding="utf-8") as f:
        linhas = [l for l in csv.DictReader(f) if l["split"] == "test"]
    if DESTINO.exists():
        shutil.rmtree(DESTINO)

    alvo = analisador.classes + ["nao_carro"]
    escolhidos = {c: [] for c in alvo}
    rng = np.random.default_rng(1)
    rng.shuffle(linhas)
    for linha in linhas:
        classe = linha["classe"]
        if classe not in escolhidos or len(escolhidos[classe]) >= a.por_classe:
            continue
        sinal = carregar(PASTA_TREINO / linha["arquivo"])[:5 * 16000]  # 5 s, como o botão
        if len(sinal) < 3 * 16000:
            continue
        # Sem pausas: cada segundo precisa ter som (senão a IA ao vivo mostra "silêncio" no meio).
        if min(float(np.sqrt(np.mean(sinal[i:i + 16000] ** 2))) for i in range(0, len(sinal) - 15999, 16000)) < 0.03:
            continue
        # Repete o trecho até 15 s: dá tempo de apertar DIAGNOSTICAR com o som tocando.
        final = np.tile(sinal, int(np.ceil(15 * 16000 / len(sinal))))[:15 * 16000]
        # Só entra no kit se acertar em QUALQUER janela de 5 s (testadas a cada 2,5 s),
        # porque ninguém sabe em que ponto do áudio o botão vai ser apertado.
        if all(acerta(analisador, final[i:i + 5 * 16000], classe) for i in range(0, 10 * 16000 + 1, 40000)):
            destino = DESTINO / classe / f"{classe}_{len(escolhidos[classe]) + 1}.wav"
            destino.parent.mkdir(parents=True, exist_ok=True)
            salvar_wav(destino, final)
            escolhidos[classe].append(linha["arquivo"])
    for classe, lista in escolhidos.items():
        print(f"  {classe:18s} {len(lista)} arquivo(s)")
    print(f"Kit salvo em {DESTINO}")


if __name__ == "__main__":
    main()

"""analise.py — Analisa UM trecho de áudio (~1 s) e decide o que ele é.

Ordem das perguntas (cada uma pode encerrar a análise):
  1. Tem som?          RMS bruto abaixo do limiar  -> "sinal_fraco"
  2. É carro?          porteiro treinado (carro × nao_carro) + veto do YAMNet
                       para fala/música (que não existem nos nossos negativos)
                                                     -> "nao_carro"
  3. Qual o estado?    classificador de diagnóstico  -> "ok" com probabilidades
Sem modelo treinado, a etapa 2 usa só o YAMNet e a 3 não acontece ("sem_modelo").
"""
from pathlib import Path

import joblib
import numpy as np

from audio_util import normalizar, rms

CAMINHO_MODELO = Path(__file__).resolve().parents[2] / "models" / "classificador.joblib"
LIMIAR_PORTEIRO = 0.5  # probabilidade mínima de "carro"
LIMIAR_VETO = 0.5      # fala/música/animal acima disso...
LIMIAR_VEICULO_VETO = 0.2  # ...e pouco som de veículo (< 0,2) = não é carro


def veto_yamnet(resumo):
    """True se o YAMNet ouve claramente fala/música/animal/clima e quase nada de veículo.

    Exigir pouco veículo evita vetar motor com alguém falando por cima.
    """
    return resumo["nao_carro"] >= LIMIAR_VETO and resumo["veiculo"] < LIMIAR_VEICULO_VETO


class Analisador:
    def __init__(self, yamnet, caminho_modelo=CAMINHO_MODELO):
        self.yamnet = yamnet
        self.modelo = joblib.load(caminho_modelo) if Path(caminho_modelo).exists() else None
        self.classes = self.modelo["classes"] if self.modelo else []

    @property
    def limiar_confianca(self):
        return self.modelo["limiar_confianca"] if self.modelo else 60

    def analisar(self, sinal, limiar_silencio, demo=False):
        """Devolve um dicionário com status, probabilidades e o som que o YAMNet ouviu."""
        r = {"rms_bruto": round(rms(sinal), 5), "status": "sinal_fraco", "carro_prob": 0.0,
             "probs": None, "som": "", "easter": None, "veto": False}
        if r["rms_bruto"] < limiar_silencio:
            return r

        scores, emb = self.yamnet.analisar(normalizar(sinal))
        resumo = self.yamnet.resumo(scores)
        r["som"] = resumo["top_pt"]
        if demo:
            r["easter"] = self.yamnet.easter_egg(scores)

        if self.modelo:
            r["carro_prob"] = float(self.modelo["porteiro"].predict_proba(emb).mean(axis=0)[0])
        else:  # sem porteiro treinado: usa a soma das classes de veículo do YAMNet
            r["carro_prob"] = min(1.0, resumo["veiculo"] * 3)
        r["veto"] = veto_yamnet(resumo)
        if r["veto"]:
            r["som"] = resumo["nao_carro_nome"] or r["som"]
        if r["carro_prob"] < LIMIAR_PORTEIRO or r["veto"]:
            r["status"] = "nao_carro"
            return r

        if not self.modelo:
            r["status"] = "sem_modelo"
            return r
        r["probs"] = self.modelo["diagnostico"].predict_proba(emb).mean(axis=0)
        r["status"] = "ok"
        return r

    def ranking(self, probs, nomes):
        """Lista ordenada [{classe, nome, prob%}] a partir do vetor de probabilidades."""
        ordem = np.argsort(probs)[::-1]
        return [{"classe": self.classes[i], "nome": nomes.get(self.classes[i], self.classes[i]),
                 "prob": int(round(float(probs[i]) * 100))} for i in ordem]

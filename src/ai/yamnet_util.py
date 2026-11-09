"""yamnet_util.py — Carrega o YAMNet do disco e extrai o que o projeto usa dele.

O YAMNet (Google, treinado no AudioSet) recebe áudio 16 kHz mono e divide em
quadros de 0,96 s com passo de 0,48 s (50% de sobreposição). Para cada quadro
devolve:
  - scores: probabilidade de 521 classes de som (fala, cachorro, motor...);
  - embedding: 1024 números que resumem o som. Nosso classificador usa isso.
Nada aqui acessa a internet: o modelo vem de models/yamnet/ (tools/baixar_yamnet.py).
"""
import csv
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")  # esconde avisos técnicos do TensorFlow
import tensorflow as tf  # noqa: E402  (precisa vir depois da variável acima)

PASTA_YAMNET = Path(__file__).resolve().parents[2] / "models" / "yamnet"
AMOSTRAS_QUADRO = 15360  # 0,96 s a 16 kHz
PASSO_QUADRO = 7680      # 0,48 s

# Classes do AudioSet que indicam veículo/motor (usadas como "segunda opinião").
NOMES_VEICULO = [
    "Vehicle", "Motor vehicle (road)", "Car", "Car passing by", "Race car, auto racing", "Truck", "Bus",
    "Engine", "Light engine (high frequency)", "Medium engine (mid frequency)", "Heavy engine (low frequency)",
    "Engine knocking", "Engine starting", "Idling", "Accelerating, revving, vroom",
]
# Sons claramente "não carro" usados como veto. O YAMNet reconhece bem essas categorias,
# e nossos negativos treinados não cobrem fala nem música.
NOMES_NAO_CARRO = ["Speech", "Music", "Singing", "Laughter", "Clapping", "Whistling", "Animal",
                   "Rain", "Wind", "Thunderstorm", "Gunshot, gunfire", "Explosion", "Siren"]
# Easter eggs do modo demo: nome no YAMNet -> nome exibido.
EASTER_EGGS = {
    "Cat": "Gato", "Meow": "Gato", "Purr": "Gato", "Dog": "Cachorro", "Bark": "Cachorro",
    "Bird": "Pássaro", "Chirp, tweet": "Pássaro", "Crow": "Corvo", "Owl": "Coruja", "Duck": "Pato",
    "Rooster, cock": "Galo", "Chicken, rooster": "Galinha", "Cattle, bovinae": "Vaca", "Moo": "Vaca",
    "Pig": "Porco", "Oink": "Porco", "Sheep": "Ovelha", "Bleat": "Ovelha", "Horse": "Cavalo",
    "Frog": "Sapo", "Cricket": "Grilo", "Insect": "Inseto",
}
# Tradução dos sons mais prováveis numa sala de apresentação (para a mensagem "não é carro").
TRADUCOES = {
    "Speech": "fala", "Music": "música", "Silence": "silêncio", "Clapping": "palmas", "Laughter": "risadas",
    "Singing": "canto", "Whistling": "assobio", "Inside, small room": "ambiente fechado", "Typing": "digitação",
    "Computer keyboard": "teclado", "Noise": "ruído", "White noise": "ruído branco", "Hum": "zumbido",
    "Mechanical fan": "ventilador", "Rain": "chuva", "Wind": "vento", "Siren": "sirene", "Gunshot, gunfire": "tiro", "Explosion": "explosão", "Thunderstorm": "tempestade", "Air conditioning": "ar-condicionado", "Animal": "animal", "Vehicle": "veículo", "Engine": "motor", "Car": "carro",
    "Motor vehicle (road)": "veículo", "Idling": "marcha lenta", "Tuning fork": "diapasão", "Sine wave": "tom puro",
    "Cat": "gato", "Dog": "cachorro", "Bird": "pássaro", "Domestic animals, pets": "animal doméstico",
}


class Yamnet:
    """Envolve o modelo: carrega uma vez e responde (scores, embeddings) por trecho."""

    def __init__(self, pasta=PASTA_YAMNET):
        if not (Path(pasta) / "saved_model.pb").exists():
            raise FileNotFoundError(f"YAMNet não encontrado em {pasta}. Rode: python tools/baixar_yamnet.py")
        self.modelo = tf.saved_model.load(str(pasta))
        with open(Path(pasta) / "assets" / "yamnet_class_map.csv", encoding="utf-8") as f:
            self.nomes = [linha["display_name"] for linha in csv.DictReader(f)]
        indice = {nome: i for i, nome in enumerate(self.nomes)}
        self.idx_veiculo = [indice[n] for n in NOMES_VEICULO if n in indice]
        self.idx_nao_carro = [indice[n] for n in NOMES_NAO_CARRO if n in indice]
        self.easter = {indice[n]: pt for n, pt in EASTER_EGGS.items() if n in indice}

    def analisar(self, sinal):
        """sinal: float32 mono 16 kHz. Devolve (scores [quadros×521], embeddings [quadros×1024]).

        Só devolve quadros CHEIOS. O YAMNet completa o fim do áudio com zeros e cria
        um quadro parcial (1 s de áudio vira 2 quadros, o 2º metade vazio). Esse
        quadro "meio silêncio" quase não aparece no treino e confundia o modelo ao vivo.
        """
        scores, embeddings, _ = self.modelo(np.asarray(sinal, dtype=np.float32))
        cheios = max(1, 1 + (len(sinal) - AMOSTRAS_QUADRO) // PASSO_QUADRO)
        return scores.numpy()[:cheios], embeddings.numpy()[:cheios]

    def resumo(self, scores):
        """Resume os scores de um trecho: som mais provável, chance de veículo e de 'não carro'."""
        return self.resumo_da_media(scores.mean(axis=0))

    def resumo_da_media(self, media):
        """Igual a resumo(), a partir da média dos scores (usado também nas métricas do treino)."""
        top = int(np.argmax(media))
        return {
            "top_nome": self.nomes[top],
            "top_pt": TRADUCOES.get(self.nomes[top], self.nomes[top]),
            "top_prob": float(media[top]),
            "veiculo": float(min(1.0, media[self.idx_veiculo].sum())),
            "nao_carro": float(media[self.idx_nao_carro].max()),
            "nao_carro_nome": TRADUCOES.get(self.nomes[self.idx_nao_carro[int(np.argmax(media[self.idx_nao_carro]))]], ""),
        }

    def easter_egg(self, scores, limiar=0.25):
        """Animal mais provável do trecho, se passar do limiar (modo demo)."""
        media = scores.mean(axis=0)
        melhor = max(self.easter, key=lambda i: media[i])
        return (self.easter[melhor], float(media[melhor])) if media[melhor] >= limiar else None

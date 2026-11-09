"""baixar_yamnet.py — Baixa o modelo YAMNet uma vez e o guarda em models/yamnet/.

O YAMNet (Google) é uma rede pré-treinada que recebe áudio mono 16 kHz e devolve
(a) a probabilidade de 521 classes de som (AudioSet) e (b) um "embedding" de
1024 números por janela de 0,96 s. Usamos o embedding para treinar o nosso
classificador e as 521 classes para os easter eggs (gato, cachorro...).

Na apresentação não há internet, então o modelo precisa estar no disco.
Uso (com o venv ativo):
    python tools/baixar_yamnet.py             # baixa (se faltar) e verifica
    python tools/baixar_yamnet.py --verificar # só verifica a carga offline
"""
import argparse
import io
import os
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # acentos no console do Windows
RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "models" / "yamnet"
# O tfhub.dev redireciona para o Kaggle Models; o segundo endereço é o destino direto.
URLS = [
    "https://tfhub.dev/google/yamnet/1?tf-hub-format=compressed",
    "https://www.kaggle.com/api/v1/models/google/yamnet/tensorFlow2/yamnet/1/download",
]


def baixar():
    """Baixa o .tar.gz do SavedModel e extrai em models/yamnet/."""
    for url in URLS:
        try:
            print(f"Baixando {url} ...")
            with urllib.request.urlopen(url, timeout=120) as r:
                dados = r.read()
            print(f"  {len(dados) / 1e6:.1f} MB recebidos")
            DESTINO.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
                tar.extractall(DESTINO, filter="data")  # filtro impede caminhos fora da pasta
            return
        except Exception as e:  # tenta o próximo endereço
            print(f"  falhou: {e}")
    sys.exit("ERRO: não foi possível baixar o YAMNet de nenhum endereço.")


def verificar():
    """Carrega o modelo do disco, roda 1 s de áudio e confere as saídas."""
    import numpy as np
    import tensorflow as tf

    modelo = tf.saved_model.load(str(DESTINO))
    t = np.arange(16000) / 16000
    audio = (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)  # 1 s de tom de 440 Hz
    scores, embeddings, _ = modelo(audio)
    mapa = DESTINO / "assets" / "yamnet_class_map.csv"
    nomes = [linha.split(",", 2)[2].strip().strip('"') for linha in mapa.read_text(encoding="utf-8").splitlines()[1:]]
    top = int(np.argmax(scores.numpy().mean(axis=0)))
    print(f"scores {tuple(scores.shape)}, embeddings {tuple(embeddings.shape)}, {len(nomes)} classes")
    print(f"classe mais provável para um tom de 440 Hz: {nomes[top]}")
    ok = scores.shape[1] == 521 and embeddings.shape[1] == 1024 and len(nomes) == 521
    print("YAMNet OK (carregado do disco)" if ok else "ERRO: formato inesperado")
    return ok


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verificar", action="store_true", help="só verifica, sem baixar")
    p.add_argument("--interno", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args()

    if a.interno:  # processo filho sem rede: apenas carrega e testa
        import socket

        def sem_rede(*_args, **_kwargs):
            raise OSError("rede bloqueada pelo teste offline")

        socket.socket.connect = sem_rede  # qualquer conexão feita pelo Python falha
        socket.create_connection = sem_rede
        sys.exit(0 if verificar() else 1)

    if not a.verificar and not (DESTINO / "saved_model.pb").exists():
        baixar()
    if not (DESTINO / "saved_model.pb").exists():
        sys.exit("ERRO: models/yamnet/saved_model.pb não existe. Rode sem --verificar.")

    # Prova de que roda offline: um processo filho em que as conexões do Python dão erro
    # e o proxy aponta para uma porta morta. Se algo tentasse usar a internet, falharia.
    print("Verificando a carga offline (rede bloqueada no processo de teste)...")
    env = dict(os.environ, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
               TFHUB_CACHE_DIR=str(RAIZ / "models" / "_sem_cache"))
    resultado = subprocess.run([sys.executable, __file__, "--interno"], env=env)
    sys.exit(resultado.returncode)


if __name__ == "__main__":
    main()

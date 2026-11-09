"""record.py — Grava áudio rotulado do ESP32 para treinar/ajustar o modelo.

Baixa 1 s de /audio.wav a cada segundo e junta tudo num WAV em
data/own/<classe>/<classe>_<data-hora>.wav. Depois, prepare_dataset.py e
train.py incluem essas gravações automaticamente (cada arquivo é um "grupo",
então treino e validação nunca compartilham a mesma gravação).

Exemplos (notebook conectado ao Wi-Fi SENTINELA):
  python src/ai/record.py --classe normal --segundos 60
  python src/ai/record.py --classe falha_batida_pino --segundos 60   # tocando o som no celular
  python src/ai/record.py --classe nao_carro --segundos 60           # fala, palmas, ambiente da sala
Classes válidas: as de src/ai/fontes.json (normal, falha_batida_pino, falha_ignicao, falha_outros, nao_carro).
(falha_outros por enquanto só ensina o porteiro "é carro"; ver fontes.json.)
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_util import rms, salvar_wav, wav_bytes_para_sinal  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = json.loads((Path(__file__).parent / "fontes.json").read_text(encoding="utf-8"))
    validas = config["classes_diagnostico"] + config.get("classes_somente_porteiro", []) + [config["classe_nao_carro"]]
    p = argparse.ArgumentParser(description="Grava áudio rotulado do ESP32")
    p.add_argument("--classe", required=True, choices=validas)
    p.add_argument("--segundos", type=int, default=60)
    p.add_argument("--esp32", default="192.168.4.1")
    a = p.parse_args()

    pedacos, falhas = [], 0
    print(f"Gravando '{a.classe}' por {a.segundos} s de http://{a.esp32}/ ... (Ctrl+C encerra e salva)")
    try:
        for i in range(a.segundos):
            inicio = time.time()
            try:
                with urllib.request.urlopen(f"http://{a.esp32}/audio.wav?ms=1000", timeout=4) as r:
                    pedaco = wav_bytes_para_sinal(r.read())
                pedacos.append(pedaco)
                barra = "#" * min(40, int(rms(pedaco) * 400))
                print(f"  {i + 1:3d}/{a.segundos} s  RMS {rms(pedaco):.4f} {barra}")
            except (urllib.error.URLError, OSError) as e:
                falhas += 1
                print(f"  {i + 1:3d}/{a.segundos} s  falhou: {e}")
            time.sleep(max(0.0, 1.0 - (time.time() - inicio)))
    except KeyboardInterrupt:
        print("Interrompido; salvando o que foi gravado.")

    if not pedacos:
        sys.exit("Nada gravado. O notebook está na rede SENTINELA?")
    destino = RAIZ / "data" / "own" / a.classe / f"{a.classe}_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    destino.parent.mkdir(parents=True, exist_ok=True)
    salvar_wav(destino, np.concatenate(pedacos))
    print(f"Salvo: {destino} ({len(pedacos)} s, {falhas} falhas)")
    print("Para usar no treino: python src/ai/prepare_dataset.py  e depois  python src/ai/train.py")


if __name__ == "__main__":
    main()

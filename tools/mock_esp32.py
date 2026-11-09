"""mock_esp32.py — Simulador do ESP32 do SENTINELA (mesma API HTTP do firmware).

Serve para desenvolver e testar o dashboard e a IA sem a placa. Só usa a
biblioteca padrão do Python.

  python tools/mock_esp32.py                       # tom de 120 Hz + ruído (porta 8080)
  python tools/mock_esp32.py --wav-dir <pasta>     # toca os WAVs da pasta em loop
  python tools/mock_esp32.py --porta 8081 --silencio

No dashboard, use o endereço  127.0.0.1:8080 .  Para simular a queda do ESP32,
feche este programa (Ctrl+C) e abra de novo.

O áudio é uma função do "relógio" (amostras desde o início), então /sensor e
/audio.wav sempre mostram o mesmo sinal, como na placa real.
"""
import argparse
import json
import math
import random
import struct
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TAXA = 16000
INICIO = time.time()
trava = threading.Lock()
atuador = {"estado": "off", "buzzer_forcado": None, "inicio_teste": 0.0, "antes_teste": "off"}
config = {"modo": "manual", "limiar": 45, "acima": 0, "abaixo": 0}
playlist = []  # amostras int16 concatenadas dos WAVs (modo --wav-dir)
args = None


def carregar_wavs(pasta):
    """Lê WAVs PCM 16-bit; usa só o 1º canal. Ignora (com aviso) outros formatos."""
    amostras = []
    arquivos = sorted(Path(pasta).rglob("*.wav"))[:200]
    for arq in arquivos:
        try:
            with wave.open(str(arq)) as w:
                if w.getsampwidth() != 2 or w.getframerate() != TAXA:
                    print(f"  ignorado (precisa 16 kHz/16 bits): {arq.name}")
                    continue
                dados = w.readframes(w.getnframes())
                canais = w.getnchannels()
                valores = struct.unpack(f"<{len(dados) // 2}h", dados)[::canais]
                amostras.extend(valores)
        except (wave.Error, EOFError) as e:
            print(f"  ignorado ({e}): {arq.name}")
    print(f"Playlist: {len(arquivos)} arquivos, {len(amostras) / TAXA:.0f} s de áudio")
    return amostras


def amostra(n):
    """Valor PCM da amostra número n do "microfone" simulado."""
    if playlist:
        return playlist[n % len(playlist)]
    if args.silencio:
        return int(random.gauss(0, 40))
    t = n / TAXA
    # Motor fictício: 120 Hz + harmônicos, com volume variando devagar, mais ruído.
    envelope = 0.6 + 0.4 * math.sin(2 * math.pi * 0.1 * t)
    valor = envelope * (6000 * math.sin(2 * math.pi * 120 * t) + 2500 * math.sin(2 * math.pi * 240 * t))
    return int(max(-32768, min(32767, valor + random.gauss(0, 600))))


def amostras_recentes(quantidade):
    agora = int((time.time() - INICIO) * TAXA)
    return [amostra(n) for n in range(agora - quantidade, agora)]


def nivel_atual():
    """Mesma fórmula do firmware: RMS em contagens do ADC (PCM/16); nível 100 = RMS 600."""
    janela = amostras_recentes(4000)
    rms_pcm = math.sqrt(sum(v * v for v in janela) / len(janela))
    pico_pcm = max(abs(v) for v in janela)
    rms = int(rms_pcm / 16)
    return rms, int(pico_pcm / 16), min(100, rms * 100 // 600), pico_pcm >= 32700


def saidas():
    """Calcula verde/vermelho/buzzer a partir do estado (inclui a animação do teste)."""
    e = atuador["estado"]
    if e == "teste":
        etapa = int((time.time() - atuador["inicio_teste"]) / 0.25)
        if etapa >= 8:
            atuador["estado"] = atuador["antes_teste"]
            atuador["buzzer_forcado"] = None
            return saidas()
        return {"estado": "teste", "verde": int(etapa in (0, 2)), "vermelho": int(etapa in (1, 3)),
                "buzzer": int(etapa in (4, 5))}
    vermelho = int(e == "alerta")
    buzzer = vermelho if atuador["buzzer_forcado"] is None else atuador["buzzer_forcado"]
    return {"estado": e, "verde": int(e == "normal"), "vermelho": vermelho, "buzzer": buzzer}


def definir_estado(estado, buzzer=None):
    if estado == "teste" and atuador["estado"] != "teste":
        atuador["antes_teste"] = atuador["estado"]
    atuador.update(estado=estado, buzzer_forcado=buzzer, inicio_teste=time.time())


def avaliar_auto(nivel):
    """Modo auto com a mesma histerese do firmware (3 janelas acima / 8 abaixo)."""
    if config["modo"] != "auto" or atuador["estado"] == "teste":
        return
    if nivel > config["limiar"]:
        config["abaixo"] = 0
        config["acima"] = min(3, config["acima"] + 1)
        if config["acima"] >= 3 and atuador["estado"] != "alerta":
            definir_estado("alerta")
    else:
        config["acima"] = 0
        config["abaixo"] = min(8, config["abaixo"] + 1)
        if config["abaixo"] >= 8 and atuador["estado"] == "alerta":
            definir_estado("normal")


def inteiro(texto, minimo, maximo):
    if texto is None or not texto.isdigit() or len(texto) > 5:
        return None
    valor = int(texto)
    return valor if minimo <= valor <= maximo else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencia o log padrão a cada requisição
        pass

    def responder(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        if isinstance(corpo, dict):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        with trava:
            self.rotear(url.path, q)

    def rotear(self, caminho, q):
        if caminho == "/":
            return self.responder(200, {"nome": "SENTINELA (simulador)", "versao": "1.0"})
        if caminho == "/status":
            return self.responder(200, {
                "ok": True, "versao": "1.0", "uptime_s": int(time.time() - INICIO), "fs_real_hz": TAXA,
                "heap_livre": 200000, "heap_minimo": 195000, "modo": config["modo"], "limiar": config["limiar"],
                "atuador": saidas(), "amostras_perdidas": 0, "intervalo_max_us": 63, "clientes_wifi": 1,
                "simulador": True})
        if caminho == "/sensor":
            rms, pico, nivel, clip = nivel_atual()
            avaliar_auto(nivel)
            return self.responder(200, {"rms": rms, "pico": pico, "nivel": nivel, "clipping": clip,
                                        "ts_ms": int((time.time() - INICIO) * 4) * 250,
                                        "adc_min": max(0, 1550 - pico), "adc_max": min(4095, 1550 + pico)})
        if caminho == "/atuador":
            estado, buzzer = q.get("estado"), q.get("buzzer")
            if estado not in ("normal", "alerta", "off", "teste"):
                return self.responder(400, {"erro": "estado invalido; use normal, alerta, off ou teste"})
            if buzzer is not None and buzzer not in ("0", "1"):
                return self.responder(400, {"erro": "buzzer deve ser 0 ou 1"})
            definir_estado(estado, None if buzzer is None or estado in ("off", "teste") else int(buzzer))
            return self.responder(200, {"ok": True, "atuador": saidas()})
        if caminho == "/config":
            modo = q.get("modo", config["modo"])
            limiar = inteiro(q.get("limiar", str(config["limiar"])), 0, 100)
            if modo not in ("auto", "manual"):
                return self.responder(400, {"erro": "modo deve ser auto ou manual"})
            if limiar is None:
                return self.responder(400, {"erro": "limiar deve ser inteiro de 0 a 100"})
            if modo == "auto" and config["modo"] != "auto" and atuador["estado"] == "off":
                definir_estado("normal")
            config.update(modo=modo, limiar=limiar, acima=0, abaixo=0)
            return self.responder(200, {"ok": True, "modo": modo, "limiar": limiar})
        if caminho == "/audio.wav":
            ms = inteiro(q.get("ms", "1000"), 200, 2000)
            if ms is None:
                return self.responder(400, {"erro": "ms deve ser inteiro de 200 a 2000"})
            dados = struct.pack(f"<{ms * 16}h", *amostras_recentes(ms * 16))
            cab = (b"RIFF" + struct.pack("<I", 36 + len(dados)) + b"WAVEfmt " +
                   struct.pack("<IHHIIHH", 16, 1, 1, TAXA, TAXA * 2, 2, 16) + b"data" + struct.pack("<I", len(dados)))
            return self.responder(200, cab + dados, "audio/wav")
        return self.responder(404, {"erro": "rota nao encontrada"})


def main():
    global args, playlist
    p = argparse.ArgumentParser(description="Simulador do ESP32 SENTINELA")
    p.add_argument("--porta", type=int, default=8080)
    p.add_argument("--wav-dir", help="pasta com WAVs 16 kHz para tocar em loop")
    p.add_argument("--silencio", action="store_true", help="só ruído baixo (testa 'sinal fraco')")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.wav_dir:
        playlist = carregar_wavs(args.wav_dir)
        if not playlist:
            sys.exit("ERRO: nenhum WAV utilizável na pasta.")
    servidor = ThreadingHTTPServer(("0.0.0.0", args.porta), Handler)
    print(f"Simulador do ESP32 em http://127.0.0.1:{args.porta}/  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nSimulador encerrado.")


if __name__ == "__main__":
    main()

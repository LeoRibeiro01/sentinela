"""server.py — Serviço local de IA do SENTINELA (http://localhost:5000).

O que faz:
  - Laço ao vivo: a cada ~1 s baixa 1 s de áudio do ESP32 (/audio.wav), analisa
    (analise.py) e, se a opção estiver ligada, comanda o LED/buzzer com
    suavização (maioria de 3 em 5) para não piscar a cada ruído.
  - GET /api/diagnostico?segundos=5 : captura N janelas, faz a média das
    probabilidades e devolve o diagnóstico com a base de conhecimento.
  - GET /api/resultado : estado ao vivo para o dashboard.
  - GET /api/config?esp32=&demo=&ia_atuador=&limiar_silencio=&limiar_confianca=
  - GET /api/calibrar : mede 3 s de silêncio e ajusta o limiar de "sinal fraco".
  - Serve o dashboard (src/client) em http://localhost:5000/.
Se este serviço cair, o dashboard e o ESP32 continuam funcionando (núcleo sem IA).
Tudo offline. Uso (venv ativo):
    python src/ai/server.py [--esp32 192.168.4.1] [--porta 5000]
"""
import argparse
import json
import math
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analise import Analisador  # noqa: E402
from audio_util import rms, wav_bytes_para_sinal  # noqa: E402
from yamnet_util import Yamnet  # noqa: E402

PASTA_CLIENTE = Path(__file__).resolve().parents[1] / "client"
ARQUIVOS_CLIENTE = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
BASE = json.loads((Path(__file__).parent / "diagnosticos.json").read_text(encoding="utf-8"))
NOMES = {c: v["nome"] for c, v in BASE.items() if not c.startswith("_")}

config = {"esp32": "192.168.4.1", "demo": False, "ia_atuador": False,
          "limiar_silencio": 0.004, "limiar_confianca": 60}
vivo = {"esp32_ok": False, "ao_vivo": {"texto": "Aguardando...", "status": "iniciando"}, "estado_suave": None}
historico = deque(maxlen=30)
votos = deque(maxlen=5)  # últimos 5 votos ("normal"/"falha"/None) para a suavização
trava_esp32 = threading.Lock()   # este processo nunca faz 2 pedidos simultâneos ao ESP32
diagnosticando = threading.Event()
analisador = None
ultimo_comando = None


# ---------------- Comunicação com o ESP32 ----------------

def pedir_esp32(caminho, timeout=4):
    with trava_esp32:
        with urllib.request.urlopen(f"http://{config['esp32']}{caminho}", timeout=timeout) as r:
            return r.read()


# 1,5 s = 2 quadros cheios do YAMNet; ainda deixa 0,5 s de folga no buffer de ~2 s do ESP32.
MS_AO_VIVO = 1500


def baixar_audio(ms=1000):
    return wav_bytes_para_sinal(pedir_esp32(f"/audio.wav?ms={ms}"))


def comandar_atuador(estado):
    """Envia o estado ao ESP32. Falha de rede não derruba o serviço: só registra."""
    global ultimo_comando
    try:
        pedir_esp32(f"/atuador?estado={estado}", timeout=3)
        ultimo_comando = estado
        return True
    except (urllib.error.URLError, OSError):
        return False


# ---------------- Laço ao vivo ----------------

def texto_ao_vivo(r):
    """Resumo legível de uma análise de 1 s para o painel ao vivo."""
    if r.get("easter"):
        nome, prob = r["easter"]
        return {"texto": f"{nome} detectado!", "confianca": int(prob * 100), "status": "easter_egg"}
    if r["status"] == "sinal_fraco":
        return {"texto": "Silêncio / sinal fraco", "status": "sinal_fraco"}
    if r["status"] == "nao_carro":
        som = f" ({r['som']})" if r["som"] else ""
        return {"texto": f"Não é motor de carro{som}", "confianca": int((1 - r["carro_prob"]) * 100),
                "status": "nao_carro"}
    if r["status"] == "sem_modelo":
        return {"texto": f"Motor detectado (modelo não treinado) — {r['som']}", "status": "sem_modelo"}
    ranking = analisador.ranking(r["probs"], NOMES)
    return {"texto": ranking[0]["nome"], "confianca": ranking[0]["prob"], "status": "ok",
            "top3": ranking[:3], "carro_prob": int(r["carro_prob"] * 100)}


def suavizar(r):
    """Maioria de 3 em 5 votos confiantes; votos incertos/silêncio não mudam o estado."""
    voto = None
    if r["status"] == "ok" and float(np.max(r["probs"])) * 100 >= config["limiar_confianca"]:
        voto = "normal" if analisador.classes[int(np.argmax(r["probs"]))] == "normal" else "falha"
    votos.append(voto)
    contagem = Counter(v for v in votos if v)
    if contagem["falha"] >= 3:
        vivo["estado_suave"] = "alerta"
    elif contagem["normal"] >= 3:
        vivo["estado_suave"] = "normal"
    if config["ia_atuador"] and vivo["estado_suave"] and vivo["estado_suave"] != ultimo_comando:
        comandar_atuador(vivo["estado_suave"])


def laco_ao_vivo():
    while True:
        inicio = time.time()
        if diagnosticando.is_set():  # o diagnóstico usa o ESP32 sozinho
            time.sleep(0.2)
            continue
        try:
            sinal = baixar_audio(MS_AO_VIVO)
            vivo["esp32_ok"] = True
            r = analisador.analisar(sinal, config["limiar_silencio"], config["demo"])
            resumo = texto_ao_vivo(r)
            resumo["rms_bruto"] = r["rms_bruto"]
            suavizar(r)
        except (urllib.error.URLError, OSError, ValueError, EOFError) as e:
            vivo["esp32_ok"] = False
            resumo = {"texto": "ESP32 sem resposta", "status": "esp32_offline", "erro": str(e)[:80]}
            votos.clear()
        anterior = vivo["ao_vivo"].get("texto")
        vivo["ao_vivo"] = resumo
        if resumo["texto"] != anterior:
            historico.append({"hora": time.strftime("%H:%M:%S"), "texto": resumo["texto"]})
        time.sleep(max(0.05, 1.0 - (time.time() - inicio)))


# ---------------- Diagnóstico de N segundos ----------------

def montar_diagnostico(chave, ranking=None):
    entrada = BASE.get(chave, BASE["_inconclusivo"])
    return {"titulo": entrada["titulo"], "causas_provaveis": entrada["causas_provaveis"],
            "o_que_verificar": entrada["o_que_verificar"], "urgencia": entrada["urgencia"], "aviso": BASE["_aviso"]}


def diagnosticar(segundos):
    """Captura 1 s por segundo, descarta janelas silenciosas e analisa o restante JUNTO.

    Juntar as janelas (≈ 5 s contínuos) dá ao YAMNet ~9 quadros cheios, o mesmo
    formato avaliado em docs/metricas_ia.md ("simulação do botão DIAGNOSTICAR").
    """
    janelas, falhas = [], 0
    for _ in range(segundos):
        inicio = time.time()
        try:
            janelas.append(baixar_audio(1000))
        except (urllib.error.URLError, OSError, ValueError, EOFError):
            falhas += 1
        time.sleep(max(0.0, 1.0 - (time.time() - inicio)))  # uma janela nova por segundo

    resposta = {"janelas_total": segundos, "janelas_validas": 0, "classes": [], "top": None,
                "confianca": 0, "atuador": "inalterado"}
    if not janelas:
        resposta.update(status="erro", erro="ESP32 não respondeu durante a captura")
        return resposta
    com_som = [j for j in janelas if rms(j) >= config["limiar_silencio"]]
    resposta["janelas_validas"] = len(com_som)
    if len(com_som) < max(2, math.ceil(segundos * 0.4)):
        resposta.update(status="sinal_fraco", diagnostico=montar_diagnostico("_sinal_fraco"))
        return resposta

    r = analisador.analisar(np.concatenate(com_som), config["limiar_silencio"])
    resposta["carro_prob"] = int(r["carro_prob"] * 100)
    resposta["som_detectado"] = r["som"]
    if r["status"] == "nao_carro":
        resposta.update(status="nao_carro", diagnostico=montar_diagnostico("_nao_carro"))
        return resposta
    if r["status"] != "ok":  # sem modelo treinado
        resposta.update(status="erro", erro="modelo não treinado (rode src/ai/train.py)")
        return resposta

    probs = r["probs"]
    ranking = analisador.ranking(probs, NOMES)
    top = ranking[0]
    resposta.update(classes=ranking, top=top["classe"], top_nome=top["nome"], confianca=top["prob"])
    if top["prob"] >= config["limiar_confianca"]:
        resposta.update(status="ok", diagnostico=montar_diagnostico(top["classe"]))
        estado = "normal" if top["classe"] == "normal" else "alerta"
    else:
        resposta.update(status="inconclusivo", diagnostico=montar_diagnostico("_inconclusivo"))
        estado = "normal"
    if comandar_atuador(estado):
        resposta["atuador"] = estado
    votos.clear()  # recomeça a suavização do modo ao vivo a partir do diagnóstico
    return resposta


def calibrar_silencio():
    """Mede 3 s em silêncio; o limiar passa a ser 2,5× o maior RMS medido (mín. 0,002)."""
    medidas = [rms(baixar_audio(1000)) for _ in range(3)]
    config["limiar_silencio"] = round(max(0.002, 2.5 * max(medidas)), 5)
    return {"ok": True, "rms_medidos": [round(m, 5) for m in medidas], "limiar_silencio": config["limiar_silencio"]}


# ---------------- Servidor HTTP ----------------

def booleano(texto):
    return texto in ("1", "true", "sim", "on")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        if not isinstance(corpo, bytes):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            self.rotear(url.path, q)
        except Exception as e:  # erro inesperado vira JSON 500, sem derrubar o serviço
            self.responder(500, {"erro": f"{type(e).__name__}: {e}"})

    def rotear(self, caminho, q):
        if caminho in ARQUIVOS_CLIENTE:
            arquivo = PASTA_CLIENTE / ARQUIVOS_CLIENTE[caminho]
            return self.responder(200, arquivo.read_bytes(), TIPOS[arquivo.suffix])
        if caminho == "/api/resultado":
            return self.responder(200, {
                "ok": True, "modelo": analisador.modelo is not None, "classes": analisador.classes,
                **config, "esp32_ok": vivo["esp32_ok"], "ao_vivo": vivo["ao_vivo"],
                "estado_suave": vivo["estado_suave"], "diagnosticando": diagnosticando.is_set(),
                "historico": list(historico)})
        if caminho == "/api/config":
            return self.responder(*self.configurar(q))
        if caminho == "/api/diagnostico":
            segundos = q.get("segundos", "5")
            if not segundos.isdigit() or not 1 <= int(segundos) <= 10:
                return self.responder(400, {"status": "erro", "erro": "segundos deve ser de 1 a 10"})
            if diagnosticando.is_set():
                return self.responder(409, {"status": "erro", "erro": "já existe um diagnóstico em andamento"})
            diagnosticando.set()
            try:
                return self.responder(200, diagnosticar(int(segundos)))
            finally:
                diagnosticando.clear()
        if caminho == "/api/calibrar":
            diagnosticando.set()
            try:
                return self.responder(200, calibrar_silencio())
            except (urllib.error.URLError, OSError) as e:
                return self.responder(503, {"ok": False, "erro": f"ESP32 não respondeu: {e}"})
            finally:
                diagnosticando.clear()
        return self.responder(404, {"erro": "rota não encontrada"})

    def configurar(self, q):
        global ultimo_comando
        if "esp32" in q:
            if not re.fullmatch(r"[\w.-]+(:\d{1,5})?", q["esp32"]):
                return 400, {"erro": "endereço do ESP32 inválido"}
            config["esp32"] = q["esp32"]
        for chave in ("demo", "ia_atuador"):
            if chave in q:
                config[chave] = booleano(q[chave])
        if "ia_atuador" in q:
            ultimo_comando = None  # ao religar, reenvia o estado atual na próxima decisão
        try:
            if "limiar_silencio" in q:
                config["limiar_silencio"] = min(0.5, max(0.0, float(q["limiar_silencio"])))
            if "limiar_confianca" in q:
                config["limiar_confianca"] = min(100, max(0, int(q["limiar_confianca"])))
        except ValueError:
            return 400, {"erro": "limiar inválido"}
        return 200, {"ok": True, **config}


def main():
    global analisador
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Serviço de IA do SENTINELA")
    p.add_argument("--esp32", default="192.168.4.1", help="endereço do ESP32 (ex.: 127.0.0.1:8080 para o simulador)")
    p.add_argument("--porta", type=int, default=5000)
    p.add_argument("--demo", action="store_true", help="liga o modo demo (animais) ao iniciar")
    a = p.parse_args()
    config.update(esp32=a.esp32, demo=a.demo)

    print("Carregando YAMNet e classificador...")
    analisador = Analisador(Yamnet())
    if analisador.modelo:
        config["limiar_confianca"] = analisador.limiar_confianca
        print(f"Modelo: classes {analisador.classes}, limiar de confiança {config['limiar_confianca']}%")
    else:
        print("AVISO: models/classificador.joblib não existe; rodando só nível + easter eggs.")
    threading.Thread(target=laco_ao_vivo, daemon=True).start()
    servidor = ThreadingHTTPServer(("127.0.0.1", a.porta), Handler)
    print(f"Serviço de IA em http://localhost:{a.porta}/  (ESP32: {config['esp32']})  Ctrl+C para parar")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServiço encerrado.")


if __name__ == "__main__":
    main()

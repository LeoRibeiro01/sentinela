"""teste_fase1.py — Roteiro automático de aceitação do firmware (Fase 1).

Usa só a biblioteca padrão do Python (nada para instalar). Três testes:

  python tools/teste_fase1.py rotas                  # cada rota, códigos HTTP e WAV
  python tools/teste_fase1.py critico --minutos 2    # áudio estável com /audio.wav em loop
  python tools/teste_fase1.py resistencia --minutos 30  # heap/uptime por 30 min (CSV)

Opção --host muda o endereço (padrão 192.168.4.1). Termina com código 0 se tudo
passou e 1 se algo falhou, imprimindo [OK]/[FALHA] em cada verificação.
"""
import argparse
import csv
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

TIMEOUT_S = 5
# O console do Windows usa cp1252 por padrão; forçamos UTF-8 para os acentos não quebrarem o script.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
falhas = []


def verificar(condicao, descricao):
    """Imprime o resultado de uma verificação e guarda as falhas."""
    print(("[OK]    " if condicao else "[FALHA] ") + descricao)
    if not condicao:
        falhas.append(descricao)
    return condicao


def pedir(base, caminho):
    """GET simples. Devolve (código HTTP, cabeçalhos, corpo em bytes); erros HTTP não lançam exceção."""
    try:
        with urllib.request.urlopen(base + caminho, timeout=TIMEOUT_S) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def pedir_json(base, caminho):
    codigo, cab, corpo = pedir(base, caminho)
    return codigo, cab, json.loads(corpo.decode("utf-8"))


def analisar_wav(corpo):
    """Abre o WAV da memória e devolve (canais, bytes/amostra, taxa, duração_s, amostras)."""
    with wave.open(io.BytesIO(corpo)) as w:
        quadros = w.readframes(w.getnframes())
        amostras = [int.from_bytes(quadros[i:i + 2], "little", signed=True) for i in range(0, len(quadros), 2)]
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes() / w.getframerate(), amostras


def teste_rotas(base):
    codigo, cab, st = pedir_json(base, "/status")
    verificar(codigo == 200 and st.get("ok") is True, f"/status responde 200 (versão {st.get('versao')})")
    verificar(cab.get("Access-Control-Allow-Origin") == "*", "cabeçalho CORS presente")
    verificar(cab.get("Cache-Control") == "no-store", "cabeçalho Cache-Control: no-store presente")
    for campo in ["uptime_s", "fs_real_hz", "heap_livre", "modo", "atuador"]:
        verificar(campo in st, f"/status contém '{campo}'")
    fs = st.get("fs_real_hz", 0)
    verificar(15500 <= fs <= 16500, f"taxa real ~ 16 kHz (medido: {fs} Hz)")
    print(f"        amostras_perdidas={st.get('amostras_perdidas')} intervalo_max_us={st.get('intervalo_max_us')}"
          f" heap_livre={st.get('heap_livre')}")

    codigo, _, se = pedir_json(base, "/sensor")
    verificar(codigo == 200 and all(k in se for k in ["rms", "pico", "nivel", "clipping", "ts_ms"]),
              f"/sensor responde com rms/pico/nivel/clipping/ts_ms ({se})")

    for estado, esperado in [("normal", (1, 0, 0)), ("alerta", (0, 1, 1)), ("off", (0, 0, 0))]:
        codigo, _, r = pedir_json(base, f"/atuador?estado={estado}")
        a = r.get("atuador", {})
        obtido = (a.get("verde"), a.get("vermelho"), a.get("buzzer"))
        verificar(codigo == 200 and a.get("estado") == estado and obtido == esperado,
                  f"/atuador?estado={estado} → verde/vermelho/buzzer = {obtido}")
    codigo, _, r = pedir_json(base, "/atuador?estado=normal&buzzer=1")
    verificar(codigo == 200 and r["atuador"]["buzzer"] == 1, "/atuador?estado=normal&buzzer=1 liga o buzzer")
    codigo, _, r = pedir_json(base, "/atuador?estado=teste")
    verificar(codigo == 200 and r["atuador"]["estado"] == "teste", "/atuador?estado=teste inicia a sequência")
    time.sleep(2.5)
    _, _, st = pedir_json(base, "/status")
    verificar(st["atuador"]["estado"] == "normal", "após o teste (~2 s) o atuador volta ao estado anterior")
    pedir(base, "/atuador?estado=off")

    codigo, _, r = pedir_json(base, "/config?modo=auto&limiar=60")
    verificar(codigo == 200 and r.get("modo") == "auto" and r.get("limiar") == 60, "/config?modo=auto&limiar=60")
    codigo, _, r = pedir_json(base, "/config?modo=manual")
    verificar(codigo == 200 and r.get("modo") == "manual", "/config?modo=manual")
    pedir(base, "/atuador?estado=off")

    for caminho, esperado in [("/atuador?estado=xyz", 400), ("/atuador", 400), ("/atuador?estado=normal&buzzer=7", 400),
                              ("/config?modo=xyz", 400), ("/config?limiar=101", 400), ("/audio.wav?ms=100", 400),
                              ("/audio.wav?ms=3000", 400), ("/audio.wav?ms=abc", 400), ("/nao-existe", 404)]:
        codigo, cab, corpo = pedir(base, caminho)
        try:
            eh_json = "erro" in json.loads(corpo.decode("utf-8"))
        except ValueError:
            eh_json = False
        verificar(codigo == esperado and eh_json, f"{caminho} → {codigo} com JSON de erro (esperado {esperado})")

    for ms in [200, 1000, 2000]:
        inicio = time.time()
        codigo, cab, corpo = pedir(base, f"/audio.wav?ms={ms}")
        tempo = time.time() - inicio
        if not verificar(codigo == 200, f"/audio.wav?ms={ms} → 200 em {tempo:.2f} s"):
            continue
        verificar(int(cab.get("Content-Length", -1)) == len(corpo), f"Content-Length ({cab.get('Content-Length')}) = bytes recebidos ({len(corpo)})")
        canais, largura, taxa, duracao, amostras = analisar_wav(corpo)
        verificar(canais == 1 and largura == 2, f"WAV mono 16-bit (canais={canais}, bytes={largura})")
        verificar(abs(duracao - ms / 1000) < 0.02, f"duração {duracao:.3f} s ~ {ms / 1000} s (taxa no cabeçalho {taxa} Hz)")
        verificar(max(abs(a) for a in amostras) > 0, "WAV não é todo zero")
        if ms == 1000:
            with open("audio-teste.wav", "wb") as f:
                f.write(corpo)
            print("        salvo em audio-teste.wav — abra num player e confira se o som está certo")


def teste_critico(base, minutos):
    """Baixa /audio.wav sem parar numa thread e lê /sensor a cada 1 s na principal."""
    fim = time.time() + minutos * 60
    contagem = {"wav_ok": 0, "wav_falha": 0, "wav_zerado": 0}

    def baixar_em_loop():
        while time.time() < fim:
            try:
                codigo, _, corpo = pedir(base, "/audio.wav?ms=1000")
                if codigo != 200:
                    contagem["wav_falha"] += 1
                    continue
                amostras = analisar_wav(corpo)[4]
                contagem["wav_ok"] += 1
                if max(abs(a) for a in amostras) < 20:
                    contagem["wav_zerado"] += 1
            except Exception:
                contagem["wav_falha"] += 1
                time.sleep(0.5)

    t = threading.Thread(target=baixar_em_loop, daemon=True)
    t.start()
    print(f"Teste crítico por {minutos} min: fale, bata palmas e faça silêncio perto do microfone.")
    leituras, falhas_sensor, ts_anterior, ts_parado = [], 0, None, 0
    while time.time() < fim:
        try:
            _, _, s = pedir_json(base, "/sensor")
            leituras.append(s)
            if s["ts_ms"] == ts_anterior:
                ts_parado += 1
            ts_anterior = s["ts_ms"]
            print(f"  rms={s['rms']:5d} nivel={s['nivel']:3d} adc=[{s.get('adc_min')}..{s.get('adc_max')}]"
                  f" clipping={s['clipping']}  wav_ok={contagem['wav_ok']} wav_falha={contagem['wav_falha']}")
        except Exception as e:
            falhas_sensor += 1
            print(f"  /sensor falhou: {e}")
        time.sleep(1)
    t.join(timeout=10)

    _, _, st = pedir_json(base, "/status")
    zerados = sum(1 for s in leituras if s.get("adc_max", 1) == 0)
    verificar(falhas_sensor == 0, f"/sensor respondeu sempre ({falhas_sensor} falhas)")
    verificar(contagem["wav_ok"] > 0 and contagem["wav_falha"] <= contagem["wav_ok"] * 0.05,
              f"downloads de WAV: {contagem['wav_ok']} ok, {contagem['wav_falha']} falhas (tolerância 5%)")
    verificar(zerados == 0 and contagem["wav_zerado"] == 0,
              f"sem leituras zeradas (janelas com adc_max=0: {zerados}; WAVs mudos: {contagem['wav_zerado']})")
    verificar(ts_parado <= 2, f"janelas do sensor continuam avançando (repetidas: {ts_parado})")
    if leituras:
        verificar(max(s["rms"] for s in leituras) > 3 * max(1, min(s["rms"] for s in leituras)),
                  f"RMS reagiu ao som (mín {min(s['rms'] for s in leituras)}, máx {max(s['rms'] for s in leituras)})")
    verificar(15500 <= st["fs_real_hz"] <= 16500, f"taxa real ao fim: {st['fs_real_hz']} Hz")
    print(f"        amostras_perdidas={st.get('amostras_perdidas')} intervalo_max_us={st.get('intervalo_max_us')}"
          f" (ideal 62-63 us)")


def teste_resistencia(base, minutos):
    """Consulta /status a cada 30 s, grava CSV e confere reinícios e heap."""
    arquivo = f"resistencia_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    linhas, sem_resposta = [], 0
    fim = time.time() + minutos * 60
    with open(arquivo, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["hora", "uptime_s", "heap_livre", "heap_minimo", "fs_real_hz", "amostras_perdidas"])
        while time.time() < fim:
            try:
                _, _, st = pedir_json(base, "/status")
                linha = [time.strftime("%H:%M:%S"), st["uptime_s"], st["heap_livre"], st.get("heap_minimo"),
                         st["fs_real_hz"], st.get("amostras_perdidas")]
                linhas.append(linha)
                escritor.writerow(linha)
                f.flush()
                print("  " + "  ".join(str(x) for x in linha))
            except Exception as e:
                sem_resposta += 1
                print(f"  sem resposta: {e}")
            time.sleep(30)
    print(f"        CSV salvo em {arquivo}")
    reinicios = sum(1 for a, b in zip(linhas, linhas[1:]) if b[1] < a[1])
    verificar(sem_resposta == 0, f"ESP32 respondeu em todas as consultas ({sem_resposta} sem resposta)")
    verificar(reinicios == 0, f"nenhum reinício (uptime nunca voltou: {reinicios})")
    if len(linhas) >= 4:
        quarto = len(linhas) // 4
        media_inicio = sum(l[2] for l in linhas[:quarto]) / quarto
        media_fim = sum(l[2] for l in linhas[-quarto:]) / quarto
        verificar(media_fim > media_inicio - 4096,
                  f"heap estável (média do início {media_inicio:.0f}, do fim {media_fim:.0f}; tolerância 4 KB)")


def main():
    p = argparse.ArgumentParser(description="Testes de aceitação do firmware SENTINELA")
    p.add_argument("teste", choices=["rotas", "critico", "resistencia"])
    p.add_argument("--host", default="192.168.4.1")
    p.add_argument("--minutos", type=float, default=None)
    a = p.parse_args()
    base = "http://" + a.host
    try:
        if a.teste == "rotas":
            teste_rotas(base)
        elif a.teste == "critico":
            teste_critico(base, a.minutos or 2)
        else:
            teste_resistencia(base, a.minutos or 30)
    except (urllib.error.URLError, OSError) as e:
        verificar(False, f"sem conexão com {base}: {e} (o notebook está na rede SENTINELA?)")
    print(f"\nResultado: {'TUDO PASSOU' if not falhas else str(len(falhas)) + ' FALHA(S)'}")
    sys.exit(0 if not falhas else 1)


if __name__ == "__main__":
    main()

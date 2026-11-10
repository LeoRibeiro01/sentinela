"""baixar_youtube.py — Coleta áudio de falhas automotivas em vídeos do YouTube.

Por quê: os datasets públicos têm UMA gravação por falha de suspensão/freio
(amrrashed), o que não dá para treinar nem medir. Vídeos de mecânicos mostrando
o som da falha são a única fonte com volume. Uso acadêmico, sem redistribuir:
data/ não é versionado; a lista de vídeos usados fica em fontes_youtube.csv.

O que faz, por classe:
  1. Busca no YouTube (várias consultas, EN e PT) e filtra pelo TÍTULO
     (precisa ter uma palavra da falha; descarta jogos, música, comparações "vs").
  2. Baixa só o áudio (.m4a).
  3. Limpa com o YAMNet: descarta quadros de 0,96 s com fala ou música
     (narração do mecânico, vinheta). Sobram trechos contínuos de >= 2 s.
  4. Salva data/raw/youtube/<classe>/<id>_segment_<n>.wav (16 kHz mono).
     O sufixo _segment_ faz o prepare_dataset agrupar pelo vídeo: trechos do
     mesmo vídeo nunca ficam um no treino e outro no teste.

Uso:  .venv\\Scripts\\python tools\\baixar_youtube.py            (todas as classes)
      .venv\\Scripts\\python tools\\baixar_youtube.py falha_freio (uma classe)
Requer: pip install yt-dlp (não vai para o requirements: só é usado aqui).
"""
import csv
import subprocess
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src" / "ai"))
from audio_util import TAXA, carregar, rms, salvar_wav  # noqa: E402
from yamnet_util import PASSO_QUADRO, Yamnet  # noqa: E402

PASTA = RAIZ / "data" / "raw" / "youtube"
PASTA_BAIXADOS = PASTA / "_baixados"
LISTA = PASTA / "fontes_youtube.csv"

# classe: (consultas de busca, palavras que o título precisa ter — ao menos uma)
CLASSES = {
    "falha_homocinetica": (
        ["bad cv joint clicking sound", "cv axle clicking when turning noise",
         "outer cv joint noise turning", "junta homocinetica barulho", "homocinetica estalando"],
        ["cv ", "cv-", "cv axle", "cv joint", "homocin", "constant velocity"]),
    "falha_pivo": (
        ["bad ball joint noise", "ball joint clunk sound", "ball joint squeak noise",
         "pivo de suspensao barulho", "barulho no pivo da suspensao"],
        ["ball joint", "balljoint", "pivo", "pivô"]),
    "falha_freio": (
        ["brake pads squealing sound", "worn brake pads squeal noise", "brake wear indicator squeal",
         "pastilha de freio chiando", "freio chiando barulho"],
        ["brake", "freio", "pastilha"]),
    "falha_amortecedor": (
        ["bad shock absorber noise", "worn strut clunk noise", "bad shocks knocking over bumps",
         "amortecedor batendo barulho", "amortecedor estourado barulho"],
        ["shock", "strut", "amortecedor"]),
    "falha_pistao": (
        ["piston slap sound", "piston slap cold start noise", "piston slap engine noise",
         "barulho de pistao batendo", "motor com pistao batendo"],
        ["piston slap", "pistao", "pistão", "piston noise", "piston knock"]),
    # Classes que já existem: só ganham mais exemplos.
    "falha_correia": (
        ["alternator belt squeal sound", "serpentine belt squeal noise", "correia do alternador chiando"],
        ["belt", "correia"]),
    "falha_batida_pino": (
        ["engine pinging detonation sound", "spark knock pinging noise acceleration", "batida de pino barulho"],
        ["ping", "detonation", "spark knock", "pino", "detonação", "detonacao"]),
    "falha_tucho": (
        ["lifter tick sound", "rocker arm tick noise", "valve tick noise engine",
         "barulho de tucho", "balancim batendo barulho"],
        ["lifter", "tappet", "rocker", "valve tick", "tucho", "balancim", "valvula", "válvula"]),
}

# Títulos com estas palavras são descartados: jogos/simuladores, música, ou vídeos que
# comparam duas falhas ("x vs y") e misturariam os rótulos.
PROIBIDAS = [" vs ", "vs.", "versus", "beamng", "forza", "game", "asmr", "song", "music",
             "lego", "toy", "rc car", "motorcycle", "moto ", "bike", "truck", "rod knock"]

# Vídeos que passaram pelo filtro de título mas foram reprovados na conferência manual (09/11):
# motos 2 tempos, um vídeo de motor SEM a falha ("no piston slap") e vídeos de freio sem o som.
EXCLUIR_IDS = {"MPdfjSFzBfY", "ur6THFUEf6M", "3ns2Xtfw1Pg",
               "Yl4yxvp_xGg", "KRQr89MGo3M", "2jQUcz-1oxc"}

RESULTADOS_POR_BUSCA = 12
VIDEOS_POR_CLASSE = 14
DURACAO_MIN_S, DURACAO_MAX_S = 8, 420
MAX_SEGUNDOS_POR_VIDEO = 90   # um vídeo longo não pode dominar a classe
TRECHO_MIN_S = 2.0
LIMIAR_FALA = 0.30
LIMIAR_MUSICA = 0.30

YTDLP = [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings"]


def buscar(consulta):
    """Devolve [(id, duração, título)] dos primeiros resultados da busca."""
    saida = subprocess.run(
        YTDLP + ["--flat-playlist", "--print", "%(id)s\t%(duration)s\t%(title)s",
                 f"ytsearch{RESULTADOS_POR_BUSCA}:{consulta}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    videos = []
    for linha in saida.stdout.splitlines():
        partes = linha.split("\t")
        if len(partes) == 3:
            try:
                duracao = float(partes[1])
            except ValueError:
                continue  # transmissões ao vivo não têm duração
            videos.append((partes[0], duracao, partes[2]))
    return videos


def titulo_serve(titulo, palavras):
    t = f" {titulo.lower()} "
    return any(p in t for p in palavras) and not any(p in t for p in PROIBIDAS)


def baixar(video_id):
    destino = PASTA_BAIXADOS / f"{video_id}.m4a"
    if not destino.exists():
        subprocess.run(YTDLP + ["-f", "bestaudio[ext=m4a]/bestaudio", "-o", str(destino),
                                f"https://www.youtube.com/watch?v={video_id}"],
                       capture_output=True)
    return destino if destino.exists() else None


def limpar(sinal, yamnet):
    """Remove fala e música. Devolve lista de trechos contínuos (arrays) de >= 2 s."""
    scores, _ = yamnet.analisar(sinal)
    i_fala = [yamnet.nomes.index(n) for n in ("Speech", "Narration, monologue", "Conversation")
              if n in yamnet.nomes]
    i_musica = [yamnet.nomes.index(n) for n in ("Music", "Singing") if n in yamnet.nomes]
    bom = (scores[:, i_fala].max(axis=1) < LIMIAR_FALA) & (scores[:, i_musica].max(axis=1) < LIMIAR_MUSICA)

    # Cada quadro k cobre as amostras [k*PASSO, k*PASSO + 0,96 s). Juntamos quadros bons seguidos.
    trechos, inicio = [], None
    for k, ok in enumerate(list(bom) + [False]):
        if ok and inicio is None:
            inicio = k
        elif not ok and inicio is not None:
            a = inicio * PASSO_QUADRO
            b = min(len(sinal), (k - 1) * PASSO_QUADRO + 15360)
            if (b - a) / TAXA >= TRECHO_MIN_S:
                trechos.append(sinal[a:b])
            inicio = None
    return trechos


def main():
    escolhidas = sys.argv[1:] or list(CLASSES)
    PASTA_BAIXADOS.mkdir(parents=True, exist_ok=True)
    yamnet = Yamnet()

    # Um vídeo só pode pertencer a UMA classe (o primeiro que o achou vence).
    ja_usados = set()
    linhas = []
    if LISTA.exists():
        with open(LISTA, encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                if linha["classe"] not in escolhidas:
                    linhas.append(linha)
                    ja_usados.add(linha["id"])

    for classe in escolhidas:
        consultas, palavras = CLASSES[classe]
        pasta_classe = PASTA / classe
        pasta_classe.mkdir(parents=True, exist_ok=True)
        for antigo in pasta_classe.glob("*.wav"):
            antigo.unlink()  # recomeça a classe do zero (reprodutível)

        candidatos = []
        for consulta in consultas:
            for vid, dur, titulo in buscar(consulta):
                if (vid not in ja_usados and vid not in EXCLUIR_IDS and DURACAO_MIN_S <= dur <= DURACAO_MAX_S
                        and titulo_serve(titulo, palavras) and vid not in [c[0] for c in candidatos]):
                    candidatos.append((vid, dur, titulo))

        aceitos, total_s = 0, 0.0
        for vid, dur, titulo in candidatos:
            if aceitos >= VIDEOS_POR_CLASSE:
                break
            arquivo = baixar(vid)
            if arquivo is None:
                print(f"  [{classe}] falhou download: {vid}")
                continue
            try:
                sinal = carregar(arquivo)
            except Exception as erro:  # arquivo estragado: segue para o próximo
                print(f"  [{classe}] não abriu {vid}: {erro}")
                continue
            trechos = limpar(sinal, yamnet)
            segundos, n = 0.0, 0
            for trecho in trechos:
                if segundos >= MAX_SEGUNDOS_POR_VIDEO or rms(trecho) < 0.003:
                    continue
                trecho = trecho[: int((MAX_SEGUNDOS_POR_VIDEO - segundos) * TAXA)]
                salvar_wav(pasta_classe / f"{vid}_segment_{n}.wav", trecho)
                segundos += len(trecho) / TAXA
                n += 1
            if segundos < TRECHO_MIN_S:
                print(f"  [{classe}] {vid}: só fala/música, descartado — {titulo[:60]}")
                continue
            aceitos += 1
            total_s += segundos
            ja_usados.add(vid)
            linhas.append({"id": vid, "classe": classe, "segundos": f"{segundos:.1f}", "titulo": titulo,
                           "url": f"https://www.youtube.com/watch?v={vid}"})
            print(f"  [{classe}] {vid}: {segundos:5.1f} s de {dur:.0f} s — {titulo[:60]}")
        print(f"== {classe}: {aceitos} vídeos, {total_s / 60:.1f} min úteis "
              f"({len(candidatos)} candidatos pelo título)\n")

    with open(LISTA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "classe", "segundos", "titulo", "url"])
        w.writeheader()
        w.writerows(linhas)
    print(f"Lista de vídeos usados: {LISTA}")


if __name__ == "__main__":
    main()

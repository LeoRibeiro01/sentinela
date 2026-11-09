"""audio_util.py — Funções de áudio compartilhadas pelo treino e pelo serviço ao vivo.

Responsabilidade única: carregar, converter (16 kHz mono), normalizar e "aumentar"
áudio. O treino e o servidor usam EXATAMENTE a mesma normalização; se fossem
diferentes, o modelo veria ao vivo um áudio diferente do que viu no treino.
"""
import io
import wave

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt

TAXA = 16000          # o YAMNet exige 16 kHz mono
RMS_ALVO = 0.1        # todo trecho é levado a este RMS (≈ -20 dBFS) antes do modelo
RMS_MINIMO_FRAME = 0.01  # quadros 10× abaixo do alvo (pausas) são descartados no treino


def para_16k_mono(sinal, taxa):
    """Converte para float32 mono a 16 kHz (média dos canais + reamostragem polifásica)."""
    sinal = np.asarray(sinal, dtype=np.float32)
    if sinal.ndim == 2:
        sinal = sinal.mean(axis=1)
    if taxa != TAXA:
        # resample_poly usa uma razão de inteiros; reduzimos pelo MDC para ser rápido.
        mdc = np.gcd(int(taxa), TAXA)
        sinal = resample_poly(sinal, TAXA // mdc, int(taxa) // mdc).astype(np.float32)
    return sinal


FORMATOS_FFMPEG = {".m4a", ".aac", ".mp4"}


def carregar(caminho):
    """Lê o áudio e devolve float32 mono 16 kHz em [-1, 1].

    WAV/FLAC/OGG/MP3 via libsndfile; M4A/AAC via ffmpeg (pacote imageio-ffmpeg,
    usado só na preparação do dataset, nunca ao vivo).
    """
    if str(caminho).lower().endswith(tuple(FORMATOS_FFMPEG)):
        return carregar_com_ffmpeg(caminho)
    sinal, taxa = sf.read(str(caminho), dtype="float32", always_2d=False)
    return para_16k_mono(sinal, taxa)


def carregar_com_ffmpeg(caminho):
    import subprocess

    import imageio_ffmpeg  # importado aqui: o serviço ao vivo não precisa dele

    comando = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(caminho),
               "-f", "f32le", "-ac", "1", "-ar", str(TAXA), "-"]
    saida = subprocess.run(comando, capture_output=True, check=True)
    return np.frombuffer(saida.stdout, dtype="<f4").copy()


def parece_corrompido(sinal):
    """True se o trecho parece ruído branco em escala cheia (arquivo corrompido).

    Áudio real tem amostras vizinhas parecidas (autocorrelação de passo 1 alta,
    tipicamente > 0,5). Ruído branco tem autocorrelação ~0. Junto com RMS alto,
    isso denuncia arquivo estragado: aconteceu com os WAVs segmentados do amrrashed.
    """
    x = sinal - sinal.mean()
    energia = float(np.dot(x, x))
    if energia == 0:
        return False
    autocorrelacao = float(np.dot(x[1:], x[:-1])) / energia
    return abs(autocorrelacao) < 0.1 and rms(sinal) > 0.2


def wav_bytes_para_sinal(dados):
    """Converte a resposta de /audio.wav do ESP32 (bytes) em float32 mono 16 kHz."""
    with wave.open(io.BytesIO(dados)) as w:
        taxa = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    sinal = pcm.astype(np.float32) / 32768.0
    if abs(taxa - TAXA) > 20:  # o ESP32 informa a taxa medida (ex.: 15998); só reamostra se for bem diferente
        sinal = para_16k_mono(sinal, taxa)
    return sinal


def rms(sinal):
    return float(np.sqrt(np.mean(np.square(sinal)))) if len(sinal) else 0.0


def normalizar(sinal):
    """Leva o trecho ao RMS_ALVO e limita picos em ±1. Trecho mudo volta inalterado."""
    valor = rms(sinal)
    if valor < 1e-6:
        return sinal
    return np.clip(sinal * (RMS_ALVO / valor), -1.0, 1.0).astype(np.float32)


def aumentar(sinal, rng):
    """Cópia "como se tivesse passado pelo alto-falante, pelo MAX9814 e pelo ADC do ESP32".

    Cada cópia sorteia: faixa do alto-falante (graves cortados em 100–300 Hz,
    agudos em 4–7 kHz), ruído de fundo (SNR 10–30 dB) e, com 50% de chance cada,
    saturação (AGC/alto-falante no limite) e quantização de 12 bits. Isso reduz
    a diferença entre o áudio limpo dos datasets e o captado na demonstração.
    """
    filtro = butter(4, [rng.uniform(100, 300), rng.uniform(4000, 7000)], btype="bandpass", fs=TAXA, output="sos")
    x = sosfilt(filtro, sinal).astype(np.float32)
    snr_db = rng.uniform(10, 30)
    x = x + rng.normal(0, rms(x) / (10 ** (snr_db / 20)) + 1e-6, len(x)).astype(np.float32)
    if rng.random() < 0.5:
        ganho = rng.uniform(1.0, 3.0)
        x = np.tanh(ganho * x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)
    if rng.random() < 0.5:
        x = (np.round(x / (np.max(np.abs(x)) + 1e-9) * 2048) / 2048).astype(np.float32)
    return normalizar(x)


_FILTRO_CELULAR = butter(4, [250, 5000], btype="bandpass", fs=TAXA, output="sos")


def simular_captura(sinal, rng):
    """Degradação usada SÓ para avaliar (não para treinar): celular + MAX9814 + ADC.

    Parâmetros FIXOS (250–5000 Hz, ruído com SNR de 12 dB, saturação leve e 12 bits),
    aplicados a trechos de teste que o modelo nunca viu.
    """
    x = sosfilt(_FILTRO_CELULAR, sinal).astype(np.float32)
    x = x + rng.normal(0, rms(x) / (10 ** (12 / 20)) + 1e-6, len(x)).astype(np.float32)
    x = np.tanh(2.0 * x / (np.max(np.abs(x)) + 1e-9)) * 0.8  # saturação leve (AGC/alto-falante)
    x = np.round(x * 2048) / 2048                            # 12 bits, como o ADC do ESP32
    return normalizar(x.astype(np.float32))


def salvar_wav(caminho, sinal):
    """Grava float32 [-1, 1] como WAV PCM 16-bit mono 16 kHz."""
    sf.write(str(caminho), np.clip(sinal, -1, 1), TAXA, subtype="PCM_16")

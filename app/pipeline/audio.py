"""Extracción de audio con FFmpeg (mono, 16 kHz) para minimizar tamaño/costo."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def build_extract_audio_cmd(source: Path, dest: Path) -> list[str]:
    """Construye el comando FFmpeg para extraer audio mono a 16 kHz (WAV PCM).

    Args:
        source: video de entrada.
        dest: ruta del WAV de salida.

    Returns:
        Lista de argumentos lista para ``subprocess.run``.
    """
    return [
        "ffmpeg",
        "-y",                 # sobrescribir sin preguntar
        "-i", str(source),
        "-vn",                # sin video
        "-ac", "1",           # mono
        "-ar", "16000",       # 16 kHz
        "-c:a", "pcm_s16le",  # WAV PCM 16-bit
        str(dest),
    ]


def probe_duration(source: Path) -> float:
    """Devuelve la duración del video en segundos usando ffprobe.

    Args:
        source: archivo de video.

    Returns:
        Duración en segundos (0.0 si no se puede determinar).
    """
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def probe_resolution(source: Path) -> tuple[int, int]:
    """Devuelve (ancho, alto) del primer stream de video (o 1080x1920 si falla)."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x", str(source),
        ],
        capture_output=True, text=True,
    )
    try:
        w, h = proc.stdout.strip().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1080, 1920


def extract_audio(source: Path, dest: Path) -> Path:
    """Extrae el audio de ``source`` a ``dest`` usando FFmpeg.

    Args:
        source: video de entrada.
        dest: ruta del WAV de salida.

    Returns:
        La ruta ``dest`` del audio extraído.

    Raises:
        RuntimeError: si FFmpeg falla.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_extract_audio_cmd(source, dest)
    logger.info("Extrayendo audio: %s -> %s", source.name, dest.name)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falló al extraer audio: {proc.stderr[-800:]}")
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError("El audio extraído está vacío.")
    return dest

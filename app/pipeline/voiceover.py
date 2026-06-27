"""Pegar la voz generada sobre un video con FFmpeg.

Dos modos:
- REEMPLAZAR la pista de audio del video por la voz (``-map 0:v -map 1:a``).
- MEZCLAR la voz con el audio/música de fondo del video (filtro ``amix``),
  bajando un poco el fondo para que la voz se entienda.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.pipeline import audio as audio_probe

logger = logging.getLogger(__name__)

# Audio de salida común (AAC estéreo, buena calidad para voz).
_AUDIO_ENC = ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]


def build_pegar_voz_cmd(video: Path, voz: Path, salida: Path) -> list[str]:
    """REEMPLAZA el audio del video por la voz. El video se copia (sin recodificar)."""
    return [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(voz),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", *_AUDIO_ENC,
        "-shortest", str(salida),
    ]


def build_mezclar_voz_cmd(
    video: Path, voz: Path, salida: Path, *, vol_fondo: float = 0.25,
) -> list[str]:
    """MEZCLA la voz con el audio de fondo del video (amix), bajando el fondo.

    Requiere que el video TENGA audio; si no, usa ``build_pegar_voz_cmd``.
    """
    filtro = (
        f"[0:a]volume={vol_fondo}[bg];"
        f"[bg][1:a]amix=inputs=2:duration=longest:dropout_transition=0[a]"
    )
    return [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(voz),
        "-filter_complex", filtro,
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", *_AUDIO_ENC,
        "-shortest", str(salida),
    ]


def pegar_voz_al_video(
    video: Path, voz: Path, salida: Path, *, mezclar: bool = False,
    vol_fondo: float = 0.25,
) -> Path:
    """Pega ``voz`` sobre ``video`` y devuelve ``salida``.

    Args:
        mezclar: si True, mezcla la voz con el audio de fondo del video; si False
            (o si el video no tiene audio), reemplaza el audio por la voz.

    Raises:
        RuntimeError: si FFmpeg falla o la salida queda vacía.
    """
    salida.parent.mkdir(parents=True, exist_ok=True)
    usar_mezcla = mezclar and audio_probe.has_audio(video)
    if mezclar and not usar_mezcla:
        logger.info("El video no tiene audio: se reemplaza en vez de mezclar.")
    cmd = (build_mezclar_voz_cmd(video, voz, salida, vol_fondo=vol_fondo)
           if usar_mezcla else build_pegar_voz_cmd(video, voz, salida))
    logger.info("Pegando voz al video (%s): %s",
                "mezcla" if usar_mezcla else "reemplazo", salida.name)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falló al pegar la voz: {proc.stderr[-800:]}")
    if not salida.exists() or salida.stat().st_size == 0:
        raise RuntimeError("El video con voz quedó vacío.")
    return salida

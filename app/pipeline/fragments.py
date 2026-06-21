"""Construcción del pool de fragmentos a partir de TODOS los videos del lote.

Los fragmentos tienen duración VARIABLE (entre ``beat_min`` y ``beat_max``), de
modo que la imagen cambia a un ritmo irregular y natural. Se trocea cada video y
se intercalan en ronda para que fragmentos consecutivos vengan de videos
distintos (mezcla natural).
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.transcribe import Segment

logger = logging.getLogger(__name__)

# Duraciones permitidas (pasos de 0.5s) dentro del rango pedido.
_STEP = 0.5


@dataclass
class VideoSource:
    """Un video del lote con sus metadatos y transcripción."""

    id: int
    path: Path
    duration: float
    name: str = ""
    segments: list[Segment] = field(default_factory=list)


@dataclass(frozen=True)
class Beat:
    """Un fragmento: de qué video, ruta, segundo de inicio y duración."""

    video_id: int
    source: Path
    start: float
    dur: float

    def key(self) -> tuple[int, int, int]:
        """Clave estable para deduplicar/cachear (video + start + dur en ms)."""
        return (self.video_id, int(round(self.start * 1000)), int(round(self.dur * 1000)))


def _durations(beat_min: float, beat_max: float) -> list[float]:
    """Lista de duraciones candidatas en pasos de 0.5s dentro del rango."""
    vals: list[float] = []
    d = beat_min
    while d <= beat_max + 1e-6:
        vals.append(round(d, 3))
        d += _STEP
    return vals or [beat_min]


def video_beats(
    video: VideoSource,
    rng: random.Random,
    beat_min: float,
    beat_max: float,
) -> list[Beat]:
    """Trocea un video en fragmentos no solapados de duración variable."""
    choices = _durations(beat_min, beat_max)
    beats: list[Beat] = []
    t = 0.0
    while t + beat_min <= video.duration + 1e-6:
        # Duración que quepa en lo que queda del video.
        restante = video.duration - t
        posibles = [d for d in choices if d <= restante + 1e-6]
        if not posibles:
            break
        dur = rng.choice(posibles)
        beats.append(Beat(video_id=video.id, source=video.path,
                          start=round(t, 3), dur=dur))
        t += dur
    return beats


def build_pool(
    videos: list[VideoSource],
    rng: random.Random,
    beat_min: float,
    beat_max: float,
) -> list[Beat]:
    """Construye el pool de fragmentos intercalando los videos en ronda.

    El intercalado hace que fragmentos consecutivos provengan de videos
    diferentes, garantizando que cualquier ventana del pool mezcle varios videos.
    """
    per_video = [video_beats(v, rng, beat_min, beat_max) for v in videos]
    pool: list[Beat] = []
    idx = 0
    while True:
        added = False
        for beats in per_video:
            if idx < len(beats):
                pool.append(beats[idx])
                added = True
        if not added:
            break
        idx += 1
    logger.info("Pool de fragmentos: %d beats de %d videos", len(pool), len(videos))
    return pool

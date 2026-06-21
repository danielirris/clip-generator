"""Construcción del pool de fragmentos a partir de TODOS los videos del lote.

El cuerpo de los clips se rellena con estos fragmentos (sin filtro estricto de
"impacto"). Se trocea cada video en beats de 2s y se intercalan en ronda para
que fragmentos consecutivos vengan de videos distintos (mezcla natural).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.transcribe import Segment

logger = logging.getLogger(__name__)


@dataclass
class VideoSource:
    """Un video del lote con sus metadatos y transcripción."""

    id: int
    path: Path
    duration: float
    segments: list[Segment] = field(default_factory=list)


@dataclass(frozen=True)
class Beat:
    """Un fragmento de 2s: de qué video, en qué ruta y en qué segundo empieza."""

    video_id: int
    source: Path
    start: float

    def key(self) -> tuple[int, int]:
        """Clave estable para deduplicar/cachear (video + start en ms)."""
        return (self.video_id, int(round(self.start * 1000)))


def video_beats(video: VideoSource, beat_s: float) -> list[Beat]:
    """Trocea un video en beats de ``beat_s`` segundos no solapados."""
    beats: list[Beat] = []
    t = 0.0
    while t + beat_s <= video.duration + 1e-6:
        beats.append(Beat(video_id=video.id, source=video.path, start=round(t, 3)))
        t += beat_s
    return beats


def build_pool(videos: list[VideoSource], beat_s: float) -> list[Beat]:
    """Construye el pool de fragmentos intercalando los videos en ronda.

    El intercalado (round-robin) hace que fragmentos consecutivos provengan de
    videos diferentes, garantizando que cualquier ventana del pool mezcle varios
    videos.

    Args:
        videos: videos del lote (con duración).
        beat_s: duración de cada beat.

    Returns:
        Lista de ``Beat`` intercalada por video.
    """
    per_video = [video_beats(v, beat_s) for v in videos]
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
    logger.info(
        "Pool de fragmentos: %d beats de %d videos", len(pool), len(videos)
    )
    return pool

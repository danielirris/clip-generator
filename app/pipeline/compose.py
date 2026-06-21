"""Composición de varios clips combinando ganchos + cuerpo del pool.

Cada clip = [ganchos impactantes al inicio] + [cuerpo con fragmentos variados de
TODOS los videos]. Los N clips se generan con desplazamientos distintos del pool
para que sean combinaciones diferentes entre sí.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.pipeline.analyze import Moment
from app.pipeline.fragments import Beat, VideoSource

logger = logging.getLogger(__name__)


def _window(items: list[Beat], offset: int, length: int) -> list[Beat]:
    """Toma ``length`` elementos desde ``offset``, dando la vuelta (wrap)."""
    if not items:
        return []
    return [items[(offset + i) % len(items)] for i in range(length)]


def build_hook_beats(
    moments: list[Moment],
    videos: list[VideoSource],
    beat_s: float,
) -> list[Beat]:
    """Convierte los momentos de gancho en beats (el inicio de cada momento).

    Si no hay momentos (sin transcripción), usa el inicio de los primeros videos
    como ganchos por defecto.
    """
    hooks: list[Beat] = []
    for m in moments:
        if 0 <= m.video_id < len(videos):
            v = videos[m.video_id]
            start = max(0.0, min(m.start, max(0.0, v.duration - beat_s)))
            hooks.append(Beat(video_id=v.id, source=v.path, start=round(start, 3)))

    if not hooks:
        # Ganchos por defecto: el arranque de los primeros videos.
        for v in videos:
            hooks.append(Beat(video_id=v.id, source=v.path, start=0.0))
        logger.info("Sin ganchos de IA; usando el inicio de los primeros videos.")
    return hooks


def compose_clips(
    pool: list[Beat],
    moments: list[Moment],
    videos: list[VideoSource],
    *,
    num_clips: int,
    total_beats: int,
    hook_beats: int,
    beat_s: float,
) -> list[list[Beat]]:
    """Compone ``num_clips`` listas de beats (una por clip).

    Args:
        pool: pool de fragmentos del cuerpo (intercalado por video).
        moments: ganchos detectados por la IA (puede estar vacío).
        videos: videos del lote (para mapear ganchos a su ruta).
        num_clips: cuántos clips generar.
        total_beats: beats por clip (p.ej. 24).
        hook_beats: cuántos beats de gancho al inicio de cada clip.
        beat_s: duración de cada beat.

    Returns:
        Lista de clips; cada clip es una lista de ``Beat`` de longitud
        ``total_beats`` (o menos si no hay material en absoluto).

    Raises:
        RuntimeError: si no hay ningún fragmento disponible.
    """
    if not pool:
        raise RuntimeError("No hay fragmentos para componer los clips.")

    hook_pool = build_hook_beats(moments, videos, beat_s)
    hook_n = max(0, min(hook_beats, total_beats))
    body_n = total_beats - hook_n

    clips: list[list[Beat]] = []
    for k in range(num_clips):
        hooks = _window(hook_pool, k * max(1, hook_n), hook_n) if hook_n else []
        # Desplazamos el cuerpo body_n posiciones por clip -> selección distinta.
        body = _window(pool, k * body_n, body_n)
        clip = hooks + body
        clips.append(clip[:total_beats])
        videos_en_clip = len({b.video_id for b in clip})
        logger.info(
            "Clip %d/%d: %d beats, %d videos distintos",
            k + 1, num_clips, len(clip), videos_en_clip,
        )
    return clips


def unique_beats(clips: list[list[Beat]]) -> list[Beat]:
    """Devuelve los beats únicos usados en todos los clips (para renderizar 1 vez)."""
    seen: dict[tuple[int, int], Beat] = {}
    for clip in clips:
        for beat in clip:
            seen.setdefault(beat.key(), beat)
    return list(seen.values())

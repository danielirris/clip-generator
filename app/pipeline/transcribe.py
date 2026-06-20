"""Transcripción con Groq Whisper (large v3 turbo) -> segmentos con timestamps."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.retry import with_retries

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    """Un segmento de transcripción con sus tiempos en segundos."""

    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


def parse_segments(raw: Any) -> list[Segment]:
    """Normaliza la respuesta de Groq (verbose_json) a una lista de ``Segment``.

    Acepta tanto objetos del SDK (con atributos) como diccionarios, de modo que
    sea fácil de testear con datos simulados.

    Args:
        raw: respuesta de la API (objeto o dict) con clave/atributo ``segments``.

    Returns:
        Lista de segmentos con tiempos saneados (start <= end).
    """
    if isinstance(raw, dict):
        segments = raw.get("segments") or []
    else:
        segments = getattr(raw, "segments", None) or []

    result: list[Segment] = []
    for seg in segments:
        if isinstance(seg, dict):
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
            text = str(seg.get("text", "")).strip()
        else:
            start = float(getattr(seg, "start", 0.0))
            end = float(getattr(seg, "end", 0.0))
            text = str(getattr(seg, "text", "")).strip()
        if end < start:
            end = start
        if text:
            result.append(Segment(start=start, end=end, text=text))
    return result


def transcribe_audio(audio_path: Path) -> list[Segment]:
    """Transcribe un archivo de audio con Groq Whisper devolviendo segmentos.

    Args:
        audio_path: ruta del WAV (mono, 16 kHz).

    Returns:
        Lista de ``Segment`` con timestamps.

    Raises:
        RuntimeError: si la API no devuelve segmentos utilizables.
    """
    from groq import Groq  # import perezoso para no requerir el SDK en tests

    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY no está configurada.")

    client = Groq(api_key=settings.groq_api_key)
    logger.info("Transcribiendo con Groq (%s)", settings.groq_whisper_model)

    def _call() -> Any:
        with open(audio_path, "rb") as fh:
            return client.audio.transcriptions.create(
                file=(audio_path.name, fh.read()),
                model=settings.groq_whisper_model,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

    raw = with_retries(_call, what="transcripción Groq")
    segments = parse_segments(raw)
    if not segments:
        raise RuntimeError("La transcripción no devolvió segmentos.")
    logger.info("Transcripción completada: %d segmentos", len(segments))
    return segments

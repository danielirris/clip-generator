"""Transcripción con OpenAI Whisper -> segmentos con timestamps."""
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


@dataclass
class Word:
    """Una palabra de la transcripción con sus tiempos (para sincronía fina)."""

    word: str
    start: float
    end: float

    def to_dict(self) -> dict[str, Any]:
        return {"word": self.word, "start": self.start, "end": self.end}


def parse_words(raw: Any) -> list[Word]:
    """Normaliza la respuesta de OpenAI (verbose_json, granularity=word)."""
    if isinstance(raw, dict):
        words = raw.get("words") or []
    else:
        words = getattr(raw, "words", None) or []
    result: list[Word] = []
    for w in words:
        if isinstance(w, dict):
            text = str(w.get("word", "")).strip()
            start = float(w.get("start", 0.0))
            end = float(w.get("end", start))
        else:
            text = str(getattr(w, "word", "")).strip()
            start = float(getattr(w, "start", 0.0))
            end = float(getattr(w, "end", start))
        if end < start:
            end = start
        if text:
            result.append(Word(word=text, start=start, end=end))
    return result


def parse_segments(raw: Any) -> list[Segment]:
    """Normaliza la respuesta de OpenAI (verbose_json) a una lista de ``Segment``.

    Acepta objetos del SDK (con atributos) o diccionarios, para poder testear
    con datos simulados.

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
    """Transcribe un archivo de audio con OpenAI Whisper devolviendo segmentos.

    No lanza si no hay voz: en ese caso devuelve una lista vacía (los videos con
    solo música simplemente no llevan subtítulos).

    Args:
        audio_path: ruta del WAV (mono, 16 kHz).

    Returns:
        Lista de ``Segment`` con timestamps (posiblemente vacía).
    """
    from openai import OpenAI  # import perezoso para no requerir el SDK en tests

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY no está configurada.")

    client = OpenAI(api_key=settings.openai_api_key)
    logger.info("Transcribiendo con OpenAI (%s): %s",
                settings.openai_transcribe_model, audio_path.name)

    def _call() -> Any:
        with open(audio_path, "rb") as fh:
            return client.audio.transcriptions.create(
                file=fh,
                model=settings.openai_transcribe_model,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

    raw = with_retries(_call, what="transcripción OpenAI")
    segments = parse_segments(raw)
    logger.info("Transcripción de %s: %d segmentos", audio_path.name, len(segments))
    return segments


def transcribe_words(audio_path: Path) -> list[Word]:
    """Transcribe con timestamps a nivel de PALABRA (para sincronía de animaciones).

    Returns:
        Lista de ``Word`` (posiblemente vacía si no hay voz).
    """
    from openai import OpenAI  # import perezoso

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY no está configurada.")

    client = OpenAI(api_key=settings.openai_api_key)
    logger.info("Transcribiendo (palabras) con OpenAI: %s", audio_path.name)

    def _call() -> Any:
        with open(audio_path, "rb") as fh:
            return client.audio.transcriptions.create(
                file=fh,
                model=settings.openai_transcribe_model,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )

    raw = with_retries(_call, what="transcripción OpenAI (palabras)")
    words = parse_words(raw)
    logger.info("Transcripción de %s: %d palabras", audio_path.name, len(words))
    return words

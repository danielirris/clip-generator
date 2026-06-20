"""Análisis con Gemini 2.5 Flash-Lite: detecta los momentos más impactantes."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.pipeline.transcribe import Segment
from app.retry import with_retries

logger = logging.getLogger(__name__)


@dataclass
class Clip:
    """Un momento impactante propuesto por la IA."""

    start: float
    end: float
    score: float
    razon: str


SYSTEM_INSTRUCTION = (
    "Eres un editor experto de clips virales para redes sociales (Reels, TikTok, "
    "Shorts). Analizas transcripciones e identificas los momentos MÁS impactantes."
)

_PROMPT_TEMPLATE = """\
A partir de la siguiente transcripción con timestamps (en segundos), identifica
los momentos MÁS impactantes para montar un clip vertical corto.

Criterios de "impactante" (priorízalos):
- Ganchos de apertura potentes.
- Frases citables, contundentes o memorables.
- Picos emocionales (sorpresa, indignación, inspiración).
- Preguntas retóricas que enganchan.
- Datos o afirmaciones sorprendentes.
- Momentos de tensión, conflicto o humor.
- Conclusiones fuertes o llamados a la acción.

Devuelve EXCLUSIVAMENTE JSON válido (sin markdown, sin ``` , sin texto extra)
con esta forma EXACTA:
{{"clips": [{{"start": <segundos>, "end": <segundos>, "score": <0-100>, "razon": "<por qué es impactante>"}}]}}

Reglas:
- "start" y "end" en segundos (números), dentro del rango de la transcripción.
- "score" entero 0-100. Ordena el array por "score" DESCENDENTE.
- Devuelve entre 5 y 40 clips si el material lo permite.

TRANSCRIPCIÓN:
{transcript}
"""

_STRICT_SUFFIX = (
    "\n\nIMPORTANTE: tu respuesta anterior no fue JSON válido. Responde ÚNICAMENTE "
    "con el objeto JSON, empezando por '{' y terminando por '}', sin ningún otro texto."
)


def format_transcript(segments: list[Segment]) -> str:
    """Formatea los segmentos como líneas '[inicio-fin] texto' para el prompt."""
    return "\n".join(
        f"[{seg.start:.1f}-{seg.end:.1f}] {seg.text}" for seg in segments
    )


def build_prompt(segments: list[Segment], *, strict: bool = False) -> str:
    """Construye el prompt para Gemini a partir de los segmentos."""
    prompt = _PROMPT_TEMPLATE.format(transcript=format_transcript(segments))
    if strict:
        prompt += _STRICT_SUFFIX
    return prompt


def _strip_code_fences(text: str) -> str:
    """Elimina posibles vallas ```json ... ``` y espacios alrededor del JSON."""
    text = text.strip()
    # Quita una valla de apertura tipo ```json o ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_clips_json(text: str) -> list[Clip]:
    """Parsea de forma robusta el JSON de Gemini a una lista de ``Clip``.

    Limpia vallas de código y, como último recurso, extrae el primer objeto
    JSON balanceado del texto.

    Args:
        text: respuesta cruda del modelo.

    Returns:
        Lista de clips ordenada por score descendente.

    Raises:
        ValueError: si no se puede obtener un JSON válido con clips.
    """
    cleaned = _strip_code_fences(text)
    data: Any
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Último recurso: extraer el primer bloque {...} del texto.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("La respuesta de Gemini no contiene JSON.")
        data = json.loads(match.group(0))

    raw_clips = data.get("clips") if isinstance(data, dict) else None
    if not isinstance(raw_clips, list):
        raise ValueError("El JSON no contiene una lista 'clips'.")

    clips: list[Clip] = []
    for item in raw_clips:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        score = float(item.get("score", 0) or 0)
        razon = str(item.get("razon", "")).strip()
        clips.append(Clip(start=start, end=end, score=score, razon=razon))

    if not clips:
        raise ValueError("El JSON de Gemini no contiene clips válidos.")

    clips.sort(key=lambda c: c.score, reverse=True)
    return clips


def analyze_segments(segments: list[Segment]) -> list[Clip]:
    """Pide a Gemini los mejores momentos; reintenta una vez si el JSON es inválido.

    Args:
        segments: segmentos de la transcripción.

    Returns:
        Lista de ``Clip`` ordenada por score descendente.

    Raises:
        RuntimeError: si no hay clave de API o el modelo no devuelve JSON válido.
    """
    from google import genai  # import perezoso
    from google.genai import types

    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY no está configurada.")

    client = genai.Client(api_key=settings.gemini_api_key)

    def _generate(strict: bool) -> str:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.4,
        )
        resp = with_retries(
            lambda: client.models.generate_content(
                model=settings.gemini_model,
                contents=build_prompt(segments, strict=strict),
                config=config,
            ),
            what="análisis Gemini",
        )
        return resp.text or ""

    logger.info("Analizando con Gemini (%s)", settings.gemini_model)
    text = _generate(strict=False)
    try:
        clips = parse_clips_json(text)
    except ValueError:
        logger.warning("JSON inválido de Gemini; reintentando con prompt estricto.")
        text = _generate(strict=True)
        clips = parse_clips_json(text)  # si vuelve a fallar, propaga la excepción

    logger.info("Gemini devolvió %d clips", len(clips))
    return clips

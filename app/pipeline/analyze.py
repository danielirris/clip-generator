"""Análisis con OpenAI (gpt-4o-mini): detecta los momentos de GANCHO (hooks).

Los momentos impactantes solo se usan para el ARRANQUE de cada clip; el resto
del clip se rellena con fragmentos variados de todos los videos (sin filtro
estricto). Por eso aquí solo buscamos los mejores ganchos.
"""
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
class Moment:
    """Un momento de gancho propuesto por la IA, referido a un video del lote."""

    video_id: int
    start: float
    end: float
    score: float
    razon: str


SYSTEM_INSTRUCTION = (
    "Eres un editor experto de clips virales (Reels, TikTok, Shorts). Identificas "
    "los GANCHOS de apertura más potentes para enganchar en los primeros segundos."
)

_PROMPT_TEMPLATE = """\
Tienes la transcripción de VARIOS videos (cada línea indica [video, inicio-fin]).
Identifica los mejores GANCHOS de apertura: frases que enganchen en los primeros
segundos (promesas, preguntas, datos sorprendentes, frases contundentes, humor).

Devuelve EXCLUSIVAMENTE JSON válido (sin markdown, sin ``` , sin texto extra):
{{"momentos": [{{"video": <indice>, "start": <segundos>, "end": <segundos>, "score": <0-100>, "razon": "<por qué engancha>"}}]}}

Reglas:
- "video" es el índice entero que aparece entre corchetes.
- "start"/"end" en segundos dentro de ese video. Ordena por "score" DESC.
- Devuelve entre 5 y 20 ganchos si el material lo permite.

TRANSCRIPCIÓN:
{transcript}
"""

_STRICT_SUFFIX = (
    "\n\nIMPORTANTE: responde ÚNICAMENTE con el objeto JSON, empezando por '{' y "
    "terminando por '}', sin ningún otro texto."
)


def format_multi_transcript(videos_segments: list[list[Segment]]) -> str:
    """Formatea los segmentos de todos los videos como líneas etiquetadas.

    Cada línea: ``[<video>, <inicio>-<fin>] texto``.
    """
    lines: list[str] = []
    for vid, segments in enumerate(videos_segments):
        for seg in segments:
            lines.append(f"[{vid}, {seg.start:.1f}-{seg.end:.1f}] {seg.text}")
    return "\n".join(lines)


def build_prompt(videos_segments: list[list[Segment]], *, strict: bool = False) -> str:
    """Construye el prompt para el modelo a partir de los segmentos de todos los videos."""
    prompt = _PROMPT_TEMPLATE.format(transcript=format_multi_transcript(videos_segments))
    if strict:
        prompt += _STRICT_SUFFIX
    return prompt


def _strip_code_fences(text: str) -> str:
    """Elimina posibles vallas ```json ... ``` y espacios alrededor del JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_moments_json(text: str, num_videos: int | None = None) -> list[Moment]:
    """Parsea de forma robusta el JSON del modelo a una lista de ``Moment``.

    Args:
        text: respuesta cruda del modelo.
        num_videos: si se indica, descarta momentos con un índice de video fuera
            de rango.

    Returns:
        Lista de momentos ordenada por score descendente.

    Raises:
        ValueError: si no se puede obtener un JSON válido con momentos.
    """
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("La respuesta del modelo no contiene JSON.")
        data = json.loads(match.group(0))

    raw = data.get("momentos") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise ValueError("El JSON no contiene una lista 'momentos'.")

    moments: list[Moment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            video_id = int(item["video"])
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        if num_videos is not None and not (0 <= video_id < num_videos):
            continue
        moments.append(
            Moment(
                video_id=video_id,
                start=start,
                end=end,
                score=float(item.get("score", 0) or 0),
                razon=str(item.get("razon", "")).strip(),
            )
        )

    if not moments:
        raise ValueError("El JSON no contiene momentos válidos.")

    moments.sort(key=lambda m: m.score, reverse=True)
    return moments


def analyze_hooks(videos_segments: list[list[Segment]]) -> list[Moment]:
    """Pide a OpenAI los mejores ganchos; reintenta una vez si el JSON es inválido.

    Si no hay transcripción utilizable (videos solo con música), devuelve una
    lista vacía y el compositor usará ganchos por defecto (el inicio de los
    primeros videos).

    Args:
        videos_segments: lista por video de sus segmentos de transcripción.

    Returns:
        Lista de ``Moment`` ordenada por score (posiblemente vacía).
    """
    from openai import OpenAI  # import perezoso

    if not any(videos_segments):
        logger.info("Sin transcripción: se omite el análisis de ganchos.")
        return []

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY no está configurada.")

    client = OpenAI(api_key=settings.openai_api_key)
    num_videos = len(videos_segments)

    def _generate(strict: bool) -> str:
        resp = with_retries(
            lambda: client.chat.completions.create(
                model=settings.openai_analyze_model,
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": build_prompt(videos_segments, strict=strict)},
                ],
                response_format={"type": "json_object"},
                temperature=0.4,
            ),
            what="análisis OpenAI",
        )
        return resp.choices[0].message.content or ""

    logger.info("Analizando ganchos con OpenAI (%s)", settings.openai_analyze_model)
    text = _generate(strict=False)
    try:
        moments = parse_moments_json(text, num_videos)
    except ValueError:
        logger.warning("JSON inválido; reintentando con prompt estricto.")
        try:
            text = _generate(strict=True)
            moments = parse_moments_json(text, num_videos)
        except ValueError:
            logger.warning("No se pudieron extraer ganchos; se usarán por defecto.")
            return []

    logger.info("OpenAI devolvió %d ganchos", len(moments))
    return moments


# --------------------------------------------------------------------------- #
# Director de estilo: entiende el tema y define la tipología de subtítulos
# --------------------------------------------------------------------------- #
_DEFAULT_STYLE = {
    "tema": "",
    "accent": "#FFD400",      # color de palabras resaltadas / activas
    "secondary": "#00E0FF",
    "emphasis": [],           # palabras clave a resaltar
    "intensidad": 70,         # 0-100
}


def analyze_ad_style(transcript: str, prompt_text: str = "") -> dict:
    """Pide a la IA un 'estilo' para los subtítulos en función del TEMA del video.

    Devuelve un dict con: tema, accent (hex), secondary (hex), emphasis (lista de
    palabras clave a resaltar) e intensidad (0-100). Ante cualquier fallo devuelve
    un estilo por defecto (nunca rompe el render).
    """
    from openai import OpenAI  # import perezoso

    if not transcript.strip():
        return dict(_DEFAULT_STYLE)

    settings = get_settings()
    if not settings.openai_api_key:
        return dict(_DEFAULT_STYLE)

    client = OpenAI(api_key=settings.openai_api_key)
    sys = (
        "Eres director de arte de video para anuncios verticales (Reels/TikTok). "
        "Defines la TIPOLOGÍA de subtítulos según el TEMA del contenido."
    )
    user = f"""\
A partir de la transcripción y los lineamientos, define el estilo de los subtítulos.
Devuelve EXCLUSIVAMENTE JSON válido con esta forma:
{{"tema": "<tema en pocas palabras>", "accent": "<color hex llamativo acorde al tema>",
"secondary": "<color hex secundario>", "emphasis": ["<5-15 palabras clave del texto a resaltar>"],
"intensidad": <0-100>}}

Reglas:
- "accent"/"secondary" en formato #RRGGBB, alto contraste sobre texto blanco con contorno negro.
- "emphasis": palabras EXACTAS que aparezcan en el texto (productos, beneficios, cifras, CTA).
- El color y la intensidad deben pegar con el tema (salud=verde, lujo=dorado, tecnología=azul, etc.).

LINEAMIENTOS:
{prompt_text[:2000]}

TRANSCRIPCIÓN:
{transcript[:4000]}
"""
    try:
        resp = with_retries(
            lambda: client.chat.completions.create(
                model=settings.openai_analyze_model,
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.5,
            ),
            what="estilo OpenAI", attempts=2,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo obtener el estilo; se usa el de por defecto.")
        return dict(_DEFAULT_STYLE)

    style = dict(_DEFAULT_STYLE)
    if isinstance(data, dict):
        if isinstance(data.get("tema"), str):
            style["tema"] = data["tema"][:80]
        for key in ("accent", "secondary"):
            v = str(data.get(key, "")).strip()
            if re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
                style[key] = v.upper()
        if isinstance(data.get("emphasis"), list):
            style["emphasis"] = [str(w).strip() for w in data["emphasis"][:15] if str(w).strip()]
        try:
            style["intensidad"] = max(0, min(100, int(data.get("intensidad", 70))))
        except (TypeError, ValueError):
            pass
    logger.info("Estilo IA: tema=%r accent=%s emphasis=%d",
                style["tema"], style["accent"], len(style["emphasis"]))
    return style

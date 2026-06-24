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
{prompt_text[:4000]}

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


# --------------------------------------------------------------------------- #
# Director de EDICIÓN: la IA decide placement (full-screen, píldoras, emojis)
# en función de la voz (Regla 0). Lee palabras con timestamps.
# --------------------------------------------------------------------------- #
_SUBTITLE_STYLES = {"pop", "karaoke", "box", "punch", "color"}


def _default_plan(words) -> dict:
    plan = {
        "tema": "", "accent": "#FFD400", "secondary": "#00E0FF",
        "subtitle_style": "pop", "intensidad": 70,
        "emphasis": [], "fullscreen": [], "pills": [], "emojis": [],
    }
    # Intro full-screen por defecto con las primeras palabras.
    if words:
        hook = " ".join(w.word for w in words[:4])
        plan["fullscreen"] = [{"at": 0.0, "top": "", "key": hook, "sub": ""}]
    return plan


def _spaced(items: list[dict], key: str, gap: float, limit: int) -> list[dict]:
    """Ordena por ``key``, fuerza separación mínima y limita la cantidad."""
    out: list[dict] = []
    for it in sorted(items, key=lambda d: d.get(key, 0.0)):
        if out and it[key] - out[-1][key] < gap:
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return out


def plan_ad(words, duration: float, prompt_text: str = "") -> dict:
    """Pide a la IA un PLAN de edición completo a partir de la voz (con tiempos).

    Devuelve dict con: tema, accent, secondary, subtitle_style, intensidad,
    emphasis, fullscreen[{at,top,key,sub}], pills[{start,end,text,emoji}],
    emojis[{at,emoji}]. Robusto: ante fallo devuelve un plan por defecto.
    """
    from openai import OpenAI  # import perezoso

    if not words:
        return _default_plan(words)
    settings = get_settings()
    if not settings.openai_api_key:
        return _default_plan(words)

    lines = "\n".join(f"[{w.start:.1f}] {w.word}" for w in words[:200])
    sys = (
        "Eres editor de video senior (Reels/TikTok). Construyes el video EN FUNCIÓN "
        "DE LA VOZ: cada gráfico responde a lo que se dice, en su segundo exacto."
    )
    user = f"""\
Tienes la transcripción con timestamps (segundos) y los lineamientos. Diseña el PLAN
de edición. Devuelve EXCLUSIVAMENTE JSON válido:
{{"tema":"<tema>","accent":"#RRGGBB","secondary":"#RRGGBB",
"subtitle_style":"pop|karaoke|box|punch|color","intensidad":<0-100>,
"emphasis":["<palabras clave del texto a resaltar>"],
"fullscreen":[{{"at":<seg>,"top":"<línea pequeña MAYÚS, opcional>","key":"<palabra/frase clave grande>","sub":"<subtítulo fino, opcional>"}}],
"pills":[{{"start":<seg>,"end":<seg>,"text":"<frase clave en MAYÚS>","emoji":"<emoji acorde>"}}],
"emojis":[{{"at":<seg>,"emoji":"<emoji>"}}]}}

Reglas:
- TODO sale del guion: el texto de cada gráfico es lo que dice la voz en ese momento.
- "at"/"start"/"end" en segundos dentro de [0, {duration:.1f}], tomados de los timestamps.
- fullscreen: 2-3 (uno al inicio ~0s, uno al centro, opcional antes del cierre).
- pills: 2-5 en las frases más relevantes; "end" cuando la voz termina la frase.
- emojis: 3-6, contextuales (🥛 leche, 🌱 natural, 💪 salud, 💰 dinero, ✨ beneficio...).
- accent vibrante de alto contraste acorde al tema; evita amarillo si el fondo es claro.
- No satures: cada elemento con propósito.

LINEAMIENTOS:
{prompt_text[:3000]}

TRANSCRIPCIÓN (timestamp en segundos):
{lines}
"""
    try:
        resp = with_retries(
            lambda: client_chat(settings, sys, user),
            what="plan de edición OpenAI", attempts=2,
        )
        data = json.loads(resp)
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo obtener el plan; se usa el de por defecto.")
        return _default_plan(words)

    plan = _default_plan(words)
    if not isinstance(data, dict):
        return plan
    if isinstance(data.get("tema"), str):
        plan["tema"] = data["tema"][:80]
    for k in ("accent", "secondary"):
        v = str(data.get(k, "")).strip()
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            plan[k] = v.upper()
    st = str(data.get("subtitle_style", "")).strip().lower()
    plan["subtitle_style"] = st if st in _SUBTITLE_STYLES else "pop"
    try:
        plan["intensidad"] = max(0, min(100, int(data.get("intensidad", 70))))
    except (TypeError, ValueError):
        pass
    if isinstance(data.get("emphasis"), list):
        plan["emphasis"] = [str(w).strip() for w in data["emphasis"][:15] if str(w).strip()]

    def _clamp(x):
        try:
            return max(0.0, min(float(duration), float(x)))
        except (TypeError, ValueError):
            return None

    fs = []
    for it in data.get("fullscreen", []) or []:
        if not isinstance(it, dict):
            continue
        at = _clamp(it.get("at"))
        key = str(it.get("key", "")).strip()
        if at is None or not key:
            continue
        fs.append({"at": round(at, 2), "top": str(it.get("top", "")).strip()[:40],
                   "key": key[:60], "sub": str(it.get("sub", "")).strip()[:80]})
    plan["fullscreen"] = _spaced(fs, "at", 2.0, 3) or plan["fullscreen"]

    pills = []
    for it in data.get("pills", []) or []:
        if not isinstance(it, dict):
            continue
        s, e = _clamp(it.get("start")), _clamp(it.get("end"))
        text = str(it.get("text", "")).strip()
        if s is None or not text:
            continue
        if e is None or e <= s:
            e = min(float(duration), s + 1.8)
        pills.append({"start": round(s, 2), "end": round(e, 2), "text": text[:42],
                      "emoji": str(it.get("emoji", "")).strip()[:4]})
    plan["pills"] = _spaced(pills, "start", 1.5, 5)

    emojis = []
    for it in data.get("emojis", []) or []:
        if not isinstance(it, dict):
            continue
        at = _clamp(it.get("at"))
        em = str(it.get("emoji", "")).strip()
        if at is None or not em:
            continue
        emojis.append({"at": round(at, 2), "emoji": em[:4]})
    plan["emojis"] = _spaced(emojis, "at", 1.2, 6)

    logger.info("Plan IA: tema=%r accent=%s style=%s fs=%d pills=%d emojis=%d",
                plan["tema"], plan["accent"], plan["subtitle_style"],
                len(plan["fullscreen"]), len(plan["pills"]), len(plan["emojis"]))
    return plan


def client_chat(settings, system: str, user: str) -> str:
    """Llamada de chat JSON reutilizable (devuelve el texto del mensaje)."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_analyze_model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0.5,
    )
    return resp.choices[0].message.content or "{}"

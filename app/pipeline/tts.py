"""Generación de voz por texto (TTS) con ElevenLabs.

El usuario escribe el guion (gancho + cuerpo + cierre), elige una voz de un
catálogo y la app genera un .mp3 con ElevenLabs (modelo multilingüe, español).
La clave se lee del entorno (``ELEVENLABS_API_KEY``); el frontend NUNCA la ve.

Se llama directamente a la API REST de ElevenLabs con ``httpx`` (ya es dependencia)
para no añadir paquetes. Equivale a usar el SDK oficial ``@elevenlabs/elevenlabs-js``.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.config import get_settings
from app.retry import with_retries

logger = logging.getLogger(__name__)

API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"

# --------------------------------------------------------------------------- #
# Catálogo de voces: nombre visible -> voice_id de ElevenLabs.
# El usuario elige por NOMBRE; internamente se usa el ID. (IDs públicos de las
# voces prediseñadas de ElevenLabs; todas funcionan con el modelo multilingüe.)
# --------------------------------------------------------------------------- #
VOCES: dict[str, str] = {
    "Sarah":  "EXAVITQu4vr4xnSDxMaL",   # femenina, cálida
    "Laura":  "FGY2WhTYpPnrIDTdsKH5",   # femenina, juvenil
    "Rachel": "21m00Tcm4TlvDq8ikWAM",   # femenina, narradora
    "Antoni": "ErXwobaYiN019PkySvjV",   # masculina, cercana
    "Josh":   "TxGEqnHWrfWFTfGW9XjX",   # masculina, profunda
    "Adam":   "pNInz6obpgDQGcFmaJgB",   # masculina, locutor
    "Bill":   "pqHfZKP75CvOlQylNhV4",   # masculina, madura
    "Charlie":"IKne3meq5aSn9XLyUdCD",   # masculina, natural
}

VELOCIDAD_MIN = 0.7
VELOCIDAD_MAX = 1.2


def listar_voces() -> list[str]:
    """Nombres de las voces disponibles (para el menú del usuario)."""
    return list(VOCES.keys())


def resolver_voice_id(voz: str | None) -> str:
    """Devuelve el voice_id a partir del nombre del catálogo.

    Si ``voz`` no está en el catálogo pero parece un voice_id directo, se usa tal
    cual; si está vacío, se usa la voz por defecto de la configuración.
    """
    if not voz:
        voz = get_settings().tts_voz_default
    if voz in VOCES:
        return VOCES[voz]
    # ¿Es ya un voice_id? (ElevenLabs usa ids alfanuméricos de ~20 chars.)
    if len(voz) >= 16 and voz.isalnum():
        return voz
    # Último recurso: la voz por defecto, o la primera del catálogo.
    return VOCES.get(get_settings().tts_voz_default) or next(iter(VOCES.values()))


def construir_voice_settings(
    velocidad: float,
    estabilidad: float | None,
    similitud: float | None,
) -> dict:
    """Arma ``voice_settings`` con ``speed`` (velocidad) y ajustes opcionales.

    ``velocidad`` se recorta a [0.7, 1.2] (valores > 1 aceleran).
    """
    settings = get_settings()
    vel = max(VELOCIDAD_MIN, min(VELOCIDAD_MAX, float(velocidad)))
    est = settings.tts_estabilidad_default if estabilidad is None else float(estabilidad)
    sim = settings.tts_similitud_default if similitud is None else float(similitud)
    return {
        "stability": max(0.0, min(1.0, est)),
        "similarity_boost": max(0.0, min(1.0, sim)),
        "speed": vel,
    }


def disponible() -> bool:
    """Indica si hay clave de ElevenLabs configurada."""
    return bool(get_settings().elevenlabs_api_key)


def generar_voz(
    texto: str,
    *,
    voz: str | None = None,
    velocidad: float | None = None,
    estabilidad: float | None = None,
    similitud: float | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Genera la voz del ``texto`` con ElevenLabs y devuelve la ruta del .mp3.

    Args:
        texto: el guion a locutar (gancho + cuerpo + cierre ya unidos).
        voz: nombre del catálogo ``VOCES`` (o un voice_id directo).
        velocidad: 0.7-1.2 (default de configuración, típicamente 1.1).
        estabilidad / similitud: ajustes opcionales de la voz (0-1).
        out_dir: carpeta donde escribir el .mp3 (default: storage/).

    Raises:
        RuntimeError: si no hay clave, el texto está vacío o falla la API.
    """
    import httpx  # import perezoso

    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY no está configurada en el servidor.")
    texto = (texto or "").strip()
    if not texto:
        raise RuntimeError("El texto del guion está vacío.")

    if velocidad is None:
        velocidad = settings.tts_velocidad_default
    voice_id = resolver_voice_id(voz)
    payload = {
        "text": texto,
        "model_id": settings.elevenlabs_model,
        "voice_settings": construir_voice_settings(velocidad, estabilidad, similitud),
    }
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }

    out_dir = out_dir or settings.storage_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"voz_ia_{uuid.uuid4().hex[:8]}.mp3"

    def _call() -> bytes:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{API_BASE}/{voice_id}", json=payload, headers=headers)
        if resp.status_code != 200:
            detalle = resp.text[:300]
            raise RuntimeError(f"ElevenLabs devolvió {resp.status_code}: {detalle}")
        if not resp.content:
            raise RuntimeError("ElevenLabs devolvió audio vacío.")
        return resp.content

    logger.info("Generando voz (ElevenLabs, voz=%s, vel=%.2f, %d chars)",
                voz or settings.tts_voz_default, velocidad, len(texto))
    audio = with_retries(_call, what="TTS ElevenLabs", attempts=2)
    dest.write_bytes(audio)
    logger.info("Voz generada: %s (%d KB)", dest.name, len(audio) // 1024)
    return dest

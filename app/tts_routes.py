"""Rutas de la API para texto a voz (TTS) con ElevenLabs.

- GET  /api/voces        -> catálogo de voces para el menú.
- POST /api/generar-voz  -> { texto, voz, velocidad, videoId?, mezclar? }
  Genera la voz y, si se indica ``videoId`` (un trabajo con video), la pega sobre
  ese video y devuelve el .mp4; si no, devuelve el .mp3 generado.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.pipeline import tts, voiceover

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/voces")
async def voces() -> dict:
    """Catálogo de voces disponibles (solo nombres; los IDs quedan en el servidor)."""
    return {"voces": tts.listar_voces(), "disponible": tts.disponible()}


@router.post("/api/generar-voz")
async def generar_voz(payload: dict = Body(...)) -> FileResponse:
    """Genera la voz del guion y (opcional) la pega sobre el video del trabajo.

    Body: ``{ texto, voz, velocidad, videoId?, mezclar? }``.
    """
    from app.jobs import manager  # import perezoso (evita ciclos)

    if not tts.disponible():
        raise HTTPException(status_code=503,
                            detail="Falta ELEVENLABS_API_KEY en el servidor.")
    texto = str(payload.get("texto", "")).strip()
    if not texto:
        raise HTTPException(status_code=400, detail="El texto del guion está vacío.")

    settings = get_settings()
    tmp_dir = settings.storage_dir / "tts"
    try:
        voz_mp3 = tts.generar_voz(
            texto,
            voz=payload.get("voz"),
            velocidad=payload.get("velocidad"),
            estabilidad=payload.get("estabilidad"),
            similitud=payload.get("similitud"),
            out_dir=tmp_dir,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    video_id = payload.get("videoId")
    if video_id:
        # Pegar la voz sobre el video del trabajo (su primer clip disponible).
        video = manager.clip_path(str(video_id), 1)
        if not video:
            raise HTTPException(status_code=404,
                                detail="No se encontró un video para ese videoId.")
        salida = tmp_dir / f"voz_video_{uuid.uuid4().hex[:8]}.mp4"
        try:
            voiceover.pegar_voz_al_video(
                video, voz_mp3, salida, mezclar=bool(payload.get("mezclar")),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return FileResponse(path=str(salida), media_type="video/mp4",
                            filename="video_con_voz.mp4")

    # Sin videoId: devolvemos la voz generada (para previsualizar/elegir).
    return FileResponse(path=str(voz_mp3), media_type="audio/mpeg",
                        filename="voz.mp3")

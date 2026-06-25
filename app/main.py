"""FastAPI: endpoints de la API, subida de videos y servidor web."""
from __future__ import annotations

import io
import logging
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, get_settings
from app.jobs import manager
from app import library

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("clip-generator")

settings = get_settings()

WEB_DIR = BASE_DIR / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

ALLOWED_EXT = {".mp4", ".mov", ".mkv"}
ALLOWED_AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
ALLOWED_OVERLAY_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif",
                       ".mp4", ".mov", ".webm", ".m4v"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranca el JobManager al iniciar la app."""
    settings.ensure_dirs()
    manager.start()
    logger.info("Aplicación iniciada (puerto %d).", settings.port)
    yield


app = FastAPI(title="clip-generator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Página de subida."""
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "max_upload_mb": settings.max_upload_mb,
            "num_clips": settings.num_clips,
        },
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Healthcheck para EasyPanel."""
    return JSONResponse({"status": "ok"})


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    """Página de Configuración: biblioteca de música libre de derechos."""
    return TEMPLATES.TemplateResponse("config.html", {"request": request})


@app.get("/galeria", response_class=HTMLResponse)
async def galeria_page(request: Request) -> HTMLResponse:
    """Galería de los últimos trabajos terminados (videos reproducibles)."""
    return TEMPLATES.TemplateResponse("galeria.html", {"request": request})


@app.get("/api/galeria")
async def galeria_list() -> JSONResponse:
    """Lista los últimos trabajos terminados con sus videos."""
    return JSONResponse({"items": manager.gallery()})


@app.get("/api/jobs/{job_id}/thumb/{n}")
async def job_thumb(job_id: str, n: int) -> FileResponse:
    """Miniatura (primer frame) del clip ``n`` del job."""
    if not manager.get(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    thumb = manager.thumb_path(job_id, n)
    if not thumb:
        raise HTTPException(status_code=404, detail="Miniatura no disponible")
    return FileResponse(path=str(thumb), media_type="image/jpeg")


@app.get("/api/library/music")
async def library_list() -> JSONResponse:
    """Lista las pistas de la biblioteca de música."""
    return JSONResponse({"tracks": [p.name for p in library.list_music()]})


@app.post("/api/library/music")
async def library_add(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Añade una o varias pistas (libres de derechos) a la biblioteca."""
    settings.ensure_dirs()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    added = 0
    for track in files:
        if not track.filename:
            continue
        tmp, name = await _save_upload(track, max_bytes, ALLOWED_AUDIO_EXT)
        library.save_music(tmp, name)
        added += 1
    return JSONResponse({"added": added, "tracks": [p.name for p in library.list_music()]})


@app.delete("/api/library/music/{name}")
async def library_delete(name: str) -> JSONResponse:
    """Borra una pista de la biblioteca."""
    if not library.delete_music(name):
        raise HTTPException(status_code=404, detail="Pista no encontrada")
    return JSONResponse({"tracks": [p.name for p in library.list_music()]})


@app.get("/api/library/guides")
async def guides_list() -> JSONResponse:
    """Lista los videos del stock de guías."""
    return JSONResponse({"guides": [p.name for p in library.list_guides()]})


@app.post("/api/library/guides")
async def guides_add(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Añade uno o varios videos al stock de guías (se sobreponen en el anuncio)."""
    settings.ensure_dirs()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    added = 0
    for vid in files:
        if not vid.filename:
            continue
        tmp, name = await _save_upload(vid, max_bytes, library.VIDEO_EXT)
        library.save_guide(tmp, name)
        added += 1
    return JSONResponse({"added": added, "guides": [p.name for p in library.list_guides()]})


@app.delete("/api/library/guides/{name}")
async def guides_delete(name: str) -> JSONResponse:
    """Borra un video del stock de guías."""
    if not library.delete_guide(name):
        raise HTTPException(status_code=404, detail="Guía no encontrada")
    return JSONResponse({"guides": [p.name for p in library.list_guides()]})


@app.get("/api/config/prompt")
async def get_prompt() -> JSONResponse:
    """Devuelve el prompt de edición de Remotion (editable)."""
    return JSONResponse({"prompt": library.read_prompt()})


@app.post("/api/config/prompt")
async def set_prompt(payload: dict) -> JSONResponse:
    """Guarda el prompt de edición de Remotion."""
    text = str(payload.get("prompt", ""))
    library.write_prompt(text)
    return JSONResponse({"ok": True, "chars": len(text)})


async def _save_upload(
    file: UploadFile, max_bytes: int, allowed: set[str] = ALLOWED_EXT
) -> tuple[Path, str]:
    """Guarda un upload en un temporal con control de tamaño (streaming)."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado ({ext or 'sin extensión'}). "
                   f"Usa: {', '.join(sorted(allowed))}",
        )
    tmp = Path(tempfile.mkstemp(suffix=ext, dir=str(settings.storage_dir))[1])
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"'{file.filename}' supera el máximo de "
                               f"{settings.max_upload_mb} MB.",
                    )
                out.write(chunk)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"'{file.filename}' está vacío.")
    return tmp, file.filename or f"video{ext}"


@app.post("/api/jobs")
async def create_job(
    files: list[UploadFile] = File(...),
    music: list[UploadFile] = File(None),
    voz: UploadFile | None = File(None),
    mode: str = Form("montage"),
    num_clips: int = Form(0),
) -> JSONResponse:
    """Recibe varios videos (compendio) y varias pistas de música; crea un job.

    Returns:
        JSON con el ``job_id``.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No se enviaron videos.")
    if mode not in ("montage", "ad"):
        raise HTTPException(status_code=400, detail="Modo inválido (montage|ad).")

    settings.ensure_dirs()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    saved: list[tuple[Path, str]] = []
    music_saved: list[tuple[Path, str]] = []
    voz_saved: tuple[Path, str] | None = None
    try:
        for file in files:
            saved.append(await _save_upload(file, max_bytes))
        for track in (music or []):
            if track and track.filename:
                music_saved.append(await _save_upload(track, max_bytes, ALLOWED_AUDIO_EXT))
        if voz is not None and voz.filename:
            voz_saved = await _save_upload(voz, max_bytes, ALLOWED_AUDIO_EXT)
    except HTTPException:
        for tmp, _ in saved:
            tmp.unlink(missing_ok=True)
        for tmp, _ in music_saved:
            tmp.unlink(missing_ok=True)
        if voz_saved:
            voz_saved[0].unlink(missing_ok=True)
        raise

    num_clips = max(0, min(20, num_clips))  # tope sano
    job_id = manager.submit(saved, music_saved, mode, voz_saved, num_clips)
    return JSONResponse(
        {"job_id": job_id, "n_videos": len(saved), "music": len(music_saved),
         "voz": voz_saved is not None, "mode": mode},
        status_code=201,
    )


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    """Devuelve el estado del job."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return JSONResponse(job.public_dict())


@app.get("/api/jobs/{job_id}/download/{n}")
async def download_clip(job_id: str, n: int) -> FileResponse:
    """Descarga el clip ``n`` (1-indexado) del job."""
    if not manager.get(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    path = manager.clip_path(job_id, n)
    if not path:
        raise HTTPException(status_code=409, detail="El clip aún no está listo")
    return FileResponse(path=str(path), media_type="video/mp4",
                        filename=f"clip_{job_id}_{n}.mp4")


@app.get("/preview/{job_id}", response_class=HTMLResponse)
async def preview_page(request: Request, job_id: str) -> HTMLResponse:
    """Previsualización en vivo del anuncio (Remotion Player) antes de renderizar."""
    if not manager.get(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return TEMPLATES.TemplateResponse("preview.html", {"request": request, "job_id": job_id})


@app.get("/api/jobs/{job_id}/ad.json")
async def ad_json(job_id: str) -> FileResponse:
    """Sirve el ad.json (la 'receta') del proyecto para el reproductor."""
    p = manager.ad_json_path(job_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return FileResponse(path=str(p), media_type="application/json")


@app.get("/api/jobs/{job_id}/r/{path:path}")
async def ad_asset(job_id: str, path: str) -> FileResponse:
    """Sirve un asset del proyecto (video/música/sfx) para el reproductor."""
    p = manager.ad_asset_path(job_id, path)
    if not p:
        raise HTTPException(status_code=404, detail="Asset no encontrado")
    return FileResponse(path=str(p))


@app.post("/api/jobs/{job_id}/overlay")
async def upload_overlay(job_id: str, file: UploadFile = File(...)) -> JSONResponse:
    """Sube una imagen/video al proyecto para ponerlo encima (overlay)."""
    proj = manager.ad_project_dir(job_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_OVERLAY_EXT:
        raise HTTPException(status_code=400, detail="Formato no soportado para overlay")
    overlays = proj / "public" / "overlays"
    overlays.mkdir(parents=True, exist_ok=True)
    name = f"ov_{uuid.uuid4().hex[:8]}{ext}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    dest = overlays / name
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail="Archivo demasiado grande")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return JSONResponse({"file": f"overlays/{name}"})


@app.post("/api/jobs/{job_id}/ad.json")
async def save_ad_json(job_id: str, payload: dict = Body(...)) -> JSONResponse:
    """Guarda el ad.json editado en el preview (textos, tiempos, emojis, etc.)."""
    if not manager.get(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if not manager.save_ad_json(job_id, payload):
        raise HTTPException(status_code=400, detail="ad.json inválido")
    return JSONResponse({"ok": True})


@app.post("/api/jobs/{job_id}/render")
async def render_ad(job_id: str, payload: dict | None = Body(None)) -> JSONResponse:
    """Dispara el render. Si se envía 'ad', renderiza con esa versión editada."""
    if not manager.get(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if payload and isinstance(payload.get("ad"), dict):
        manager.save_ad_json(job_id, payload["ad"])
    if not manager.request_render(job_id):
        raise HTTPException(status_code=409, detail="No se puede renderizar este trabajo")
    return JSONResponse({"ok": True})


@app.get("/api/jobs/{job_id}/project")
async def download_project(job_id: str) -> FileResponse:
    """Descarga el proyecto Remotion editable (.zip) del modo anuncio."""
    if not manager.get(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    ad_zip = manager.ad_zip_path(job_id)
    if not ad_zip:
        raise HTTPException(status_code=409, detail="El proyecto aún no está listo")
    return FileResponse(path=str(ad_zip), media_type="application/zip",
                        filename=f"anuncio-remotion_{job_id}.zip")


@app.get("/api/jobs/{job_id}/download")
async def download_all(job_id: str):
    """Descarga los videos en un .zip (o el proyecto Remotion si no se renderizó)."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    paths = [manager.clip_path(job_id, i) for i in range(1, job.n_clips + 1)]
    paths = [p for p in paths if p]
    if not paths:
        # Modo anuncio sin render: entregamos el proyecto Remotion.
        if job.mode == "ad":
            ad_zip = manager.ad_zip_path(job_id)
            if ad_zip:
                return FileResponse(path=str(ad_zip), media_type="application/zip",
                                    filename=f"anuncio-remotion_{job_id}.zip")
        raise HTTPException(status_code=409, detail="El resultado aún no está listo")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for i, p in enumerate(paths, start=1):
            zf.write(p, arcname=f"clip_{i}.mp4")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="clips_{job_id}.zip"'},
    )

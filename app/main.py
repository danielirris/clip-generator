"""FastAPI: endpoints de la API, subida de video y servidor web."""
from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, get_settings
from app.jobs import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("clip-generator")

settings = get_settings()

WEB_DIR = BASE_DIR / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

ALLOWED_EXT = {".mp4", ".mov", ".mkv"}


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
            "duracion_total_s": settings.duracion_total_s,
        },
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Healthcheck para EasyPanel."""
    return JSONResponse({"status": "ok"})


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...)) -> JSONResponse:
    """Recibe el video, valida y crea un job.

    Returns:
        JSON con el ``job_id``.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado ({ext}). Usa: {', '.join(sorted(ALLOWED_EXT))}",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    settings.ensure_dirs()

    # Guardamos el upload en un temporal con control de tamaño (streaming).
    tmp = Path(tempfile.mkstemp(suffix=ext, dir=str(settings.storage_dir))[1])
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"El archivo supera el máximo de {settings.max_upload_mb} MB.",
                    )
                out.write(chunk)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        logger.exception("Error guardando el upload")
        raise HTTPException(status_code=500, detail="Error guardando el archivo") from exc
    finally:
        await file.close()

    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="El archivo está vacío.")

    job_id = manager.submit(tmp, file.filename or f"video{ext}")
    return JSONResponse({"job_id": job_id}, status_code=201)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    """Devuelve el estado del job."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return JSONResponse(job.public_dict())


@app.get("/api/jobs/{job_id}/download")
async def download(job_id: str) -> FileResponse:
    """Descarga el mp4 final del job."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    output = manager.output_for(job_id)
    if not output:
        raise HTTPException(status_code=409, detail="El clip aún no está listo")
    filename = f"clip_{job_id}.mp4"
    return FileResponse(path=str(output), media_type="video/mp4", filename=filename)

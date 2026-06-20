"""Cola secuencial de jobs, estado en memoria y orquestación del pipeline.

Diseñado para bajo uso de RAM: un único hilo trabajador procesa los jobs de a
UNO. El estado vive en un dict en memoria protegido por un lock. Sin Redis ni
Celery.
"""
from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.pipeline import audio, transcribe, analyze, render, cleanup

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Estados posibles de un job."""

    QUEUED = "queued"
    EXTRACTING = "extracting"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"


# Progreso aproximado (0-100) asociado a cada estado, para la barra del front.
_PROGRESS = {
    JobStatus.QUEUED: 0,
    JobStatus.EXTRACTING: 10,
    JobStatus.TRANSCRIBING: 35,
    JobStatus.ANALYZING: 60,
    JobStatus.RENDERING: 75,
    JobStatus.DONE: 100,
    JobStatus.ERROR: 100,
}


@dataclass
class Job:
    """Estado de un job de procesamiento."""

    id: str
    filename: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    message: str = "En cola"
    error: str = ""
    aviso: str = ""
    created_at: float = field(default_factory=time.time)
    output_path: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Representación serializable para la API (sin rutas internas)."""
        d = asdict(self)
        d["status"] = self.status.value
        d["download_ready"] = self.status == JobStatus.DONE
        d.pop("output_path", None)
        return d


class JobManager:
    """Gestiona la cola, el estado y el hilo trabajador único."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._jobs: dict[str, Job] = {}
        self._sources: dict[str, Path] = {}
        self._lock = threading.Lock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._started = False

    # --- ciclo de vida ---
    def start(self) -> None:
        """Arranca el hilo trabajador (idempotente)."""
        if not self._started:
            self._settings.ensure_dirs()
            self._worker.start()
            self._started = True
            logger.info("JobManager iniciado.")

    # --- API pública ---
    def submit(self, source_tmp: Path, filename: str) -> str:
        """Registra un nuevo job, mueve el upload a su carpeta y lo encola.

        Args:
            source_tmp: ruta temporal del video ya guardado en disco.
            filename: nombre original del archivo.

        Returns:
            El ``job_id`` generado.
        """
        job_id = uuid.uuid4().hex[:12]
        work_dir = self._settings.jobs_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(filename).suffix.lower() or ".mp4"
        source_path = work_dir / f"source{ext}"
        shutil.move(str(source_tmp), str(source_path))

        job = Job(id=job_id, filename=filename)
        with self._lock:
            self._jobs[job_id] = job
            self._sources[job_id] = source_path
        self._queue.put(job_id)
        logger.info("Job %s encolado (%s)", job_id, filename)
        return job_id

    def get(self, job_id: str) -> Job | None:
        """Devuelve el job por id, o None si no existe."""
        with self._lock:
            return self._jobs.get(job_id)

    def output_for(self, job_id: str) -> Path | None:
        """Ruta del mp4 final si el job está terminado, o None."""
        job = self.get(job_id)
        if job and job.status == JobStatus.DONE and job.output_path:
            p = Path(job.output_path)
            return p if p.exists() else None
        return None

    # --- internos ---
    def _update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in kwargs.items():
                setattr(job, key, value)
            if "status" in kwargs:
                job.progress = _PROGRESS.get(job.status, job.progress)

    def _run_worker(self) -> None:
        """Bucle del trabajador: procesa jobs de la cola de a uno."""
        # Purga inicial de outputs antiguos.
        cleanup.purge_old_outputs(
            self._settings.outputs_dir, self._settings.retencion_horas
        )
        while True:
            job_id = self._queue.get()
            try:
                self._process(job_id)
            except Exception as exc:  # noqa: BLE001 - el job no debe tumbar el hilo
                logger.exception("Error inesperado procesando job %s", job_id)
                self._update(
                    job_id,
                    status=JobStatus.ERROR,
                    message="Error inesperado",
                    error=str(exc),
                )
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        """Ejecuta el pipeline completo para un job."""
        settings = self._settings
        source = self._sources.get(job_id)
        if source is None:
            self._update(job_id, status=JobStatus.ERROR, error="Fuente no encontrada")
            return

        work_dir = settings.jobs_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        output_path = settings.outputs_dir / f"{job_id}.mp4"

        try:
            # 1) Extraer audio
            self._update(job_id, status=JobStatus.EXTRACTING, message="Extrayendo audio")
            audio_path = work_dir / "audio.wav"
            audio.extract_audio(source, audio_path)
            # Nota: el video fuente NO se borra todavía porque el render necesita
            # sus fotogramas para cortar los beats. Se elimina al final (finally).

            # 2) Transcribir
            self._update(
                job_id, status=JobStatus.TRANSCRIBING, message="Transcribiendo (Groq)"
            )
            segments = transcribe.transcribe_audio(audio_path)

            # 3) Analizar momentos impactantes
            self._update(
                job_id, status=JobStatus.ANALYZING, message="Analizando (Gemini)"
            )
            clips = analyze.analyze_segments(segments)

            # 4) Render final
            self._update(
                job_id, status=JobStatus.RENDERING, message="Renderizando clip vertical"
            )
            result = render.render_clip(
                source=source,
                segments=segments,
                clips=clips,
                work_dir=work_dir,
                output_path=output_path,
                total_beats=settings.total_beats,
                beat_s=settings.duracion_beat_s,
                modo_fondo=settings.modo_fondo,
                subtitulos=settings.subtitulos,
            )

            self._update(
                job_id,
                status=JobStatus.DONE,
                message="Completado",
                aviso=result.aviso,
                output_path=str(output_path),
            )
            logger.info("Job %s completado (%.0fs)", job_id, result.duracion_real_s)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Fallo en el pipeline del job %s", job_id)
            self._update(
                job_id,
                status=JobStatus.ERROR,
                message="Error en el procesamiento",
                error=str(exc),
            )
        finally:
            # Limpieza de temporales (mantiene solo el output final).
            cleanup.cleanup_job_dir(work_dir)
            cleanup.delete_source(source)
            self._sources.pop(job_id, None)
            cleanup.purge_old_outputs(
                settings.outputs_dir, settings.retencion_horas
            )


# Instancia global única.
manager = JobManager()

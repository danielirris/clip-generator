"""Cola secuencial de jobs, estado en memoria y orquestación del pipeline.

Un job procesa un COMPENDIO de videos y produce N clips verticales, cada uno
mezclando fragmentos de TODOS los videos (ganchos al inicio + cuerpo variado).

Diseñado para bajo uso de RAM: un único hilo trabajador procesa los jobs de a
UNO. El estado vive en un dict en memoria protegido por un lock. Sin Redis ni
Celery.
"""
from __future__ import annotations

import json
import logging
import queue
import random
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
from app.pipeline.compose import compose_clips
from app.pipeline.fragments import VideoSource, build_pool
from app.pipeline.remotion_export import export_remotion
from app.store import JobStore

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
    JobStatus.ANALYZING: 55,
    JobStatus.RENDERING: 70,
    JobStatus.DONE: 100,
    JobStatus.ERROR: 100,
}


@dataclass
class Job:
    """Estado de un job (un compendio de videos -> N clips)."""

    id: str
    filenames: list[str]
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    message: str = "En cola"
    error: str = ""
    aviso: str = ""
    n_clips: int = 0
    created_at: float = field(default_factory=time.time)
    output_dir: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Representación serializable para la API (sin rutas internas)."""
        d = asdict(self)
        d["status"] = self.status.value
        d["n_videos"] = len(self.filenames)
        d["download_ready"] = self.status == JobStatus.DONE
        # URLs de descarga de cada clip.
        d["clips"] = (
            [f"/api/jobs/{self.id}/download/{i}" for i in range(1, self.n_clips + 1)]
            if self.status == JobStatus.DONE else []
        )
        d.pop("output_dir", None)
        return d


class JobManager:
    """Gestiona la cola, el estado y el hilo trabajador único."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._jobs: dict[str, Job] = {}
        self._sources: dict[str, list[Path]] = {}
        self._music: dict[str, list[Path]] = {}
        self._lock = threading.Lock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._started = False
        self._store = JobStore(self._settings.storage_dir / "jobs.db")

    # --- ciclo de vida ---
    def start(self) -> None:
        """Arranca el hilo trabajador (idempotente) y reanuda trabajos pendientes."""
        if not self._started:
            self._settings.ensure_dirs()
            self._recover()
            self._worker.start()
            self._started = True
            logger.info("JobManager iniciado.")

    def _recover(self) -> None:
        """Reanuda trabajos que quedaron a medias tras un reinicio del contenedor."""
        for row in self._store.incomplete():
            try:
                sources = [Path(p) for p in json.loads(row["sources"])]
                music = [Path(p) for p in json.loads(row["music"] or "[]")]
                if not sources or not all(p.exists() for p in sources):
                    self._store.update(row["id"], {
                        "status": JobStatus.ERROR.value, "progress": 100,
                        "error": "Interrumpido por un reinicio; vuelve a subir los videos.",
                    })
                    continue
                job = Job(id=row["id"], filenames=json.loads(row["filenames"]),
                          created_at=row["created_at"], status=JobStatus.QUEUED,
                          message="Reanudado tras reinicio")
                with self._lock:
                    self._jobs[job.id] = job
                    self._sources[job.id] = sources
                    if music:
                        self._music[job.id] = music  # lista de pistas
                self._store.update(row["id"], {"status": "queued", "progress": 0,
                                               "message": "Reanudado tras reinicio"})
                self._queue.put(job.id)
                logger.info("Job %s reanudado tras reinicio", job.id)
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo recuperar el job %s", row["id"])

    # --- API pública ---
    def submit(
        self,
        source_tmps: list[tuple[Path, str]],
        music_tmps: list[tuple[Path, str]] | None = None,
    ) -> str:
        """Registra un nuevo job, mueve los uploads a su carpeta y lo encola.

        Args:
            source_tmps: lista de (ruta_temporal, nombre_original) de los videos.
            music_tmps: lista de (ruta_temporal, nombre) de las pistas de música.

        Returns:
            El ``job_id`` generado.
        """
        job_id = uuid.uuid4().hex[:12]
        work_dir = self._settings.jobs_dir / job_id
        sources_dir = work_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        paths: list[Path] = []
        filenames: list[str] = []
        for i, (tmp, name) in enumerate(source_tmps):
            ext = Path(name).suffix.lower() or ".mp4"
            dest = sources_dir / f"src_{i:03d}{ext}"
            shutil.move(str(tmp), str(dest))
            paths.append(dest)
            filenames.append(name)

        music_paths: list[Path] = []
        for i, (mtmp, mname) in enumerate(music_tmps or []):
            mext = Path(mname).suffix.lower() or ".mp3"
            mdest = sources_dir / f"music_{i:03d}{mext}"
            shutil.move(str(mtmp), str(mdest))
            music_paths.append(mdest)

        job = Job(id=job_id, filenames=filenames)
        with self._lock:
            self._jobs[job_id] = job
            self._sources[job_id] = paths
            if music_paths:
                self._music[job_id] = music_paths
        self._store.save(id=job_id, filenames=filenames, status=JobStatus.QUEUED.value,
                         created_at=job.created_at, sources=paths, music=music_paths)
        self._queue.put(job_id)
        logger.info("Job %s encolado (%d videos, %d pistas)",
                    job_id, len(paths), len(music_paths))
        return job_id

    def get(self, job_id: str) -> Job | None:
        """Devuelve el job por id (de memoria, o reconstruido desde SQLite)."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job
        row = self._store.get_one(job_id)  # p.ej. job ya hecho antes de un reinicio
        if row is None:
            return None
        return Job(
            id=row["id"], filenames=json.loads(row["filenames"]),
            status=JobStatus(row["status"]), progress=row["progress"],
            message=row["message"], error=row["error"], aviso=row["aviso"],
            n_clips=row["n_clips"], created_at=row["created_at"],
            output_dir=row["output_dir"],
        )

    def clip_path(self, job_id: str, n: int) -> Path | None:
        """Ruta del clip ``n`` (1-indexado) si el job está terminado."""
        job = self.get(job_id)
        if job and job.status == JobStatus.DONE and job.output_dir:
            p = Path(job.output_dir) / f"clip_{n}.mp4"
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
            progress = job.progress
        # Replica en SQLite (fuera del lock).
        fields: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key == "status":
                fields["status"] = value.value if isinstance(value, JobStatus) else value
                fields["progress"] = progress
            elif key in ("message", "error", "aviso", "n_clips", "output_dir"):
                fields[key] = value
        self._store.update(job_id, fields)

    def _run_worker(self) -> None:
        """Bucle del trabajador: procesa jobs de la cola de a uno."""
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
                    job_id, status=JobStatus.ERROR,
                    message="Error inesperado", error=str(exc),
                )
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        """Ejecuta el pipeline completo para un job (compendio -> N clips)."""
        settings = self._settings
        sources = self._sources.get(job_id, [])
        if not sources:
            self._update(job_id, status=JobStatus.ERROR, error="Sin videos en el job")
            return

        work_dir = settings.jobs_dir / job_id
        output_dir = settings.outputs_dir / job_id

        try:
            # 1) Extraer audio + medir duración + 2) transcribir, por video.
            videos: list[VideoSource] = []
            segments_by_video: dict[int, list] = {}
            for vid, src in enumerate(sources):
                self._update(
                    job_id, status=JobStatus.EXTRACTING,
                    message=f"Procesando audio {vid + 1}/{len(sources)}",
                )
                duration = audio.probe_duration(src)
                audio_path = work_dir / f"audio_{vid:03d}.wav"
                audio.extract_audio(src, audio_path)

                self._update(
                    job_id, status=JobStatus.TRANSCRIBING,
                    message=f"Transcribiendo {vid + 1}/{len(sources)}",
                )
                segs = transcribe.transcribe_audio(audio_path)
                audio_path.unlink(missing_ok=True)  # ya no se necesita

                videos.append(VideoSource(id=vid, path=src, duration=duration,
                                          name=self.get(job_id).filenames[vid], segments=segs))
                segments_by_video[vid] = segs

            # 3) Analizar ganchos (impactantes) sobre todos los videos.
            self._update(job_id, status=JobStatus.ANALYZING, message="Detectando ganchos")
            moments = analyze.analyze_hooks([v.segments for v in videos])

            # Construir pool y componer N clips (cortes de duración variable).
            rng = random.Random(f"{settings.seed}:{job_id}")
            pool = build_pool(videos, rng, settings.beat_min_s, settings.beat_max_s)
            n_clips = max(1, settings.num_clips)
            # Las transiciones (xfade) solapan y acortan el clip; compensamos
            # componiendo un poco más de material para acabar cerca de la duración.
            buffer_s = 0.0
            if settings.transiciones:
                avg_trans = (settings.trans_min + settings.trans_max) / 2
                buffer_s = avg_trans * settings.trans_dur_s
            clips = compose_clips(
                pool, moments, videos, rng,
                num_clips=n_clips,
                duracion_total_s=settings.duracion_total_s + buffer_s,
                hook_beats=settings.hook_beats,
                beat_min=settings.beat_min_s,
                beat_max=settings.beat_max_s,
            )

            # 4) Render de los N clips (beats cacheados, transiciones, música).
            self._update(
                job_id, status=JobStatus.RENDERING,
                message=f"Renderizando {n_clips} clips",
            )
            music_paths = self._music.get(job_id, [])
            video_names = {v.id: v.name for v in videos}
            result = render.render_clips(
                clips, segments_by_video, video_names, work_dir, output_dir, rng,
                modo_fondo=settings.modo_fondo,
                subtitulos=settings.subtitulos,
                transiciones=settings.transiciones,
                trans_min=settings.trans_min,
                trans_max=settings.trans_max,
                modo_transicion=settings.modo_transicion,
                trans_dur=settings.trans_dur_s,
                music_paths=music_paths,
                threads=settings.ffmpeg_threads,
            )

            # 5) Exportar proyecto Remotion editable.
            if settings.remotion_export:
                self._update(job_id, status=JobStatus.RENDERING,
                             message="Exportando proyecto Remotion")
                export_remotion(output_dir, result)

            aviso = ""
            if len(pool) < settings.min_fragmentos:
                aviso = (
                    f"Pool de {len(pool)} fragmentos (< {settings.min_fragmentos} "
                    f"recomendado): los clips reutilizan más material."
                )

            self._update(
                job_id, status=JobStatus.DONE, message="Completado",
                n_clips=len(result.clips), aviso=aviso, output_dir=str(output_dir),
            )
            logger.info(
                "Job %s completado: %d clips, %d beats únicos",
                job_id, len(result.clips), result.beats_unicos,
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("Fallo en el pipeline del job %s", job_id)
            self._update(
                job_id, status=JobStatus.ERROR,
                message="Error en el procesamiento", error=str(exc),
            )
        finally:
            # Limpieza: borra temporales y videos fuente (deja solo los clips).
            cleanup.cleanup_job_dir(work_dir)
            with self._lock:
                self._sources.pop(job_id, None)
                self._music.pop(job_id, None)
            cleanup.purge_old_outputs(settings.outputs_dir, settings.retencion_horas)


# Instancia global única.
manager = JobManager()

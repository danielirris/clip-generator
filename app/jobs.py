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

from app.config import Settings, get_settings, BASE_DIR
from app.pipeline import audio, transcribe, analyze, render, cleanup
from app.pipeline.compose import compose_clips
from app.pipeline.fragments import VideoSource, build_pool
from app.pipeline.remotion_export import export_remotion
from app.pipeline.ad_export import build_ad_project, AdVideo
from app.pipeline import ad_render
from app import library
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
    mode: str = "montage"  # montage | ad
    created_at: float = field(default_factory=time.time)
    output_dir: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Representación serializable para la API (sin rutas internas)."""
        d = asdict(self)
        d["status"] = self.status.value
        d["n_videos"] = len(self.filenames)
        done = self.status == JobStatus.DONE
        d["download_ready"] = done
        # Previsualización por video (clips de montaje o anuncios ya renderizados).
        d["clips"] = (
            [f"/api/jobs/{self.id}/download/{i}" for i in range(1, self.n_clips + 1)]
            if done and self.n_clips > 0 else []
        )
        d["download_url"] = f"/api/jobs/{self.id}/download" if done else None
        # En modo anuncio, además: proyecto editable + previsualización en vivo.
        is_ad = done and self.mode == "ad"
        d["project_url"] = f"/api/jobs/{self.id}/project" if is_ad else None
        d["preview_url"] = f"/preview/{self.id}" if is_ad else None
        d.pop("output_dir", None)
        return d


class JobManager:
    """Gestiona la cola, el estado y el hilo trabajador único."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._jobs: dict[str, Job] = {}
        self._sources: dict[str, list[Path]] = {}
        self._music: dict[str, list[Path]] = {}
        self._voz: dict[str, Path] = {}
        self._req_clips: dict[str, int] = {}  # nº de clips pedido (0 = por defecto)
        self._lock = threading.Lock()
        self._queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
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
                voz = Path(row["voz"]) if row["voz"] else None
                if not sources or not all(p.exists() for p in sources):
                    self._store.update(row["id"], {
                        "status": JobStatus.ERROR.value, "progress": 100,
                        "error": "Interrumpido por un reinicio; vuelve a subir los videos.",
                    })
                    continue
                job = Job(id=row["id"], filenames=json.loads(row["filenames"]),
                          created_at=row["created_at"], status=JobStatus.QUEUED,
                          mode=row["mode"], message="Reanudado tras reinicio")
                with self._lock:
                    self._jobs[job.id] = job
                    self._sources[job.id] = sources
                    if music:
                        self._music[job.id] = music  # lista de pistas
                    if voz:
                        self._voz[job.id] = voz
                    if row["num_clips_req"]:
                        self._req_clips[job.id] = int(row["num_clips_req"])
                self._store.update(row["id"], {"status": "queued", "progress": 0,
                                               "message": "Reanudado tras reinicio"})
                self._queue.put(("job", job.id))
                logger.info("Job %s reanudado tras reinicio", job.id)
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo recuperar el job %s", row["id"])

    # --- API pública ---
    def submit(
        self,
        source_tmps: list[tuple[Path, str]],
        music_tmps: list[tuple[Path, str]] | None = None,
        mode: str = "montage",
        voz_tmp: tuple[Path, str] | None = None,
        num_clips: int = 0,
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

        voz_path: Path | None = None
        if voz_tmp is not None:
            vtmp, vname = voz_tmp
            vext = Path(vname).suffix.lower() or ".mp3"
            voz_path = sources_dir / f"voz{vext}"
            shutil.move(str(vtmp), str(voz_path))

        job = Job(id=job_id, filenames=filenames, mode=mode)
        with self._lock:
            self._jobs[job_id] = job
            self._sources[job_id] = paths
            if music_paths:
                self._music[job_id] = music_paths
            if voz_path is not None:
                self._voz[job_id] = voz_path
            if num_clips:
                self._req_clips[job_id] = int(num_clips)
        self._store.save(id=job_id, filenames=filenames, status=JobStatus.QUEUED.value,
                         created_at=job.created_at, sources=paths, music=music_paths,
                         mode=mode, voz=voz_path, num_clips_req=int(num_clips or 0))
        self._queue.put(("job", job_id))
        logger.info("Job %s encolado (modo=%s, %d videos, %d pistas)",
                    job_id, mode, len(paths), len(music_paths))
        return job_id

    def request_render(self, job_id: str) -> bool:
        """Encola el render del proyecto Remotion ya generado (modo anuncio)."""
        job = self.get(job_id)
        if not job or job.mode != "ad" or not job.output_dir:
            return False
        if not (Path(job.output_dir) / "remotion-ad").exists():
            return False
        self._update(job_id, status=JobStatus.RENDERING, message="En cola para renderizar")
        self._queue.put(("render", job_id))
        return True

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
            n_clips=row["n_clips"], mode=row["mode"], created_at=row["created_at"],
            output_dir=row["output_dir"],
        )

    def clip_path(self, job_id: str, n: int) -> Path | None:
        """Ruta del clip ``n`` (1-indexado) si el job está terminado."""
        job = self.get(job_id)
        if job and job.status == JobStatus.DONE and job.output_dir:
            p = Path(job.output_dir) / f"clip_{n}.mp4"
            return p if p.exists() else None
        return None

    def ad_project_dir(self, job_id: str) -> Path | None:
        """Carpeta del proyecto Remotion del job, o None."""
        job = self.get(job_id)
        if job and job.output_dir:
            p = Path(job.output_dir) / "remotion-ad"
            return p if p.exists() else None
        return None

    def ad_json_path(self, job_id: str) -> Path | None:
        """Ruta del ad.json del proyecto, o None."""
        proj = self.ad_project_dir(job_id)
        if proj and (proj / "ad.json").exists():
            return proj / "ad.json"
        return None

    def save_ad_json(self, job_id: str, data: Any) -> bool:
        """Sobrescribe el ad.json del proyecto con la versión editada en el preview."""
        proj = self.ad_project_dir(job_id)
        if not proj or not isinstance(data, dict) or "videos" not in data:
            return False
        (proj / "ad.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def ad_asset_path(self, job_id: str, rel: str) -> Path | None:
        """Ruta de un asset del proyecto (public/<rel>), validada contra escapes."""
        proj = self.ad_project_dir(job_id)
        if not proj:
            return None
        public = (proj / "public").resolve()
        target = (public / rel).resolve()
        if str(target).startswith(str(public)) and target.is_file():
            return target
        return None

    def ad_zip_path(self, job_id: str) -> Path | None:
        """Ruta del .zip del proyecto Remotion (modo anuncio) si está listo."""
        job = self.get(job_id)
        if job and job.status == JobStatus.DONE and job.output_dir:
            p = Path(job.output_dir) / "anuncio-remotion.zip"
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
            kind, job_id = self._queue.get()
            try:
                if kind == "render":
                    self._render_existing_ad(job_id)
                else:
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

        job = self.get(job_id)
        if job and job.mode == "ad":
            self._process_ad(job_id, sources, work_dir, output_dir)
            return

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
            n_clips = max(1, self._req_clips.get(job_id) or settings.num_clips)
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
                subtitulos=settings.subtitulos_recortes,  # Apartado 1: sin subtítulos
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
                self._voz.pop(job_id, None)
                self._req_clips.pop(job_id, None)
            cleanup.purge_old_outputs(settings.outputs_dir, settings.retencion_horas)

    def _process_ad(self, job_id: str, sources: list[Path],
                    work_dir: Path, output_dir: Path) -> None:
        """Modo anuncio: genera un proyecto Remotion (1 composición por video)."""
        settings = self._settings
        # Música: la del job si la subió; si no, la biblioteca (libre de derechos).
        music_paths = self._music.get(job_id) or library.list_music()
        sfx = library.ensure_sfx()  # whoosh/pop/ding generados, sin copyright
        voz = self._voz.get(job_id)  # locución subida para ponerle al video
        # Si hay locución, se transcribe ESA (es el audio que se oirá) una sola vez.
        voz_words = None
        voz_dur = 0.0
        if voz is not None:
            self._update(job_id, status=JobStatus.TRANSCRIBING,
                         message="Transcribiendo la locución")
            voz_dur = audio.probe_duration(voz)
            voz_words = transcribe.transcribe_words(voz)
        try:
            videos: list[AdVideo] = []
            for vid, src in enumerate(sources):
                width, height = audio.probe_resolution(src)
                if voz is not None:
                    # La locución manda: dura lo que la voz y el video se repite.
                    words = voz_words or []
                    duration = voz_dur or audio.probe_duration(src)
                else:
                    self._update(job_id, status=JobStatus.EXTRACTING,
                                 message=f"Procesando audio {vid + 1}/{len(sources)}")
                    duration = audio.probe_duration(src)
                    audio_path = work_dir / f"audio_{vid:03d}.wav"
                    audio.extract_audio(src, audio_path)
                    self._update(job_id, status=JobStatus.TRANSCRIBING,
                                 message=f"Transcribiendo (palabras) {vid + 1}/{len(sources)}")
                    words = transcribe.transcribe_words(audio_path)
                    audio_path.unlink(missing_ok=True)

                music = music_paths[vid % len(music_paths)] if music_paths else None
                videos.append(AdVideo(
                    id=vid, path=src, name=self.get(job_id).filenames[vid],
                    width=width, height=height, duration=duration,
                    words=words, music=music, voz=voz,
                ))

            # Director de edición: la IA, leyendo la voz con timestamps, decide el
            # plan completo por video (estilo, full-screen, píldoras, emojis...).
            self._update(job_id, status=JobStatus.ANALYZING,
                         message="Diseñando la edición (IA)")
            prompt_text = library.read_prompt()
            for v in videos:
                v.plan = analyze.plan_ad(v.words, v.duration, prompt_text)
                # Colores AL AZAR (independientes del tema): paleta barajada por video.
                pal = analyze.random_palette(f"{settings.seed}:{job_id}:{v.id}")
                v.plan["palette"] = pal
                v.plan["accent"] = pal[0]

            self._update(job_id, status=JobStatus.RENDERING,
                         message="Generando proyecto Remotion (anuncio)")
            build_ad_project(
                videos, output_dir,
                cta_texto=settings.cta_texto, whatsapp=settings.whatsapp_link,
                vol=settings.musica_volumen, vol_duck=settings.musica_volumen_ducking,
                sfx=sfx,
            )
            # Empaquetar el proyecto editable (.zip).
            shutil.make_archive(str(output_dir / "anuncio-remotion"), "zip",
                                str(output_dir / "remotion-ad"))

            # Con preview_first: NO renderizamos aún; mostramos la previsualización
            # y el render se dispara con request_render (botón "Renderizar").
            if settings.preview_first:
                self._update(job_id, status=JobStatus.DONE, n_clips=0,
                             message="Listo para previsualizar", output_dir=str(output_dir))
                logger.info("Job %s (anuncio) generado; esperando preview/render", job_id)
            else:
                self._render_existing_ad(job_id, output_dir=output_dir, videos_n=len(videos))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Fallo en el modo anuncio del job %s", job_id)
            self._update(job_id, status=JobStatus.ERROR,
                         message="Error en el procesamiento", error=str(exc))
        finally:
            cleanup.cleanup_job_dir(work_dir)
            with self._lock:
                self._sources.pop(job_id, None)
                self._music.pop(job_id, None)
                self._voz.pop(job_id, None)
                self._req_clips.pop(job_id, None)
            cleanup.purge_old_outputs(settings.outputs_dir, settings.retencion_horas)

    def _render_existing_ad(self, job_id: str, output_dir: Path | None = None,
                            videos_n: int | None = None) -> None:
        """Renderiza el proyecto Remotion ya generado a clip_N.mp4 (bajo demanda)."""
        settings = self._settings
        output_dir = output_dir or (settings.outputs_dir / job_id)
        project_dir = output_dir / "remotion-ad"
        if not project_dir.exists():
            self._update(job_id, status=JobStatus.ERROR, error="Proyecto no encontrado")
            return
        if not (settings.renderizar_anuncio and ad_render.render_available()):
            self._update(job_id, status=JobStatus.DONE, n_clips=0,
                         message="Listo para previsualizar",
                         aviso="Este servidor no renderiza video (sin Node); usa el proyecto.",
                         output_dir=str(output_dir))
            return
        self._update(job_id, status=JobStatus.RENDERING,
                     message="Renderizando anuncio (Remotion)")
        try:
            rendered = ad_render.render_ad_project(project_dir, output_dir)
            n = len(rendered)
            aviso = ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("Render del anuncio falló (%s)", job_id)
            n = 0
            aviso = f"No se pudo renderizar ({exc}); usa el proyecto editable."
        link = project_dir / "node_modules"
        if link.is_symlink():
            link.unlink()
        self._update(job_id, status=JobStatus.DONE, n_clips=n, aviso=aviso,
                     message="Completado", output_dir=str(output_dir))
        logger.info("Job %s (anuncio) renderizado: %d video(s)", job_id, n)


# Instancia global única.
manager = JobManager()

"""Carga y validación de la configuración desde variables de entorno."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del proyecto (carpeta que contiene este paquete `app/`).
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuración de la aplicación leída del entorno / archivo .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Clave de API (OpenAI cubre transcripción y análisis) ---
    openai_api_key: str = ""

    # --- Modelos ---
    openai_transcribe_model: str = "whisper-1"
    openai_analyze_model: str = "gpt-4o-mini"

    # --- Especificación de los clips ---
    num_clips: int = 5            # cuántos clips generar por compendio (3-5 típico)
    duracion_total_s: int = 48
    beat_min_s: float = 2.0       # duración mínima de cada fragmento (corte)
    beat_max_s: float = 4.0       # duración máxima de cada fragmento (corte)
    min_fragmentos: int = 50      # tamaño mínimo del pool de fragmentos
    hook_beats: int = 2           # fragmentos "impactantes" al inicio de cada clip
    modo_fondo: str = "blur"      # blur | crop | pad_negro
    subtitulos: bool = True

    # --- Transiciones ---
    transiciones: bool = True     # aplicar transiciones entre fragmentos
    trans_min: int = 3            # nº mínimo de transiciones por clip
    trans_max: int = 6            # nº máximo de transiciones por clip
    modo_transicion: str = "variadas"  # variadas | fundido | corte
    trans_dur_s: float = 0.4      # duración del solape de cada transición

    # --- Audio ---
    quitar_audio_original: bool = True  # los clips no llevan el audio de los videos

    # --- Remotion ---
    remotion_export: bool = True  # exportar proyecto Remotion editable por job

    # --- Recursos (estabilidad en VPS) ---
    ffmpeg_threads: int = 1       # hilos de FFmpeg (1 = menor pico de CPU/RAM)

    # --- Semilla para variar cortes/transiciones de forma reproducible ---
    seed: int = 1234

    # --- Límites / recursos ---
    max_upload_mb: int = 2048
    retencion_horas: int = 24

    # --- Servidor ---
    port: int = 8000

    # --- Rutas de almacenamiento (derivadas) ---
    @property
    def storage_dir(self) -> Path:
        return BASE_DIR / "storage"

    @property
    def jobs_dir(self) -> Path:
        """Carpeta de trabajo temporal por job."""
        return self.storage_dir / "jobs"

    @property
    def outputs_dir(self) -> Path:
        """Carpeta de resultados finales (un subdirectorio por job)."""
        return self.storage_dir / "outputs"

    def ensure_dirs(self) -> None:
        """Crea las carpetas de almacenamiento si no existen."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings."""
    return Settings()

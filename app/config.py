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

    # --- Claves de API ---
    groq_api_key: str = ""
    gemini_api_key: str = ""

    # --- Modelos ---
    groq_whisper_model: str = "whisper-large-v3-turbo"
    gemini_model: str = "gemini-2.5-flash-lite"

    # --- Especificación del clip ---
    duracion_total_s: int = 48
    duracion_beat_s: int = 2
    modo_fondo: str = "blur"  # blur | crop | pad_negro
    subtitulos: bool = True

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
        """Carpeta de resultados finales (mp4 por job)."""
        return self.storage_dir / "outputs"

    @property
    def total_beats(self) -> int:
        """Número de beats objetivo (p.ej. 48 / 2 = 24)."""
        return max(1, self.duracion_total_s // self.duracion_beat_s)

    def ensure_dirs(self) -> None:
        """Crea las carpetas de almacenamiento si no existen."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings."""
    return Settings()

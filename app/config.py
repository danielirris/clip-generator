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

    # --- Claves de otros proveedores (leídas del entorno; el front NUNCA las ve) ---
    elevenlabs_api_key: str = ""
    groq_api_key: str = ""      # reservada (no se usa hoy; disponible si se necesita)
    gemini_api_key: str = ""    # reservada (no se usa hoy; disponible si se necesita)

    # --- Texto a voz (ElevenLabs) ---
    elevenlabs_model: str = "eleven_multilingual_v2"  # soporta español
    tts_voz_default: str = "Sarah"                    # clave del catálogo VOCES
    tts_velocidad_default: float = 1.1                # 0.7-1.2 (>1 acelera)
    tts_estabilidad_default: float = 0.5
    tts_similitud_default: float = 0.75

    # --- Especificación de los clips ---
    num_clips: int = 5            # cuántos clips generar por compendio (3-5 típico)
    duracion_total_s: int = 48
    beat_min_s: float = 2.0       # duración mínima de cada fragmento (corte)
    beat_max_s: float = 4.0       # duración máxima de cada fragmento (corte)
    min_fragmentos: int = 50      # tamaño mínimo del pool de fragmentos
    hook_beats: int = 2           # fragmentos "impactantes" al inicio de cada clip
    modo_fondo: str = "blur"      # blur | crop | pad_negro
    subtitulos: bool = True
    # Apartado 1 (Recortes): SIN subtítulos por defecto — los subtítulos bonitos
    # se ponen en el Apartado 2 (Remotion); si no, quedarían dobles/encimados.
    subtitulos_recortes: bool = False

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

    # --- Recursos / velocidad ---
    ffmpeg_threads: int = 0        # 0 = auto (usa todos los núcleos = más rápido)
    remotion_concurrency: int = 0  # 0 = auto (Remotion elige según los núcleos)

    # --- Modo anuncio (proyecto Remotion por video) ---
    whatsapp_link: str = "https://wa.me/0000000000"  # CTA (placeholder editable)
    cta_texto: str = "Haz clic para conseguir el tuyo"
    musica_volumen: float = 0.18  # volumen base de la música (0-1)
    musica_volumen_ducking: float = 0.08  # volumen mientras habla la voz
    renderizar_anuncio: bool = True  # renderizar el mp4 final si hay Node + runtime
    preview_first: bool = True       # modo anuncio: previsualizar antes de renderizar

    # --- Semilla para variar cortes/transiciones de forma reproducible ---
    seed: int = 1234

    # --- Límites / recursos ---
    max_upload_mb: int = 2048
    retencion_horas: int = 24
    # Galería: nº de trabajos recientes que se conservan (y se muestran). En vez
    # de borrar por horas, mantenemos SIEMPRE los últimos N para poder verlos.
    galeria_max: int = 25

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

    @property
    def effective_ffmpeg_threads(self) -> int:
        """Hilos de FFmpeg a usar, dejando SIEMPRE 1 núcleo libre para el servidor.

        Si ``ffmpeg_threads`` es 0 (auto), no usamos todos los núcleos: dejamos uno
        para que Uvicorn siga respondiendo al healthcheck durante renders pesados y
        EasyPanel no reinicie el contenedor (evita el 502 por saturación de CPU).
        Si se fija un valor explícito por entorno, se respeta.
        """
        if self.ffmpeg_threads > 0:
            return self.ffmpeg_threads
        import os
        return max(1, (os.cpu_count() or 2) - 1)

    def ensure_dirs(self) -> None:
        """Crea las carpetas de almacenamiento si no existen."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings."""
    return Settings()

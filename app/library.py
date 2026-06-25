"""Biblioteca de assets de audio: música (libre de derechos) y SFX.

- La **música** la sube el usuario una vez en la página de Configuración y se usa
  automáticamente en los anuncios cuando el job no trae música propia.
- Los **SFX** (whoosh/pop/ding) se generan con FFmpeg (originales, sin copyright)
  la primera vez y se cachean.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


# --------------------------------------------------------------------------- #
# Prompt de edición de Remotion (editable, persistente en el volumen)
# --------------------------------------------------------------------------- #
def prompt_path() -> Path:
    return get_settings().storage_dir / "PROMPT_EDICION.md"


def read_prompt() -> str:
    """Devuelve el prompt efectivo (el editado en el volumen, o el del repo)."""
    p = prompt_path()
    if p.exists():
        return p.read_text(encoding="utf-8")
    default = BASE_DIR / "remotion" / "PROMPT_EDICION.md"
    return default.read_text(encoding="utf-8") if default.exists() else ""


def write_prompt(text: str) -> None:
    """Guarda el prompt editable en el volumen persistente."""
    p = prompt_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    logger.info("Prompt de edición actualizado (%d chars).", len(text))


def _base() -> Path:
    return get_settings().storage_dir / "library"


def music_dir() -> Path:
    d = _base() / "music"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sfx_dir() -> Path:
    d = _base() / "sfx"
    d.mkdir(parents=True, exist_ok=True)
    return d


def guides_dir() -> Path:
    """Carpeta del 'stock' de videos de la guía (se suben una vez en /config)."""
    d = _base() / "guides"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Música
# --------------------------------------------------------------------------- #
def list_music() -> list[Path]:
    """Lista las pistas de música de la biblioteca (ordenadas por nombre)."""
    return sorted(p for p in music_dir().iterdir()
                  if p.is_file() and p.suffix.lower() in AUDIO_EXT)


def save_music(tmp_path: Path, filename: str) -> Path:
    """Guarda una pista en la biblioteca con un nombre saneado y único."""
    safe = "".join(c for c in Path(filename).stem if c.isalnum() or c in " -_").strip()
    safe = safe.replace(" ", "_") or "pista"
    ext = Path(filename).suffix.lower() or ".mp3"
    dest = music_dir() / f"{safe}{ext}"
    i = 1
    while dest.exists():
        dest = music_dir() / f"{safe}_{i}{ext}"
        i += 1
    shutil.move(str(tmp_path), str(dest))
    logger.info("Música añadida a la biblioteca: %s", dest.name)
    return dest


def delete_music(name: str) -> bool:
    """Borra una pista de la biblioteca por nombre de archivo."""
    target = (music_dir() / name).resolve()
    if target.parent == music_dir().resolve() and target.is_file():
        target.unlink()
        logger.info("Música borrada de la biblioteca: %s", name)
        return True
    return False


# --------------------------------------------------------------------------- #
# Stock de Guías (videos cortos que se sobreponen para generar confianza)
# --------------------------------------------------------------------------- #
def list_guides() -> list[Path]:
    """Lista los videos de la guía del stock (ordenados por nombre)."""
    return sorted(p for p in guides_dir().iterdir()
                  if p.is_file() and p.suffix.lower() in VIDEO_EXT)


def save_guide(tmp_path: Path, filename: str) -> Path:
    """Guarda un video de guía en el stock con nombre saneado y único."""
    safe = "".join(c for c in Path(filename).stem if c.isalnum() or c in " -_").strip()
    safe = safe.replace(" ", "_") or "guia"
    ext = Path(filename).suffix.lower() or ".mp4"
    dest = guides_dir() / f"{safe}{ext}"
    i = 1
    while dest.exists():
        dest = guides_dir() / f"{safe}_{i}{ext}"
        i += 1
    shutil.move(str(tmp_path), str(dest))
    logger.info("Guía añadida al stock: %s", dest.name)
    return dest


def delete_guide(name: str) -> bool:
    """Borra un video de guía del stock por nombre de archivo."""
    target = (guides_dir() / name).resolve()
    if target.parent == guides_dir().resolve() and target.is_file():
        target.unlink()
        logger.info("Guía borrada del stock: %s", name)
        return True
    return False


# --------------------------------------------------------------------------- #
# SFX (generados con FFmpeg, sin copyright)
# --------------------------------------------------------------------------- #
_SFX_SPECS = {
    # nombre: (entrada lavfi, filtros de audio)
    "pop": (
        "sine=frequency=620:duration=0.12",
        "afade=t=out:st=0.0:d=0.12,volume=0.5",
    ),
    "ding": (
        "sine=frequency=1180:duration=0.6",
        "afade=t=out:st=0.06:d=0.54,volume=0.55",
    ),
    "whoosh": (
        "anoisesrc=d=0.55:c=pink:a=0.35",
        "highpass=f=350,lowpass=f=3800,afade=t=in:d=0.28,afade=t=out:st=0.28:d=0.27,volume=0.5",
    ),
}


def ensure_sfx() -> dict[str, Path]:
    """Genera (si faltan) los SFX whoosh/pop/ding y devuelve sus rutas."""
    out: dict[str, Path] = {}
    for name, (src, af) in _SFX_SPECS.items():
        dest = sfx_dir() / f"{name}.m4a"
        if not dest.exists():
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", src,
                   "-af", af, "-c:a", "aac", "-b:a", "128k", str(dest)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                logger.warning("No se pudo generar SFX %s: %s", name, proc.stderr[-300:])
                continue
        if dest.exists():
            out[name] = dest
    return out

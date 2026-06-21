"""Renderiza un proyecto de anuncio Remotion a mp4 usando el runtime persistente.

Degradación elegante: si no hay Node o el runtime no está instalado, no falla —
devuelve [] y el job entrega solo el proyecto editable (.zip).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

RUNTIME = BASE_DIR / "remotion-runtime"


def render_available() -> bool:
    """True si se puede renderizar (Node disponible y runtime instalado)."""
    return bool(shutil.which("node")) and (RUNTIME / "node_modules").exists()


def render_ad_project(project_dir: Path, out_dir: Path, timeout: int = 1800) -> list[Path]:
    """Renderiza todas las composiciones del proyecto a ``out_dir/clip_N.mp4``.

    Returns:
        Lista de rutas de los mp4 renderizados.

    Raises:
        RuntimeError: si el render falla.
    """
    if not render_available():
        raise RuntimeError("Render Remotion no disponible (falta Node o el runtime).")

    # Symlink node_modules del runtime dentro del proyecto (webpack resuelve imports).
    link = project_dir / "node_modules"
    if not link.exists():
        os.symlink(RUNTIME / "node_modules", link)

    script = RUNTIME / "render.mjs"
    logger.info("Renderizando anuncio con Remotion: %s", project_dir.name)
    proc = subprocess.run(
        ["node", str(script), str(project_dir), str(out_dir)],
        capture_output=True, text=True, cwd=str(RUNTIME), timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Render Remotion falló: {proc.stderr[-1000:]}")

    clips = sorted(out_dir.glob("clip_*.mp4"))
    if not clips:
        raise RuntimeError("El render de Remotion no produjo ningún video.")
    logger.info("Anuncio renderizado: %d video(s)", len(clips))
    return clips

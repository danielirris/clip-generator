"""Limpieza de temporales por job y purga de outputs antiguos."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_job_dir(work_dir: Path) -> None:
    """Borra por completo la carpeta de trabajo temporal de un job.

    Args:
        work_dir: carpeta ``storage/jobs/{job_id}`` a eliminar.
    """
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
        logger.info("Temporales borrados: %s", work_dir)


def delete_source(source: Path) -> None:
    """Borra el video fuente subido en cuanto deja de necesitarse."""
    try:
        if source.exists():
            source.unlink()
            logger.info("Video fuente borrado: %s", source.name)
    except OSError as exc:  # pragma: no cover - mejor esfuerzo
        logger.warning("No se pudo borrar el fuente %s: %s", source, exc)


def purge_old_outputs(outputs_dir: Path, retencion_horas: int) -> int:
    """Elimina los outputs con antigüedad mayor a ``retencion_horas``.

    Args:
        outputs_dir: carpeta ``storage/outputs``.
        retencion_horas: horas de retención.

    Returns:
        Número de archivos borrados.
    """
    if not outputs_dir.exists():
        return 0
    limite = time.time() - retencion_horas * 3600
    borrados = 0
    for item in outputs_dir.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < limite:
                item.unlink()
                borrados += 1
                logger.info("Output antiguo borrado: %s", item.name)
        except OSError as exc:  # pragma: no cover - mejor esfuerzo
            logger.warning("No se pudo borrar %s: %s", item, exc)
    return borrados

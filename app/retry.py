"""Utilidad de reintentos con backoff exponencial para llamadas de red."""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def with_retries(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.5,
    what: str = "operación",
) -> T:
    """Ejecuta ``func`` reintentando ante excepciones con backoff exponencial.

    Args:
        func: callable sin argumentos a ejecutar.
        attempts: número máximo de intentos.
        base_delay: retardo base en segundos (se duplica en cada intento).
        what: descripción para los logs.

    Returns:
        El resultado de ``func``.

    Raises:
        La última excepción si se agotan los intentos.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - reintento genérico intencional
            last_exc = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Fallo en %s (intento %d/%d): %s. Reintentando en %.1fs",
                what, attempt, attempts, exc, delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    logger.error("Agotados los reintentos de %s: %s", what, last_exc)
    raise last_exc

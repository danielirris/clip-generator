"""Persistencia de jobs en SQLite para sobrevivir reinicios del contenedor.

El estado vive también en memoria (rápido), pero se replica aquí para que, si
EasyPanel reinicia el contenedor a mitad de un trabajo, no se pierda: al arrancar
se reanudan los trabajos incompletos y se siguen pudiendo descargar los ya hechos.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JobStore:
    """Almacén SQLite de jobs (thread-safe con un lock global)."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                filenames   TEXT NOT NULL,
                status      TEXT NOT NULL,
                progress    INTEGER NOT NULL DEFAULT 0,
                message     TEXT DEFAULT '',
                error       TEXT DEFAULT '',
                aviso       TEXT DEFAULT '',
                n_clips     INTEGER DEFAULT 0,
                created_at  REAL NOT NULL,
                output_dir  TEXT,
                sources     TEXT NOT NULL,
                music       TEXT,
                mode        TEXT NOT NULL DEFAULT 'montage',
                voz         TEXT
            )
            """
        )
        # Migraciones para bases existentes sin columnas nuevas.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        if "mode" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'montage'")
        if "voz" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN voz TEXT")
        self._conn.commit()

    def save(
        self,
        *,
        id: str,
        filenames: list[str],
        status: str,
        created_at: float,
        sources: list[Path],
        music: list[Path],
        mode: str = "montage",
        voz: Path | None = None,
    ) -> None:
        """Inserta (o reemplaza) un job recién creado. ``music`` es una lista de pistas."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs "
                "(id, filenames, status, progress, message, error, aviso, n_clips, "
                " created_at, output_dir, sources, music, mode, voz) "
                "VALUES (?, ?, ?, 0, 'En cola', '', '', 0, ?, NULL, ?, ?, ?, ?)",
                (
                    id, json.dumps(filenames), status, created_at,
                    json.dumps([str(p) for p in sources]),
                    json.dumps([str(p) for p in music]), mode,
                    str(voz) if voz else None,
                ),
            )
            self._conn.commit()

    def update(self, job_id: str, fields: dict[str, Any]) -> None:
        """Actualiza columnas de un job."""
        allowed = {"status", "progress", "message", "error", "aviso",
                   "n_clips", "output_dir"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id)
            )
            self._conn.commit()

    def get_one(self, job_id: str) -> sqlite3.Row | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
            return cur.fetchone()

    def incomplete(self) -> list[sqlite3.Row]:
        """Jobs que no terminaron (para reanudar tras un reinicio)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM jobs WHERE status NOT IN ('done', 'error')"
            )
            return cur.fetchall()

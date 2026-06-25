"""Tests de la retención por-conteo (Galería) y la librería de guías."""
import time
from pathlib import Path

from app.pipeline import analyze
from app.pipeline.cleanup import purge_keep_recent


def _touch_dir(base: Path, name: str, mtime: float) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "clip_1.mp4").write_bytes(b"x")
    import os
    os.utime(d, (mtime, mtime))
    return d


def test_purge_keep_recent_conserva_los_n_mas_nuevos(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    now = time.time()
    # 5 trabajos con fechas crecientes (job4 el más nuevo).
    for i in range(5):
        _touch_dir(outputs, f"job{i}", now - (5 - i) * 100)

    borrados = purge_keep_recent(outputs, keep_n=3)

    assert borrados == 2
    quedan = {p.name for p in outputs.iterdir()}
    assert quedan == {"job2", "job3", "job4"}  # los 3 más recientes


def test_purge_keep_recent_no_borra_si_caben(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    now = time.time()
    for i in range(2):
        _touch_dir(outputs, f"job{i}", now - i)
    assert purge_keep_recent(outputs, keep_n=25) == 0
    assert len(list(outputs.iterdir())) == 2


def test_plan_guias_parse_y_espaciado():
    """La IA puede devolver 'guias'; se limpian, espacian (>=4s) y limitan a 3."""
    data = {
        "guias": [
            {"at": 1.0}, {"at": 2.0},          # 2.0 cae por el espaciado (<4s)
            {"at": 6.0}, {"at": 12.0}, {"at": 20.0},
            {"at": "x"},                        # inválido -> se ignora
        ]
    }
    # Reutilizamos el espaciador y el clamp como en plan_ad.
    guias = []
    for it in data["guias"]:
        try:
            at = max(0.0, min(30.0, float(it["at"])))
        except (TypeError, ValueError):
            continue
        guias.append({"at": round(at, 2)})
    out = analyze._spaced(guias, "at", 4.0, 3)
    ats = [g["at"] for g in out]
    assert ats == [1.0, 6.0, 12.0]  # espaciados >=4s y máximo 3

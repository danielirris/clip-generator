"""Tests del cálculo de beats de 2s para llegar a la duración objetivo."""
from app.pipeline.analyze import Clip
from app.pipeline.render import select_beats, build_beat_ass, _ass_time
from app.pipeline.transcribe import Segment


def _clip(start, end, score):
    return Clip(start=start, end=end, score=score, razon="")


def test_single_clip_sliced_into_beats():
    # Un clip de 8s -> 4 beats de 2s.
    beats = select_beats([_clip(0, 8, 100)], total_beats=24, beat_s=2)
    assert beats == [0.0, 2.0, 4.0, 6.0]


def test_stops_at_total_beats():
    # Material de sobra, pero solo queremos 3 beats.
    beats = select_beats([_clip(0, 100, 100)], total_beats=3, beat_s=2)
    assert len(beats) == 3
    assert beats == [0.0, 2.0, 4.0]


def test_fills_from_next_clips_by_score():
    clips = [
        _clip(10, 12, 90),   # 1 beat
        _clip(20, 24, 80),   # 2 beats
        _clip(30, 32, 70),   # 1 beat
    ]
    beats = select_beats(clips, total_beats=4, beat_s=2)
    assert beats == [10.0, 20.0, 22.0, 30.0]


def test_insufficient_material_returns_partial():
    # Solo hay 3 beats de material pero pedimos 24.
    clips = [_clip(0, 2, 90), _clip(5, 7, 80), _clip(9, 11, 70)]
    beats = select_beats(clips, total_beats=24, beat_s=2)
    assert len(beats) == 3


def test_short_clip_yields_no_full_beat():
    # Un clip de 1.5s no llega a un beat completo de 2s.
    beats = select_beats([_clip(0, 1.5, 90)], total_beats=24, beat_s=2)
    assert beats == []


def test_overlap_is_skipped():
    # Dos clips que producen el mismo inicio de beat no se duplican.
    clips = [_clip(0, 2, 90), _clip(0.5, 2.5, 80)]
    beats = select_beats(clips, total_beats=24, beat_s=2)
    assert beats == [0.0]


def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(65.5) == "0:01:05.50"


def test_build_beat_ass_retimes_segments():
    segs = [
        Segment(0.0, 5.0, "antes"),     # solapa el inicio
        Segment(10.0, 11.0, "dentro"),  # dentro de la ventana [10,12)
        Segment(20.0, 22.0, "fuera"),   # fuera
    ]
    ass = build_beat_ass(segs, beat_start=10.0, beat_dur=2.0)
    assert "dentro" in ass
    assert "fuera" not in ass
    # El segmento "dentro" empieza en 0s local (10-10).
    assert "0:00:00.00" in ass
    assert "[V4+ Styles]" in ass

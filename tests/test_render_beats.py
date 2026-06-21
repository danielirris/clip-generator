"""Tests del pool de fragmentos, composición, transiciones y subtítulos."""
import random
from pathlib import Path

from app.pipeline.analyze import Moment
from app.pipeline.fragments import VideoSource, Beat, video_beats, build_pool
from app.pipeline.compose import compose_clips, build_hook_beats, unique_beats
from app.pipeline.render import (
    build_beat_ass, _ass_time, plan_transitions, _xfade_offsets,
)
from app.pipeline.transcribe import Segment


def _vid(i, dur):
    return VideoSource(id=i, path=Path(f"/v{i}.mp4"), duration=dur)


def _rng():
    return random.Random(42)


# --- pool de fragmentos (duración variable 2-4s) ---
def test_video_beats_respect_min_max():
    beats = video_beats(_vid(0, 30), _rng(), 2.0, 4.0)
    assert beats, "debe producir beats"
    assert all(2.0 <= b.dur <= 4.0 for b in beats)
    # No se solapan y caben en el video.
    assert all(beats[i].start + beats[i].dur <= beats[i + 1].start + 1e-6
               for i in range(len(beats) - 1))
    assert beats[-1].start + beats[-1].dur <= 30 + 1e-6


def test_pool_interleaves_videos():
    pool = build_pool([_vid(0, 20), _vid(1, 20), _vid(2, 20)], _rng(), 2.0, 4.0)
    assert len({b.video_id for b in pool[:3]}) == 3  # ronda: 1 de cada uno


# --- composición ---
def test_compose_sums_to_target_duration():
    videos = [_vid(i, 60) for i in range(5)]
    rng = _rng()
    pool = build_pool(videos, rng, 2.0, 4.0)
    clips = compose_clips(pool, [], videos, rng, num_clips=5,
                          duracion_total_s=48, hook_beats=2, beat_min=2.0, beat_max=4.0)
    assert len(clips) == 5
    for clip in clips:
        assert abs(sum(b.dur for b in clip) - 48) < 1e-6


def test_compose_each_clip_mixes_all_videos():
    videos = [_vid(i, 60) for i in range(5)]
    rng = _rng()
    pool = build_pool(videos, rng, 2.0, 4.0)
    clips = compose_clips(pool, [], videos, rng, num_clips=5,
                          duracion_total_s=48, hook_beats=2, beat_min=2.0, beat_max=4.0)
    for clip in clips:
        assert len({b.video_id for b in clip}) == 5


def test_compose_clips_differ():
    videos = [_vid(i, 80) for i in range(5)]
    rng = _rng()
    pool = build_pool(videos, rng, 2.0, 4.0)
    clips = compose_clips(pool, [], videos, rng, num_clips=5,
                          duracion_total_s=48, hook_beats=2, beat_min=2.0, beat_max=4.0)
    sigs = {tuple(b.key() for b in c) for c in clips}
    assert len(sigs) == 5


def test_compose_hook_goes_first():
    videos = [_vid(i, 60) for i in range(3)]
    rng = _rng()
    pool = build_pool(videos, rng, 2.0, 4.0)
    clips = compose_clips(pool, [Moment(2, 10, 13, 99, "fuerte")], videos, rng,
                          num_clips=1, duracion_total_s=48, hook_beats=2,
                          beat_min=2.0, beat_max=4.0)
    assert clips[0][0].video_id == 2
    assert clips[0][0].start == 10.0


def test_build_hook_beats_default_when_no_moments():
    hooks = build_hook_beats([], [_vid(0, 10), _vid(1, 10)], _rng(), 2.0, 4.0)
    assert [h.start for h in hooks] == [0.0, 0.0]
    assert {h.video_id for h in hooks} == {0, 1}


def test_unique_beats_dedupes():
    b = Beat(0, Path("/v0.mp4"), 4.0, 2.0)
    assert len(unique_beats([[b, b], [b]])) == 1


# --- transiciones ---
def test_plan_transitions_count_in_range():
    plan = plan_transitions(20, _rng(), 3, 6, "variadas")
    assert 3 <= len(plan) <= 6
    idxs = [b for b, _ in plan]
    assert idxs == sorted(set(idxs))           # fronteras únicas y ordenadas
    assert all(1 <= b < 20 for b in idxs)


def test_plan_transitions_none_for_corte():
    assert plan_transitions(20, _rng(), 3, 6, "corte") == []


def test_plan_transitions_none_for_single_beat():
    assert plan_transitions(1, _rng(), 3, 6, "variadas") == []


def test_plan_transitions_fundido_uses_fade():
    plan = plan_transitions(20, _rng(), 3, 6, "fundido")
    assert all(t == "fade" for _, t in plan)


def test_xfade_offsets():
    assert _xfade_offsets([4.0, 3.0, 2.0], 0.5) == [3.5, 6.0]


# --- subtítulos ASS ---
def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(65.5) == "0:01:05.50"


def test_build_beat_ass_retimes_segments():
    segs = [Segment(0.0, 5.0, "antes"), Segment(10.0, 11.0, "dentro"),
            Segment(20.0, 22.0, "fuera")]
    ass = build_beat_ass(segs, beat_start=10.0, beat_dur=2.0)
    assert "dentro" in ass and "fuera" not in ass
    assert "0:00:00.00" in ass and "[V4+ Styles]" in ass

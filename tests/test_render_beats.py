"""Tests del pool de fragmentos, composición de clips y subtítulos ASS."""
from pathlib import Path

from app.pipeline.analyze import Moment
from app.pipeline.fragments import VideoSource, Beat, video_beats, build_pool
from app.pipeline.compose import compose_clips, build_hook_beats, unique_beats
from app.pipeline.render import build_beat_ass, _ass_time
from app.pipeline.transcribe import Segment


def _vid(i, dur):
    return VideoSource(id=i, path=Path(f"/v{i}.mp4"), duration=dur, segments=[])


# --- pool de fragmentos ---
def test_video_beats_non_overlapping():
    beats = video_beats(_vid(0, 8), beat_s=2)
    assert [b.start for b in beats] == [0.0, 2.0, 4.0, 6.0]


def test_video_beats_drops_partial_tail():
    # 7s -> 3 beats completos (0,2,4); el resto (6-7) no llega a 2s.
    assert len(video_beats(_vid(0, 7), beat_s=2)) == 3


def test_pool_interleaves_videos():
    pool = build_pool([_vid(0, 6), _vid(1, 6)], beat_s=2)
    # Round-robin: v0@0, v1@0, v0@2, v1@2, ...
    assert [b.video_id for b in pool[:4]] == [0, 1, 0, 1]
    assert len(pool) == 6  # 3 beats por video


def test_pool_any_window_mixes_videos():
    pool = build_pool([_vid(i, 10) for i in range(3)], beat_s=2)
    # Cualquier ventana de >=3 beats cubre los 3 videos.
    assert len({b.video_id for b in pool[:3]}) == 3


# --- composición de clips ---
def test_compose_produces_requested_clips():
    videos = [_vid(i, 30) for i in range(4)]
    pool = build_pool(videos, beat_s=2)
    moments = [Moment(0, 4, 6, 90, "a"), Moment(1, 2, 4, 80, "b")]
    clips = compose_clips(pool, moments, videos,
                          num_clips=5, total_beats=24, hook_beats=2, beat_s=2)
    assert len(clips) == 5
    assert all(len(c) == 24 for c in clips)


def test_compose_hooks_go_first():
    videos = [_vid(i, 30) for i in range(3)]
    pool = build_pool(videos, beat_s=2)
    moments = [Moment(2, 10, 12, 99, "fuerte")]
    clips = compose_clips(pool, moments, videos,
                          num_clips=1, total_beats=24, hook_beats=2, beat_s=2)
    # El primer beat es el gancho del video 2 en t=10.
    assert clips[0][0].video_id == 2
    assert clips[0][0].start == 10.0


def test_compose_clips_each_mix_all_videos():
    videos = [_vid(i, 40) for i in range(5)]
    pool = build_pool(videos, beat_s=2)
    clips = compose_clips(pool, [], videos,
                          num_clips=5, total_beats=24, hook_beats=2, beat_s=2)
    for clip in clips:
        assert len({b.video_id for b in clip}) == 5  # los 5 videos presentes


def test_compose_clips_differ():
    videos = [_vid(i, 60) for i in range(5)]
    pool = build_pool(videos, beat_s=2)
    clips = compose_clips(pool, [], videos,
                          num_clips=5, total_beats=24, hook_beats=2, beat_s=2)
    sigs = {tuple(b.key() for b in c) for c in clips}
    assert len(sigs) == 5  # las 5 combinaciones son distintas


def test_build_hook_beats_default_when_no_moments():
    videos = [_vid(0, 10), _vid(1, 10)]
    hooks = build_hook_beats([], videos, beat_s=2)
    assert [h.start for h in hooks] == [0.0, 0.0]
    assert {h.video_id for h in hooks} == {0, 1}


def test_unique_beats_dedupes():
    b = Beat(0, Path("/v0.mp4"), 4.0)
    clips = [[b, b], [b]]
    assert len(unique_beats(clips)) == 1


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

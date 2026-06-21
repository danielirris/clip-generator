"""Tests del parseo robusto del JSON de ganchos (OpenAI)."""
import pytest

from app.pipeline.analyze import parse_moments_json, build_prompt
from app.pipeline.transcribe import Segment


def test_parse_plain_json():
    text = '{"momentos": [{"video": 0, "start": 1, "end": 3, "score": 90, "razon": "gancho"}]}'
    m = parse_moments_json(text)
    assert len(m) == 1
    assert m[0].video_id == 0
    assert m[0].start == 1.0 and m[0].end == 3.0
    assert m[0].score == 90.0


def test_parse_with_code_fences():
    text = '```json\n{"momentos": [{"video": 1, "start": 0, "end": 2, "score": 50, "razon": "x"}]}\n```'
    m = parse_moments_json(text)
    assert m[0].razon == "x" and m[0].video_id == 1


def test_parse_orders_by_score_desc():
    text = (
        '{"momentos": ['
        '{"video": 0, "start": 0, "end": 2, "score": 30, "razon": "a"},'
        '{"video": 0, "start": 5, "end": 7, "score": 95, "razon": "b"},'
        '{"video": 1, "start": 9, "end": 11, "score": 60, "razon": "c"}]}'
    )
    m = parse_moments_json(text)
    assert [x.score for x in m] == [95.0, 60.0, 30.0]


def test_parse_filters_out_of_range_video():
    text = (
        '{"momentos": ['
        '{"video": 9, "start": 0, "end": 2, "score": 80, "razon": "fuera"},'
        '{"video": 0, "start": 1, "end": 4, "score": 70, "razon": "ok"}]}'
    )
    m = parse_moments_json(text, num_videos=2)
    assert len(m) == 1 and m[0].razon == "ok"


def test_parse_skips_invalid_entries():
    text = (
        '{"momentos": ['
        '{"video": 0, "start": 0, "end": 0, "score": 10, "razon": "vacio"},'
        '{"video": 0, "start": 1, "end": 4, "score": 80, "razon": "ok"},'
        '{"foo": "bar"}]}'
    )
    m = parse_moments_json(text)
    assert len(m) == 1 and m[0].razon == "ok"


def test_parse_extracts_embedded_json():
    text = 'Aquí: {"momentos": [{"video": 0, "start": 2, "end": 5, "score": 40, "razon": "y"}]} fin.'
    assert len(parse_moments_json(text)) == 1


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_moments_json("no soy json")


def test_parse_no_moments_raises():
    with pytest.raises(ValueError):
        parse_moments_json('{"momentos": []}')


def test_build_prompt_labels_videos_and_strict():
    videos = [[Segment(0.0, 2.0, "hola")], [Segment(0.0, 1.0, "mundo")]]
    prompt = build_prompt(videos)
    assert "[0, 0.0-2.0] hola" in prompt
    assert "[1, 0.0-1.0] mundo" in prompt
    assert "no fue" not in prompt
    assert "ÚNICAMENTE" in build_prompt(videos, strict=True)

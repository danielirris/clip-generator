"""Tests del parseo robusto del JSON de Gemini."""
import pytest

from app.pipeline.analyze import parse_clips_json, build_prompt
from app.pipeline.transcribe import Segment


def test_parse_plain_json():
    text = '{"clips": [{"start": 1, "end": 3, "score": 90, "razon": "gancho"}]}'
    clips = parse_clips_json(text)
    assert len(clips) == 1
    assert clips[0].start == 1.0
    assert clips[0].end == 3.0
    assert clips[0].score == 90.0


def test_parse_with_code_fences():
    text = '```json\n{"clips": [{"start": 0, "end": 2, "score": 50, "razon": "x"}]}\n```'
    clips = parse_clips_json(text)
    assert len(clips) == 1
    assert clips[0].razon == "x"


def test_parse_orders_by_score_desc():
    text = (
        '{"clips": ['
        '{"start": 0, "end": 2, "score": 30, "razon": "a"},'
        '{"start": 5, "end": 7, "score": 95, "razon": "b"},'
        '{"start": 9, "end": 11, "score": 60, "razon": "c"}]}'
    )
    clips = parse_clips_json(text)
    assert [c.score for c in clips] == [95.0, 60.0, 30.0]


def test_parse_skips_invalid_entries():
    text = (
        '{"clips": ['
        '{"start": 0, "end": 0, "score": 10, "razon": "vacio"},'  # end<=start -> descartado
        '{"start": 1, "end": 4, "score": 80, "razon": "ok"},'
        '{"foo": "bar"}]}'                                          # sin start/end
    )
    clips = parse_clips_json(text)
    assert len(clips) == 1
    assert clips[0].razon == "ok"


def test_parse_extracts_embedded_json():
    text = 'Aquí tienes: {"clips": [{"start": 2, "end": 5, "score": 40, "razon": "y"}]} fin.'
    clips = parse_clips_json(text)
    assert len(clips) == 1


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_clips_json("no soy json")


def test_parse_no_clips_raises():
    with pytest.raises(ValueError):
        parse_clips_json('{"clips": []}')


def test_build_prompt_includes_timestamps_and_strict():
    segs = [Segment(0.0, 2.0, "hola mundo")]
    prompt = build_prompt(segs)
    assert "[0.0-2.0] hola mundo" in prompt
    assert "JSON" in prompt
    strict = build_prompt(segs, strict=True)
    assert "no fue JSON válido" in strict

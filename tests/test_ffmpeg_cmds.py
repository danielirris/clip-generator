"""Tests de la construcción de comandos FFmpeg (sin ejecutarlos)."""
from pathlib import Path

from app.pipeline.audio import build_extract_audio_cmd
from app.pipeline.render import (
    build_beat_cmd,
    build_concat_cmd,
    build_video_filter,
)


def test_extract_audio_cmd():
    cmd = build_extract_audio_cmd(Path("in.mp4"), Path("out.wav"))
    assert cmd[0] == "ffmpeg"
    assert "-vn" in cmd          # sin video
    assert "16000" in cmd        # 16 kHz
    assert "1" in cmd            # mono (-ac 1)
    assert cmd[-1] == "out.wav"


def test_video_filter_modes():
    blur = build_video_filter("blur")
    assert "boxblur" in blur
    assert "overlay" in blur
    assert blur.endswith("[v]")

    crop = build_video_filter("crop")
    assert "crop=1080:1920" in crop
    assert "boxblur" not in crop

    pad = build_video_filter("pad_negro")
    assert "pad=1080:1920" in pad
    assert "color=black" in pad


def test_video_filter_default_is_blur():
    # Un modo desconocido cae a blur por defecto.
    assert "boxblur" in build_video_filter("desconocido")


def test_beat_cmd_without_subtitles():
    cmd = build_beat_cmd(
        Path("src.mp4"), 4.0, 2.0, Path("beat.mp4"), "crop", ass_path=None
    )
    assert "-ss" in cmd
    assert "4.000" in cmd
    assert "2.000" in cmd
    assert "[v]" in cmd          # mapea la etiqueta sin subtítulos
    assert "libx264" in cmd
    assert cmd[-1] == "beat.mp4"


def test_beat_cmd_with_subtitles():
    cmd = build_beat_cmd(
        Path("src.mp4"), 0.0, 2.0, Path("beat.mp4"), "blur", ass_path=Path("s.ass")
    )
    joined = " ".join(cmd)
    assert "ass=" in joined       # filtro de subtítulos presente
    assert "[vout]" in cmd        # mapea la salida con subtítulos


def test_beat_cmd_seek_before_input():
    # -ss debe ir ANTES de -i para seek rápido y PTS local ~0.
    cmd = build_beat_cmd(Path("src.mp4"), 6.0, 2.0, Path("b.mp4"), "blur")
    assert cmd.index("-ss") < cmd.index("-i")


def test_concat_cmd_copies():
    cmd = build_concat_cmd(Path("list.txt"), Path("out.mp4"))
    assert "concat" in cmd
    assert "-c" in cmd and "copy" in cmd
    assert "+faststart" in cmd
    assert cmd[-1] == "out.mp4"

"""Tests de la construcción de comandos FFmpeg (sin ejecutarlos)."""
from pathlib import Path

from app.pipeline.audio import build_extract_audio_cmd
from app.pipeline.render import (
    build_beat_cmd,
    build_concat_cmd,
    build_concat_filter_cmd,
    build_video_filter,
    build_xfade_cmd,
    build_music_cmd,
)


def test_extract_audio_cmd():
    cmd = build_extract_audio_cmd(Path("in.mp4"), Path("out.wav"))
    assert cmd[0] == "ffmpeg"
    assert "-vn" in cmd and "16000" in cmd and "1" in cmd
    assert cmd[-1] == "out.wav"


def test_video_filter_modes():
    assert "boxblur" in build_video_filter("blur")
    assert "crop=1080:1920" in build_video_filter("crop")
    assert "pad=1080:1920" in build_video_filter("pad_negro")
    assert "boxblur" in build_video_filter("desconocido")  # default = blur


def test_beat_cmd_strips_audio():
    cmd = build_beat_cmd(Path("src.mp4"), 4.0, 2.0, Path("beat.mp4"), "crop")
    assert "-an" in cmd               # los beats no llevan audio
    assert "-ss" in cmd and "4.000" in cmd and "2.000" in cmd
    assert "[v]" in cmd and "libx264" in cmd
    assert cmd.index("-ss") < cmd.index("-i")  # seek rápido antes de -i


def test_beat_cmd_with_subtitles():
    cmd = build_beat_cmd(Path("src.mp4"), 0.0, 2.0, Path("b.mp4"), "blur",
                         ass_path=Path("s.ass"))
    assert "ass=" in " ".join(cmd) and "[vout]" in cmd


def test_concat_cmd_copies():
    cmd = build_concat_cmd(Path("list.txt"), Path("out.mp4"))
    assert "concat" in cmd and "-c" in cmd and "copy" in cmd
    assert cmd[-1] == "out.mp4"


def test_concat_filter_cmd_reencodes():
    cmd = build_concat_filter_cmd([Path("a.mp4"), Path("b.mp4"), Path("c.mp4")],
                                  Path("g.mp4"))
    joined = " ".join(cmd)
    assert "concat=n=3:v=1:a=0" in joined   # filtro concat (PTS limpios)
    assert "libx264" in cmd                 # re-codifica
    assert cmd[-1] == "g.mp4"


def test_xfade_cmd_builds_chain():
    cmd = build_xfade_cmd(
        [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")],
        [4.0, 3.0, 2.0], ["fade", "slideleft"], 0.5, Path("out.mp4"),
    )
    joined = " ".join(cmd)
    assert joined.count("xfade") == 2          # 3 bloques -> 2 transiciones
    assert "transition=fade" in joined and "transition=slideleft" in joined
    assert "[vout]" in cmd and cmd[-1] == "out.mp4"


def test_music_cmd_loops_and_replaces_audio():
    cmd = build_music_cmd(Path("v.mp4"), Path("m.mp3"), Path("out.mp4"))
    assert "-stream_loop" in cmd and "-shortest" in cmd
    assert "0:v" in cmd and "1:a" in cmd       # video del clip + audio de la música
    assert cmd[-1] == "out.mp4"

"""Render: normalización 9:16, subtítulos y concatenación de varios clips.

Estrategia optimizada para bajo uso de CPU/RAM:
  1. Cada beat de 2s (de cualquier video del lote) se normaliza UNA sola vez a
     1080x1920 con el fondo elegido y subtítulos quemados (re-temporizados a la
     ventana local 0..2s). Los beats compartidos entre clips se cachean.
  2. Todos los beats comparten los mismos parámetros de códec, así que cada clip
     se arma concatenando con el demuxer concat y ``-c copy`` (sin recodificar).
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.fragments import Beat
from app.pipeline.transcribe import Segment

logger = logging.getLogger(__name__)

# Parámetros fijos del formato de salida.
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Parámetros de códec compartidos por todos los beats (necesario para -c copy).
_VIDEO_ENC = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "23",
    "-pix_fmt", "yuv420p",
    "-r", str(FPS),
    "-g", str(FPS * 2),
    "-profile:v", "high",
]
_AUDIO_ENC = [
    "-c:a", "aac",
    "-b:a", "128k",
    "-ar", "44100",
    "-ac", "2",
]


@dataclass
class RenderResult:
    """Resultado del render de un lote: rutas de los clips y metadatos."""

    clips: list[Path] = field(default_factory=list)
    beats_unicos: int = 0
    duracion_clip_s: float = 0.0
    aviso: str = ""


# --------------------------------------------------------------------------- #
# Subtítulos (ASS) por beat
# --------------------------------------------------------------------------- #
def _ass_time(seconds: float) -> str:
    """Formatea segundos como ``H:MM:SS.cc`` (centisegundos) para ASS."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass_text(text: str) -> str:
    """Escapa texto para el campo Text de un Dialogue de ASS."""
    return text.replace("{", "(").replace("}", ")").replace("\n", r"\N").strip()


_ASS_HEADER = f"""\
[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,90,&H00FFFFFF,&H00000000,&H80000000,1,0,1,5,2,2,60,60,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_beat_ass(
    segments: list[Segment],
    beat_start: float,
    beat_dur: float,
) -> str:
    """Genera el contenido ASS de un beat, re-temporizado a la ventana local.

    Los segmentos que solapan ``[beat_start, beat_start + beat_dur)`` se desplazan
    al rango local ``[0, beat_dur)``.
    """
    lines: list[str] = []
    beat_end = beat_start + beat_dur
    for seg in segments:
        if seg.end <= beat_start or seg.start >= beat_end:
            continue
        local_start = max(0.0, seg.start - beat_start)
        local_end = min(beat_dur, seg.end - beat_start)
        if local_end <= local_start:
            continue
        text = _escape_ass_text(seg.text)
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(local_start)},{_ass_time(local_end)},"
            f"Default,,0,0,0,,{text}"
        )
    return _ASS_HEADER + "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Construcción de comandos FFmpeg
# --------------------------------------------------------------------------- #
def build_video_filter(modo_fondo: str) -> str:
    """Devuelve la cadena de filtros que produce la etiqueta ``[v]`` en 9:16."""
    if modo_fondo == "crop":
        return (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},fps={FPS}[v]"
        )
    if modo_fondo == "pad_negro":
        return (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,fps={FPS}[v]"
        )
    # blur (por defecto): fondo difuminado + video centrado.
    return (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},boxblur=20:2[bgb];"
        f"[fg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,fps={FPS}[v]"
    )


def _escape_filter_path(path: Path) -> str:
    """Escapa una ruta para usarla entre comillas simples en un filtergraph."""
    return str(path).replace("\\", "\\\\").replace("'", "\\'")


def build_beat_cmd(
    source: Path,
    beat_start: float,
    beat_dur: float,
    dest: Path,
    modo_fondo: str,
    ass_path: Path | None = None,
) -> list[str]:
    """Construye el comando FFmpeg para extraer y normalizar un beat."""
    vfilter = build_video_filter(modo_fondo)
    if ass_path is not None:
        vfilter += f";[v]ass='{_escape_filter_path(ass_path)}'[vout]"
        vlabel = "[vout]"
    else:
        vlabel = "[v]"

    return [
        "ffmpeg",
        "-y",
        "-ss", f"{beat_start:.3f}",   # seek rápido (antes de -i): PTS local ~0
        "-i", str(source),
        "-t", f"{beat_dur:.3f}",
        "-filter_complex", vfilter,
        "-map", vlabel,
        "-map", "0:a?",              # audio opcional
        *_VIDEO_ENC,
        *_AUDIO_ENC,
        "-shortest",
        str(dest),
    ]


def build_concat_cmd(list_file: Path, dest: Path) -> list[str]:
    """Construye el comando FFmpeg para concatenar beats sin re-codificar."""
    return [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(dest),
    ]


# --------------------------------------------------------------------------- #
# Orquestación del render de varios clips
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], descripcion: str) -> None:
    """Ejecuta un comando FFmpeg y lanza RuntimeError si falla."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falló ({descripcion}): {proc.stderr[-800:]}")


def render_clips(
    clips: list[list[Beat]],
    segments_by_video: dict[int, list[Segment]],
    work_dir: Path,
    output_dir: Path,
    *,
    beat_s: float,
    modo_fondo: str,
    subtitulos: bool,
) -> RenderResult:
    """Renderiza los beats únicos una vez y arma cada clip por concatenación.

    Args:
        clips: lista de clips; cada clip es una lista ordenada de ``Beat``.
        segments_by_video: mapea ``video_id`` -> segmentos (para subtítulos).
        work_dir: carpeta de trabajo del job (beats temporales).
        output_dir: carpeta donde se escriben ``clip_1.mp4 ...``.
        beat_s: duración de cada beat.
        modo_fondo: blur | crop | pad_negro.
        subtitulos: si se queman subtítulos.

    Returns:
        ``RenderResult`` con las rutas de los clips y metadatos.

    Raises:
        RuntimeError: si no hay beats o FFmpeg falla.
    """
    from app.pipeline.compose import unique_beats

    if not clips or not any(clips):
        raise RuntimeError("No hay beats para renderizar.")

    beats_dir = work_dir / "beats"
    beats_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Renderizar cada beat único una sola vez (cache por clave).
    cache: dict[tuple[int, int], Path] = {}
    for beat in unique_beats(clips):
        vid, ms = beat.key()
        dest = beats_dir / f"beat_v{vid}_{ms}.mp4"
        ass_path: Path | None = None
        if subtitulos:
            ass_path = beats_dir / f"beat_v{vid}_{ms}.ass"
            ass_path.write_text(
                build_beat_ass(segments_by_video.get(vid, []), beat.start, beat_s),
                encoding="utf-8",
            )
        _run(
            build_beat_cmd(beat.source, beat.start, beat_s, dest, modo_fondo, ass_path),
            f"beat v{vid}@{beat.start:.1f}s",
        )
        cache[beat.key()] = dest
    logger.info("Beats únicos renderizados: %d", len(cache))

    # 2) Armar cada clip concatenando sus beats (en orden) con -c copy.
    outputs: list[Path] = []
    for i, clip in enumerate(clips, start=1):
        list_file = work_dir / f"concat_{i}.txt"
        list_file.write_text(
            "".join(f"file '{cache[b.key()].as_posix()}'\n" for b in clip),
            encoding="utf-8",
        )
        dest = output_dir / f"clip_{i}.mp4"
        _run(build_concat_cmd(list_file, dest), f"concat clip {i}")
        outputs.append(dest)
        logger.info("Clip %d/%d listo (%d beats)", i, len(clips), len(clip))

    duracion = (len(clips[0]) * beat_s) if clips else 0.0
    return RenderResult(
        clips=outputs,
        beats_unicos=len(cache),
        duracion_clip_s=duracion,
    )

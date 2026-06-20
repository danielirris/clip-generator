"""Render: selección de beats, normalización 9:16, subtítulos y concatenación.

Estrategia optimizada para bajo uso de CPU/RAM:
  1. Cada beat de 2s se extrae YA normalizado a 1080x1920 con el fondo elegido
     y con sus subtítulos quemados (re-temporizados a la ventana local 0..2s).
  2. Todos los beats comparten exactamente los mismos parámetros de códec, por
     lo que la concatenación final usa el demuxer concat con ``-c copy`` (sin
     re-codificar de nuevo). Resultado: un único pase de codificación.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.analyze import Clip
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
    """Resultado del render con metadatos útiles para el estado del job."""

    output_path: Path
    beats_usados: int
    duracion_real_s: float
    completo: bool  # True si se alcanzó la duración objetivo
    aviso: str = ""


# --------------------------------------------------------------------------- #
# Selección y troceo en beats
# --------------------------------------------------------------------------- #
def select_beats(
    clips: list[Clip],
    total_beats: int,
    beat_s: float,
) -> list[float]:
    """Trocea los clips (por score desc.) en beats de ``beat_s`` segundos.

    Recorre los clips en orden de score, generando beats consecutivos dentro de
    cada clip. Evita solapamientos cuasi-idénticos y para al llegar a
    ``total_beats``.

    Args:
        clips: clips propuestos por la IA, idealmente ya ordenados por score.
        total_beats: número de beats objetivo (p.ej. 24).
        beat_s: duración de cada beat en segundos.

    Returns:
        Lista de tiempos de inicio (en segundos del video fuente), un valor por
        beat, con longitud <= ``total_beats``.
    """
    ordered = sorted(clips, key=lambda c: c.score, reverse=True)
    starts: list[float] = []
    used: list[float] = []

    def overlaps(start: float) -> bool:
        return any(abs(start - u) < beat_s for u in used)

    for clip in ordered:
        t = clip.start
        # Generamos beats completos mientras quepan dentro del clip.
        while t + beat_s <= clip.end + 1e-6:
            if len(starts) >= total_beats:
                return starts
            start = round(t, 3)
            if not overlaps(start):
                starts.append(start)
                used.append(start)
            t += beat_s
    return starts


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
    if cs == 100:  # redondeo hacia arriba
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

    Los segmentos que solapan ``[beat_start, beat_start + beat_dur)`` se
    desplazan al rango local ``[0, beat_dur)``.

    Args:
        segments: segmentos de la transcripción completa.
        beat_start: inicio del beat en segundos del video fuente.
        beat_dur: duración del beat en segundos.

    Returns:
        Cadena con el documento ASS completo.
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
    """Devuelve la cadena de filtros que produce la etiqueta ``[v]`` en 9:16.

    Args:
        modo_fondo: ``blur`` | ``crop`` | ``pad_negro``.

    Returns:
        Filtergraph (sin subtítulos) que termina en la etiqueta ``[v]``.
    """
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
    """Escapa una ruta para usarla entre comillas simples en un filtergraph.

    Dentro de comillas simples FFmpeg toma los caracteres (incluido ``:``)
    literalmente, así que solo hay que escapar la barra invertida y la propia
    comilla simple.
    """
    return str(path).replace("\\", "\\\\").replace("'", "\\'")


def build_beat_cmd(
    source: Path,
    beat_start: float,
    beat_dur: float,
    dest: Path,
    modo_fondo: str,
    ass_path: Path | None = None,
) -> list[str]:
    """Construye el comando FFmpeg para extraer y normalizar un beat.

    Args:
        source: video fuente.
        beat_start: inicio del beat en segundos.
        beat_dur: duración del beat en segundos.
        dest: ruta del beat normalizado de salida.
        modo_fondo: modo de fondo (blur | crop | pad_negro).
        ass_path: si se indica, se queman los subtítulos de ese archivo ASS.

    Returns:
        Lista de argumentos para ``subprocess.run``.
    """
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
# Orquestación del render
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], descripcion: str) -> None:
    """Ejecuta un comando FFmpeg y lanza RuntimeError si falla."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falló ({descripcion}): {proc.stderr[-800:]}")


def render_clip(
    source: Path,
    segments: list[Segment],
    clips: list[Clip],
    work_dir: Path,
    output_path: Path,
    *,
    total_beats: int,
    beat_s: float,
    modo_fondo: str,
    subtitulos: bool,
) -> RenderResult:
    """Genera el clip vertical final a partir de los beats seleccionados.

    Args:
        source: video fuente.
        segments: segmentos de la transcripción (para subtítulos).
        clips: clips impactantes (ordenados por score).
        work_dir: carpeta de trabajo del job para los archivos temporales.
        output_path: ruta del mp4 final.
        total_beats: beats objetivo (p.ej. 24).
        beat_s: duración de cada beat (s).
        modo_fondo: blur | crop | pad_negro.
        subtitulos: si se queman subtítulos.

    Returns:
        ``RenderResult`` con la ruta final y metadatos (duración, aviso...).

    Raises:
        RuntimeError: si no hay material o FFmpeg falla.
    """
    beat_starts = select_beats(clips, total_beats, beat_s)
    if not beat_starts:
        raise RuntimeError("No hay material suficiente para generar ningún beat.")

    beats_dir = work_dir / "beats"
    beats_dir.mkdir(parents=True, exist_ok=True)

    beat_files: list[Path] = []
    for i, start in enumerate(beat_starts):
        beat_dest = beats_dir / f"beat_{i:03d}.mp4"
        ass_path: Path | None = None
        if subtitulos:
            ass_path = beats_dir / f"beat_{i:03d}.ass"
            ass_path.write_text(build_beat_ass(segments, start, beat_s), encoding="utf-8")
        cmd = build_beat_cmd(source, start, beat_s, beat_dest, modo_fondo, ass_path)
        _run(cmd, f"beat {i}")
        beat_files.append(beat_dest)
        logger.info("Beat %d/%d listo (start=%.2fs)", i + 1, len(beat_starts), start)

    # Lista para el demuxer concat.
    list_file = work_dir / "concat.txt"
    list_file.write_text(
        "".join(f"file '{bf.as_posix()}'\n" for bf in beat_files),
        encoding="utf-8",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(build_concat_cmd(list_file, output_path), "concat final")

    duracion_real = len(beat_files) * beat_s
    completo = len(beat_files) >= total_beats
    aviso = ""
    if not completo:
        aviso = (
            f"Material insuficiente para {total_beats * beat_s:.0f}s. "
            f"Se generó el clip más largo posible: {duracion_real:.0f}s "
            f"({len(beat_files)} beats)."
        )
        logger.warning(aviso)

    return RenderResult(
        output_path=output_path,
        beats_usados=len(beat_files),
        duracion_real_s=duracion_real,
        completo=completo,
        aviso=aviso,
    )

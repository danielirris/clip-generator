"""Render: 9:16, subtítulos, transiciones (xfade), música y concatenación.

Pipeline por clip:
  1. Cada fragmento (de cualquier video) se normaliza UNA vez a 1080x1920, sin
     audio y con subtítulos quemados. Los fragmentos compartidos se cachean.
  2. Se agrupan los fragmentos en bloques separados por las transiciones; cada
     bloque se concatena con ``-c copy`` (corte seco) y los bloques se unen con
     ``xfade`` (transiciones variadas).
  3. Se sustituye el audio por la MÚSICA del lote (el audio original se descarta).
"""
from __future__ import annotations

import logging
import random
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.fragments import Beat
from app.pipeline.transcribe import Segment

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Transiciones de xfade para el modo "variadas".
_TRANS_VARIADAS = [
    "fade", "wipeleft", "wiperight", "slideup", "slidedown",
    "circleopen", "dissolve", "smoothleft", "smoothright",
]

_VIDEO_ENC = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "23",
    "-pix_fmt", "yuv420p",
    "-r", str(FPS),
    "-g", str(FPS * 2),
    "-profile:v", "high",
]


@dataclass
class RenderResult:
    """Resultado del render de un lote: rutas de clips, timelines y beats."""

    clips: list[Path] = field(default_factory=list)
    beats_unicos: int = 0
    timelines: list[dict] = field(default_factory=list)
    beat_files: dict = field(default_factory=dict)  # key -> Path del beat normalizado
    aviso: str = ""


# --------------------------------------------------------------------------- #
# Subtítulos (ASS)
# --------------------------------------------------------------------------- #
def _ass_time(seconds: float) -> str:
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


def beat_subtitle_text(segments: list[Segment], start: float, dur: float) -> str:
    """Texto de subtítulo visible durante un fragmento (para el timeline)."""
    end = start + dur
    parts = [s.text for s in segments if not (s.end <= start or s.start >= end)]
    return " ".join(parts).strip()


def build_beat_ass(segments: list[Segment], beat_start: float, beat_dur: float) -> str:
    """Genera el ASS de un fragmento, re-temporizado a la ventana local 0..dur."""
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
        if text:
            lines.append(
                f"Dialogue: 0,{_ass_time(local_start)},{_ass_time(local_end)},"
                f"Default,,0,0,0,,{text}"
            )
    return _ASS_HEADER + "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Filtros / comandos
# --------------------------------------------------------------------------- #
def build_video_filter(modo_fondo: str) -> str:
    """Filtro que produce ``[v]`` en 9:16 según el modo de fondo."""
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
    return (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},boxblur=20:2[bgb];"
        f"[fg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,fps={FPS}[v]"
    )


def _escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace("'", "\\'")


def build_beat_cmd(
    source: Path, beat_start: float, beat_dur: float, dest: Path,
    modo_fondo: str, ass_path: Path | None = None,
) -> list[str]:
    """Comando FFmpeg para extraer y normalizar un fragmento (sin audio)."""
    vfilter = build_video_filter(modo_fondo)
    if ass_path is not None:
        vfilter += f";[v]ass='{_escape_filter_path(ass_path)}'[vout]"
        vlabel = "[vout]"
    else:
        vlabel = "[v]"
    return [
        "ffmpeg", "-y",
        "-ss", f"{beat_start:.3f}", "-i", str(source), "-t", f"{beat_dur:.3f}",
        "-filter_complex", vfilter,
        "-map", vlabel, "-an",          # sin audio (la música se añade al final)
        *_VIDEO_ENC, str(dest),
    ]


def build_concat_cmd(list_file: Path, dest: Path) -> list[str]:
    """Concatena fragmentos (mismo códec) sin re-codificar (corte seco)."""
    return [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(dest),
    ]


def build_concat_filter_cmd(files: list[Path], dest: Path) -> list[str]:
    """Concatena con el filtro ``concat`` (re-codifica, PTS limpios para xfade).

    El demuxer ``concat`` con ``-c copy`` deja timestamps que ``xfade`` interpreta
    mal; el filtro ``concat`` produce una secuencia con PTS continuos correctos.
    """
    cmd: list[str] = ["ffmpeg", "-y"]
    for f in files:
        cmd += ["-i", str(f)]
    labels = "".join(f"[{i}:v]" for i in range(len(files)))
    cmd += [
        "-filter_complex", f"{labels}concat=n={len(files)}:v=1:a=0[v]",
        "-map", "[v]", *_VIDEO_ENC, str(dest),
    ]
    return cmd


def plan_transitions(
    num_beats: int, rng: random.Random, tmin: int, tmax: int, modo: str,
) -> list[tuple[int, str]]:
    """Planifica las transiciones de un clip.

    Returns:
        Lista de ``(indice_de_frontera, tipo)``; la frontera ``i`` separa el
        fragmento ``i-1`` del ``i``. Lista vacía => solo cortes secos.
    """
    if modo == "corte" or num_beats < 2:
        return []
    t = max(0, min(tmax, num_beats - 1))
    t = rng.randint(min(tmin, t), t) if t >= tmin else t
    if t <= 0:
        return []
    boundaries = sorted(rng.sample(range(1, num_beats), t))
    plan = []
    for b in boundaries:
        tipo = "fade" if modo == "fundido" else rng.choice(_TRANS_VARIADAS)
        plan.append((b, tipo))
    return plan


def _xfade_offsets(durs: list[float], overlap: float) -> list[float]:
    """Calcula los offsets de cada xfade al encadenar bloques."""
    offsets: list[float] = []
    comp = durs[0]
    for d in durs[1:]:
        offsets.append(round(comp - overlap, 3))
        comp = comp + d - overlap
    return offsets


def build_xfade_cmd(
    seg_files: list[Path], durs: list[float], types: list[str],
    overlap: float, dest: Path,
) -> list[str]:
    """Encadena bloques con xfade (transiciones) re-codificando una vez."""
    cmd: list[str] = ["ffmpeg", "-y"]
    for f in seg_files:
        cmd += ["-i", str(f)]
    offsets = _xfade_offsets(durs, overlap)
    parts: list[str] = []
    prev = "[0:v]"
    for i in range(1, len(seg_files)):
        out = f"[x{i}]" if i < len(seg_files) - 1 else "[vout]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition={types[i - 1]}:"
            f"duration={overlap}:offset={offsets[i - 1]}{out}"
        )
        prev = out
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", *_VIDEO_ENC, str(dest)]
    return cmd


def build_music_cmd(video_in: Path, music: Path, dest: Path) -> list[str]:
    """Sustituye el audio por la música (en bucle, recortada al video)."""
    return [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-stream_loop", "-1", "-i", str(music),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-shortest", str(dest),
    ]


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], descripcion: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falló ({descripcion}): {proc.stderr[-800:]}")


def _concat_group(beat_files: list[Path], work: Path, name: str) -> Path:
    """Concatena fragmentos con corte seco (demuxer copy). Para clips sin xfade."""
    if len(beat_files) == 1:
        return beat_files[0]
    list_file = work / f"{name}.txt"
    list_file.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in beat_files), encoding="utf-8"
    )
    dest = work / f"{name}.mp4"
    _run(build_concat_cmd(list_file, dest), f"concat {name}")
    return dest


def _concat_group_xfade(beat_files: list[Path], work: Path, name: str) -> Path:
    """Concatena un grupo que se va a unir con xfade (re-encode, PTS limpios)."""
    if len(beat_files) == 1:
        return beat_files[0]
    dest = work / f"{name}.mp4"
    _run(build_concat_filter_cmd(beat_files, dest), f"concat-filter {name}")
    return dest


def render_clips(
    clips: list[list[Beat]],
    segments_by_video: dict[int, list[Segment]],
    video_names: dict[int, str],
    work_dir: Path,
    output_dir: Path,
    rng: random.Random,
    *,
    modo_fondo: str,
    subtitulos: bool,
    transiciones: bool,
    trans_min: int,
    trans_max: int,
    modo_transicion: str,
    trans_dur: float,
    music_path: Path | None,
) -> RenderResult:
    """Renderiza los N clips: beats únicos cacheados, transiciones y música."""
    from app.pipeline.compose import unique_beats

    if not clips or not any(clips):
        raise RuntimeError("No hay fragmentos para renderizar.")

    beats_dir = work_dir / "beats"
    tmp_dir = work_dir / "tmp"
    beats_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Renderizar cada beat único (video-only + subtítulos).
    cache: dict[tuple, Path] = {}
    for beat in unique_beats(clips):
        v, ms, dms = beat.key()
        dest = beats_dir / f"beat_v{v}_{ms}_{dms}.mp4"
        ass_path: Path | None = None
        if subtitulos:
            ass_path = beats_dir / f"beat_v{v}_{ms}_{dms}.ass"
            ass_path.write_text(
                build_beat_ass(segments_by_video.get(v, []), beat.start, beat.dur),
                encoding="utf-8",
            )
        _run(build_beat_cmd(beat.source, beat.start, beat.dur, dest, modo_fondo, ass_path),
             f"beat v{v}@{beat.start:.1f}s")
        cache[beat.key()] = dest
    logger.info("Beats únicos renderizados: %d", len(cache))

    # 2) Armar cada clip (grupos + xfade) y añadir música.
    outputs: list[Path] = []
    timelines: list[dict] = []
    for ci, clip in enumerate(clips, start=1):
        plan = plan_transitions(
            len(clip), rng, trans_min, trans_max, modo_transicion
        ) if transiciones else []
        boundaries = [b for b, _ in plan]
        types = [t for _, t in plan]

        # Partir el clip en grupos según las fronteras de transición.
        groups: list[list[Beat]] = []
        cur: list[Beat] = []
        for idx, beat in enumerate(clip):
            if idx in boundaries and cur:
                groups.append(cur)
                cur = []
            cur.append(beat)
        if cur:
            groups.append(cur)

        # Concatenar cada grupo (corte seco).
        seg_files, seg_durs = [], []
        for gi, group in enumerate(groups):
            files = [cache[b.key()] for b in group]
            seg_files.append(_concat_group_xfade(files, tmp_dir, f"c{ci}_g{gi}"))
            seg_durs.append(sum(b.dur for b in group))

        # Unir los grupos: con xfade si hay transiciones, si no concat directo.
        clip_video = tmp_dir / f"clip_{ci}_video.mp4"
        if len(seg_files) == 1:
            clip_video = seg_files[0]
        elif types:
            _run(build_xfade_cmd(seg_files, seg_durs, types, trans_dur, clip_video),
                 f"xfade clip {ci}")
        else:
            clip_video = _concat_group(
                [cache[b.key()] for b in clip], tmp_dir, f"clip_{ci}_full"
            )

        # Música (sustituye el audio). Sin música -> clip sin audio.
        dest = output_dir / f"clip_{ci}.mp4"
        if music_path is not None:
            _run(build_music_cmd(clip_video, music_path, dest), f"música clip {ci}")
        else:
            _run(["ffmpeg", "-y", "-i", str(clip_video), "-c", "copy",
                  "-movflags", "+faststart", str(dest)], f"export clip {ci}")
        outputs.append(dest)

        # Timeline para Remotion.
        timelines.append(_build_timeline(ci, clip, boundaries, types,
                                         segments_by_video, video_names, trans_dur))
        logger.info("Clip %d/%d listo (%d fragmentos, %d transiciones)",
                    ci, len(clips), len(clip), len(types))

    return RenderResult(clips=outputs, beats_unicos=len(cache),
                        timelines=timelines, beat_files=cache)


def _build_timeline(
    index: int, clip: list[Beat], boundaries: list[int], types: list[str],
    segments_by_video: dict[int, list[Segment]], video_names: dict[int, str],
    trans_dur: float,
) -> dict:
    """Construye la 'receta' de un clip para el proyecto Remotion."""
    frags = []
    for i, beat in enumerate(clip):
        v, ms, dms = beat.key()
        frags.append({
            "file": f"beats/beat_v{v}_{ms}_{dms}.mp4",
            "video_id": v,
            "source": video_names.get(v, f"video_{v}"),
            "start": beat.start,
            "dur": beat.dur,
            "subtitle": beat_subtitle_text(segments_by_video.get(v, []), beat.start, beat.dur),
        })
    transitions = [{"after_fragment": b - 1, "type": t, "duration": trans_dur}
                   for b, t in zip(boundaries, types)]
    # Con xfade, cada transición solapa y resta su duración al total.
    duracion = sum(b.dur for b in clip) - len(transitions) * trans_dur
    return {
        "index": index,
        "duracion_s": round(duracion, 2),
        "fragments": frags,
        "transitions": transitions,
    }

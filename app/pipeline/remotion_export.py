"""Exporta un proyecto Remotion editable por job.

Genera en ``storage/outputs/{job_id}/remotion/``:
  - ``timeline.json``  -> receta de cada clip (fragmentos, tiempos, transiciones,
    subtítulos y música).
  - ``beats/``         -> fragmentos ya normalizados que referencia el timeline.
  - la música del lote (si hay).
  - ``PROMPT_EDICION.md`` -> tu prompt de edición.
  - una composición Remotion de ejemplo que lee ``timeline.json``.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.config import BASE_DIR
from app.pipeline.render import RenderResult, WIDTH, HEIGHT, FPS

logger = logging.getLogger(__name__)

_PROMPT_SRC = BASE_DIR / "remotion" / "PROMPT_EDICION.md"


def export_remotion(
    output_dir: Path,
    result: RenderResult,
    music_path: Path | None,
) -> Path:
    """Escribe el proyecto Remotion. Devuelve la carpeta ``remotion/``."""
    root = output_dir / "remotion"
    beats_dst = root / "beats"
    beats_dst.mkdir(parents=True, exist_ok=True)

    # Copiar los fragmentos referenciados por los timelines.
    for tl in result.timelines:
        for frag in tl["fragments"]:
            src = _find_beat(result, frag["file"])
            if src and src.exists():
                shutil.copy(src, beats_dst / Path(frag["file"]).name)

    # Música.
    music_name = None
    if music_path is not None and music_path.exists():
        music_name = f"music{music_path.suffix.lower()}"
        shutil.copy(music_path, root / music_name)

    # timeline.json
    timeline = {
        "width": WIDTH, "height": HEIGHT, "fps": FPS,
        "music": music_name,
        "clips": result.timelines,
    }
    (root / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Prompt de edición.
    if _PROMPT_SRC.exists():
        shutil.copy(_PROMPT_SRC, root / "PROMPT_EDICION.md")

    # Scaffold Remotion.
    _write_scaffold(root)
    logger.info("Proyecto Remotion exportado: %s", root)
    return root


def _find_beat(result: RenderResult, rel_file: str) -> Path | None:
    """Localiza el Path real de un fragmento por su nombre de archivo."""
    name = Path(rel_file).name
    for path in result.beat_files.values():
        if path.name == name:
            return path
    return None


def _write_scaffold(root: Path) -> None:
    """Escribe un proyecto Remotion mínimo que lee timeline.json."""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)

    (root / "package.json").write_text(_PACKAGE_JSON, encoding="utf-8")
    (root / "remotion.config.ts").write_text(_REMOTION_CONFIG, encoding="utf-8")
    (root / "tsconfig.json").write_text(_TSCONFIG, encoding="utf-8")
    (root / "README.md").write_text(_README, encoding="utf-8")
    (src / "index.ts").write_text(_INDEX_TS, encoding="utf-8")
    (src / "Root.tsx").write_text(_ROOT_TSX, encoding="utf-8")
    (src / "Clip.tsx").write_text(_CLIP_TSX, encoding="utf-8")


_PACKAGE_JSON = """\
{
  "name": "clip-generator-remotion",
  "version": "1.0.0",
  "scripts": {
    "studio": "remotion studio",
    "render": "remotion render"
  },
  "dependencies": {
    "@remotion/cli": "^4.0.0",
    "@remotion/transitions": "^4.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0",
    "remotion": "^4.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.0.0",
    "typescript": "^5.0.0"
  }
}
"""

_REMOTION_CONFIG = """\
import { Config } from '@remotion/cli/config';
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
"""

_TSCONFIG = """\
{
  "compilerOptions": {
    "target": "ES2018",
    "module": "ESNext",
    "jsx": "react-jsx",
    "esModuleInterop": true,
    "moduleResolution": "node",
    "resolveJsonModule": true,
    "strict": true,
    "skipLibCheck": true
  }
}
"""

_INDEX_TS = """\
import { registerRoot } from 'remotion';
import { RemotionRoot } from './Root';
registerRoot(RemotionRoot);
"""

_ROOT_TSX = """\
import React from 'react';
import { Composition } from 'remotion';
import timeline from '../timeline.json';
import { Clip } from './Clip';

// Registra una composición por cada clip del timeline.json.
export const RemotionRoot: React.FC = () => {
  return (
    <>
      {timeline.clips.map((clip: any) => (
        <Composition
          key={clip.index}
          id={`clip-${clip.index}`}
          component={Clip as any}
          durationInFrames={Math.round(clip.duracion_s * timeline.fps)}
          fps={timeline.fps}
          width={timeline.width}
          height={timeline.height}
          defaultProps={{ clip, music: timeline.music }}
        />
      ))}
    </>
  );
};
"""

_CLIP_TSX = """\
import React from 'react';
import { AbsoluteFill, Audio, Sequence, Video, staticFile } from 'remotion';
import { TransitionSeries, linearTiming } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { slide } from '@remotion/transitions/slide';
import { wipe } from '@remotion/transitions/wipe';

const fps = 30;

// Mapea el tipo de transición del timeline a una presentación de Remotion.
const presentation = (type: string) => {
  if (type?.startsWith('slide')) return slide();
  if (type?.startsWith('wipe')) return wipe();
  return fade();
};

export const Clip: React.FC<{ clip: any; music: string | null }> = ({ clip, music }) => {
  const transAfter: Record<number, any> = {};
  for (const t of clip.transitions) transAfter[t.after_fragment] = t;

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <TransitionSeries>
        {clip.fragments.map((frag: any, i: number) => {
          const dur = Math.round(frag.dur * fps);
          const out = [
            <TransitionSeries.Sequence key={`s${i}`} durationInFrames={dur}>
              <Video src={staticFile(frag.file)} />
              {frag.subtitle ? (
                <AbsoluteFill style={{
                  justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 160,
                }}>
                  <span style={{
                    color: 'white', fontSize: 64, fontWeight: 800, textAlign: 'center',
                    WebkitTextStroke: '3px black', maxWidth: '90%',
                  }}>{frag.subtitle}</span>
                </AbsoluteFill>
              ) : null}
            </TransitionSeries.Sequence>,
          ];
          const tr = transAfter[i];
          if (tr) {
            out.push(
              <TransitionSeries.Transition
                key={`t${i}`}
                presentation={presentation(tr.type)}
                timing={linearTiming({ durationInFrames: Math.round(tr.duration * fps) })}
              />
            );
          }
          return out;
        })}
      </TransitionSeries>
      {music ? <Audio src={staticFile(music)} /> : null}
    </AbsoluteFill>
  );
};
"""

_README = """\
# Proyecto Remotion — clip-generator

Edita y renderiza los clips con [Remotion](https://www.remotion.dev/).

## Contenido
- `timeline.json` — la receta de cada clip (fragmentos, tiempos, transiciones,
  subtítulos y música). **Edita aquí o en el componente.**
- `beats/` — fragmentos ya normalizados a 1080x1920 que referencia el timeline.
- `music.*` — la música del lote (si subiste una).
- `PROMPT_EDICION.md` — tu prompt de edición (úsalo como guía o pásalo a una IA).
- `src/` — composición de ejemplo que lee `timeline.json`.

## Cómo abrir
```bash
cd remotion
npm install
npm run studio          # abre Remotion Studio (previsualiza y edita)
```

## Renderizar un clip
```bash
npx remotion render clip-1 out/clip-1.mp4
```

> Nota: la composición de ejemplo coloca los `beats/` con sus transiciones,
> subtítulos y música. Ajusta `src/Clip.tsx` para tu estilo (animaciones,
> branding, intro/outro) siguiendo `PROMPT_EDICION.md`.
"""

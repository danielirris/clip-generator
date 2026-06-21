"""Modo anuncio: genera un proyecto Remotion por compendio (1 composición/video).

Aplica los lineamientos de edición del usuario de forma determinista:
  - Conserva el audio original del video.
  - Música de fondo a volumen bajo con ducking cuando habla la voz.
  - Subtítulos sincronizados (palabra/línea) con timestamps reales.
  - Texto dentro de safe-area (auto-ajuste), sin cinta amarilla ni barra de progreso.
  - Momento full-screen de intro + CTA final con botón animado a WhatsApp.
El proyecto queda listo para abrir en Remotion Studio y afinar/renderizar.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.config import BASE_DIR
from app.pipeline.transcribe import Word

logger = logging.getLogger(__name__)

_PROMPT_SRC = BASE_DIR / "remotion" / "PROMPT_EDICION.md"
FPS = 30


@dataclass
class AdVideo:
    """Un video de entrada para el modo anuncio."""

    id: int
    path: Path
    name: str
    width: int
    height: int
    duration: float
    words: list[Word] = field(default_factory=list)
    music: Path | None = None


def build_ad_project(
    videos: list[AdVideo],
    output_dir: Path,
    *,
    cta_texto: str,
    whatsapp: str,
    vol: float,
    vol_duck: float,
) -> Path:
    """Escribe el proyecto Remotion del anuncio. Devuelve la carpeta del proyecto."""
    root = output_dir / "remotion-ad"
    public = root / "public"
    audio_dir = public / "audio"
    src = root / "src"
    for d in (public, audio_dir, src):
        d.mkdir(parents=True, exist_ok=True)

    entries = []
    copied_music: dict[str, str] = {}
    for v in videos:
        video_name = f"video_{v.id:03d}{v.path.suffix.lower() or '.mp4'}"
        shutil.copy(v.path, public / video_name)

        music_name = None
        if v.music is not None and v.music.exists():
            key = v.music.name
            if key not in copied_music:
                mn = f"music_{len(copied_music):03d}{v.music.suffix.lower() or '.mp3'}"
                shutil.copy(v.music, audio_dir / mn)
                copied_music[key] = mn
            music_name = f"audio/{copied_music[key]}"

        entries.append({
            "id": v.id,
            "name": v.name,
            "video": video_name,
            "width": v.width,
            "height": v.height,
            "duration": round(v.duration, 3),
            "music": music_name,
            "words": [w.to_dict() for w in v.words],
        })

    ad = {
        "fps": FPS,
        "cta": {"texto": cta_texto, "whatsapp": whatsapp},
        "musica": {"volumen": vol, "ducking": vol_duck},
        "videos": entries,
    }
    (root / "ad.json").write_text(json.dumps(ad, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    # Código + scaffolding.
    (src / "index.ts").write_text(_INDEX_TS, encoding="utf-8")
    (src / "Root.tsx").write_text(_ROOT_TSX, encoding="utf-8")
    (src / "Ad.tsx").write_text(_AD_TSX, encoding="utf-8")
    (src / "Subtitles.tsx").write_text(_SUBTITLES_TSX, encoding="utf-8")
    (src / "Cta.tsx").write_text(_CTA_TSX, encoding="utf-8")
    (src / "Intro.tsx").write_text(_INTRO_TSX, encoding="utf-8")
    (root / "package.json").write_text(_PACKAGE_JSON, encoding="utf-8")
    (root / "tsconfig.json").write_text(_TSCONFIG, encoding="utf-8")
    (root / "remotion.config.ts").write_text(_REMOTION_CONFIG, encoding="utf-8")
    (root / "README.md").write_text(_README, encoding="utf-8")
    if _PROMPT_SRC.exists():
        shutil.copy(_PROMPT_SRC, root / "PROMPT_EDICION.md")

    logger.info("Proyecto Remotion (anuncio) generado: %s (%d videos)",
                root, len(entries))
    return root


# --------------------------------------------------------------------------- #
# Plantillas del proyecto Remotion
# --------------------------------------------------------------------------- #
_INDEX_TS = """\
import { registerRoot } from 'remotion';
import { RemotionRoot } from './Root';
registerRoot(RemotionRoot);
"""

_ROOT_TSX = """\
import React from 'react';
import { Composition } from 'remotion';
import ad from '../ad.json';
import { Ad } from './Ad';

// Una composición por video del compendio. Cada una conserva su audio original,
// sus subtítulos sincronizados, su música con ducking y el CTA final.
export const RemotionRoot: React.FC = () => {
  return (
    <>
      {ad.videos.map((v: any) => (
        <Composition
          key={v.id}
          id={`anuncio-${v.id}`}
          component={Ad as any}
          durationInFrames={Math.max(1, Math.round(v.duration * ad.fps))}
          fps={ad.fps}
          width={v.width}
          height={v.height}
          defaultProps={{ v, cta: ad.cta, musica: ad.musica }}
        />
      ))}
    </>
  );
};
"""

_AD_TSX = """\
import React from 'react';
import {
  AbsoluteFill, Audio, Video, staticFile, useCurrentFrame, useVideoConfig,
} from 'remotion';
import { Subtitles } from './Subtitles';
import { Cta } from './Cta';
import { Intro } from './Intro';

// Anuncio de un video. Mantiene SIEMPRE el audio original (<Video> lo incluye).
export const Ad: React.FC<{ v: any; cta: any; musica: any }> = ({ v, cta, musica }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();

  const introFrames = Math.round(1.4 * fps);            // intro full-screen
  const ctaFrames = Math.round(3 * fps);                // CTA final
  const ctaStart = durationInFrames - ctaFrames;

  // Ducking: la música baja mientras hay una palabra sonando (sincronía real).
  const isSpeaking = (f: number) =>
    v.words.some((w: any) => f / fps >= w.start && f / fps < w.end);

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <Video src={staticFile(v.video)} />

      {v.music ? (
        <Audio
          src={staticFile(v.music)}
          loop
          volume={(f) => (isSpeaking(f) ? musica.ducking : musica.volumen)}
        />
      ) : null}

      {/* Subtítulos sincronizados con los timestamps reales. */}
      <Subtitles words={v.words} />

      {/* Momento full-screen #1: intro breve. */}
      {frame < introFrames ? <Intro words={v.words} /> : null}

      {/* Momento full-screen #2: CTA final con botón a WhatsApp. */}
      {frame >= ctaStart ? (
        <Cta texto={cta.texto} whatsapp={cta.whatsapp} startFrame={ctaStart} />
      ) : null}
    </AbsoluteFill>
  );
};
"""

_SUBTITLES_TSX = """\
import React, { useMemo } from 'react';
import { useCurrentFrame, useVideoConfig, spring } from 'remotion';

// Subtítulos por líneas cortas, resaltando la palabra activa. Dentro de safe-area
// (margen 10%) y con auto-ajuste para que NUNCA se salga del cuadro.
type W = { word: string; start: number; end: number };

function buildLines(words: W[]): W[][] {
  const lines: W[][] = [];
  let cur: W[] = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const prev = words[i - 1];
    const gap = prev ? w.start - prev.end : 0;
    if (cur.length >= 5 || gap > 0.6) {
      if (cur.length) lines.push(cur);
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) lines.push(cur);
  return lines;
}

export const Subtitles: React.FC<{ words: W[] }> = ({ words }) => {
  const { fps, width } = useVideoConfig();
  const frame = useCurrentFrame();
  const t = frame / fps;
  const lines = useMemo(() => buildLines(words || []), [words]);

  const line = lines.find((l) => t >= l[0].start && t <= l[l.length - 1].end);
  if (!line) return null;

  const activeIdx = line.findIndex((w) => t >= w.start && t < w.end);
  // Tamaño de fuente adaptativo según el ancho del cuadro (auto-fit básico).
  const fontSize = Math.round(width * 0.062);

  return (
    <div
      style={{
        position: 'absolute',
        left: '8%', right: '8%', bottom: '14%',          // safe-area
        display: 'flex', flexWrap: 'wrap', gap: '0 0.35em',
        justifyContent: 'center', alignItems: 'center',
        textAlign: 'center',
      }}
    >
      {line.map((w, i) => {
        const active = i === activeIdx;
        const appear = spring({ frame: frame - Math.round(w.start * fps), fps, config: { damping: 200 } });
        return (
          <span
            key={i}
            style={{
              fontFamily: 'Arial, Helvetica, sans-serif',
              fontWeight: 900,
              fontSize,
              lineHeight: 1.15,
              color: active ? '#FFE600' : '#FFFFFF',
              WebkitTextStroke: `${Math.max(2, fontSize * 0.06)}px #000`,
              paintOrder: 'stroke fill',
              textShadow: '0 4px 14px rgba(0,0,0,0.55)',
              transform: `scale(${0.8 + 0.2 * appear})`,
              opacity: appear,
            }}
          >
            {w.word}
          </span>
        );
      })}
    </div>
  );
};
"""

_INTRO_TSX = """\
import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';

// Intro full-screen breve: primeras palabras como gancho. Reemplázala por tu
// branding (logo/hook) siguiendo PROMPT_EDICION.md.
export const Intro: React.FC<{ words: { word: string }[] }> = ({ words }) => {
  const { fps, width } = useVideoConfig();
  const frame = useCurrentFrame();
  const hook = (words || []).slice(0, 4).map((w) => w.word).join(' ') || 'AHORA';
  const o = interpolate(frame, [0, 6, fps * 1.2, fps * 1.4], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill style={{ backgroundColor: 'rgba(0,0,0,0.82)', justifyContent: 'center', alignItems: 'center', opacity: o }}>
      <div style={{
        margin: '0 8%', textAlign: 'center', color: '#fff', fontFamily: 'Arial, sans-serif',
        fontWeight: 900, fontSize: Math.round(width * 0.09), lineHeight: 1.1,
        WebkitTextStroke: '3px #000', paintOrder: 'stroke fill',
      }}>{hook}</div>
    </AbsoluteFill>
  );
};
"""

_CTA_TSX = """\
import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';

// CTA final full-screen. Botón animado a WhatsApp (sin número visible).
export const Cta: React.FC<{ texto: string; whatsapp: string; startFrame: number }> = ({ texto, whatsapp, startFrame }) => {
  const { fps, width } = useVideoConfig();
  const frame = useCurrentFrame();
  const f = frame - startFrame;
  const enter = spring({ frame: f, fps, config: { damping: 200 } });
  const pulse = 1 + 0.04 * Math.sin((f / fps) * 6);
  const bg = interpolate(enter, [0, 1], [0, 0.85]);

  return (
    <AbsoluteFill style={{ backgroundColor: `rgba(0,0,0,${bg})`, justifyContent: 'center', alignItems: 'center' }}>
      <div style={{ margin: '0 8%', textAlign: 'center', transform: `translateY(${(1 - enter) * 60}px)`, opacity: enter }}>
        <div style={{
          color: '#fff', fontFamily: 'Arial, sans-serif', fontWeight: 900,
          fontSize: Math.round(width * 0.075), lineHeight: 1.15,
          WebkitTextStroke: '3px #000', paintOrder: 'stroke fill', marginBottom: 40,
        }}>{texto}</div>
        <a href={whatsapp} style={{ textDecoration: 'none' }}>
          <div style={{
            display: 'inline-block', background: '#25D366', color: '#0b3d2e',
            fontFamily: 'Arial, sans-serif', fontWeight: 900,
            fontSize: Math.round(width * 0.05), padding: '24px 48px', borderRadius: 999,
            transform: `scale(${pulse})`, boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
          }}>WhatsApp →</div>
        </a>
      </div>
    </AbsoluteFill>
  );
};
"""

_PACKAGE_JSON = """\
{
  "name": "anuncio-remotion",
  "version": "1.0.0",
  "scripts": {
    "studio": "remotion studio",
    "render": "remotion render"
  },
  "dependencies": {
    "@remotion/cli": "^4.0.0",
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

_TSCONFIG = """\
{
  "compilerOptions": {
    "target": "ES2018",
    "module": "ESNext",
    "jsx": "react-jsx",
    "esModuleInterop": true,
    "moduleResolution": "node",
    "resolveJsonModule": true,
    "strict": false,
    "skipLibCheck": true
  }
}
"""

_REMOTION_CONFIG = """\
import { Config } from '@remotion/cli/config';
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
"""

_README = """\
# Anuncio (Remotion) — generado por clip-generator

Proyecto listo para editar/renderizar tus anuncios siguiendo `PROMPT_EDICION.md`.
Cada video del compendio es una composición `anuncio-<id>`.

## Qué incluye (ya cableado)
- **Audio original conservado** + música de fondo con **ducking** (baja cuando hay voz).
- **Subtítulos sincronizados** con los timestamps reales (resaltan la palabra activa).
- **Safe-area** (margen 8-10%) y auto-ajuste de tamaño para que el texto no se salga.
- **Intro full-screen** + **CTA final** con botón animado a WhatsApp (sin número).
- Datos en `ad.json` (incluye las palabras con tiempos de cada video).

## Cómo abrir
```bash
cd remotion-ad
npm install
npm run studio          # previsualiza y edita en Remotion Studio
```

## Renderizar un anuncio
```bash
npx remotion render anuncio-0 out/anuncio-0.mp4
```

## Para afinar (siguiendo PROMPT_EDICION.md)
- Cambia el link de WhatsApp y el texto del CTA en `ad.json` (`cta`).
- Sustituye `src/Intro.tsx` por tu branding (logo/hook).
- Añade tus **SFX** (whoosh/pop/ding) en `public/audio` y dispáralos en las
  transiciones desde `src/Ad.tsx`.
- Las animaciones por palabra clave y el momento full-screen "fuerte" son el
  punto donde tú (o una IA con el prompt) ponéis el toque creativo.
"""

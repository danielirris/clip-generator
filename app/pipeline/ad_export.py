"""Modo anuncio: genera un proyecto Remotion por compendio (1 composición/video).

Aplica los lineamientos de edición del usuario de forma determinista:
  - Conserva el audio original del video (la locución que trae).
  - Música de fondo a volumen bajo con ducking cuando habla la voz.
  - Subtítulos sincronizados palabra por palabra con timestamps reales.
  - Texto dentro de safe-area (auto-ajuste), sin cinta amarilla ni barra de progreso.
  - VARIAS animaciones a pantalla completa: intro (gancho) + un momento clave a
    media reproducción + CTA final con botón animado a WhatsApp.
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
    voz: Path | None = None   # audio/locución a ponerle al video (modo Apartado 2)


# --------------------------------------------------------------------------- #
# Cálculo de líneas de subtítulo y del momento full-screen
# --------------------------------------------------------------------------- #
def _lines_from_words(words: list[Word]) -> list[list[Word]]:
    """Agrupa palabras en líneas cortas (por pausas o máx. 5 palabras)."""
    lines: list[list[Word]] = []
    cur: list[Word] = []
    for i, w in enumerate(words):
        gap = w.start - words[i - 1].end if i > 0 else 0.0
        if cur and (len(cur) >= 5 or gap > 0.6):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _pick_highlight(words: list[Word], duration: float,
                    intro_s: float = 1.6, cta_s: float = 3.0) -> dict | None:
    """Elige una frase clave cerca de la mitad para la animación full-screen."""
    lines = _lines_from_words(words)
    if not lines:
        return None
    mid = duration / 2
    cands = [l for l in lines
             if l[0].start >= intro_s and l[-1].end <= max(intro_s, duration - cta_s)]
    pool = cands or lines
    best = min(pool, key=lambda l: abs(((l[0].start + l[-1].end) / 2) - mid))
    return {"text": " ".join(w.word for w in best), "start": round(best[0].start, 3)}


def build_ad_project(
    videos: list[AdVideo],
    output_dir: Path,
    *,
    cta_texto: str,
    whatsapp: str,
    vol: float,
    vol_duck: float,
    sfx: dict[str, Path] | None = None,
) -> Path:
    """Escribe el proyecto Remotion del anuncio. Devuelve la carpeta del proyecto."""
    root = output_dir / "remotion-ad"
    public = root / "public"
    audio_dir = public / "audio"
    sfx_out = audio_dir / "sfx"
    src = root / "src"
    for d in (public, audio_dir, sfx_out, src):
        d.mkdir(parents=True, exist_ok=True)

    # Copiar los SFX (whoosh/pop/ding) al proyecto.
    sfx_names: dict[str, str] = {}
    for name, p in (sfx or {}).items():
        if p and p.exists():
            shutil.copy(p, sfx_out / p.name)
            sfx_names[name] = f"audio/sfx/{p.name}"

    entries = []
    copied_music: dict[str, str] = {}
    for v in videos:
        video_name = f"video_{v.id:03d}{v.path.suffix.lower() or '.mp4'}"
        shutil.copy(v.path, public / video_name)

        voz_name = None
        if v.voz is not None and v.voz.exists():
            voz_name = f"voz_{v.id:03d}{v.voz.suffix.lower() or '.mp3'}"
            shutil.copy(v.voz, public / voz_name)

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
            "voz": voz_name,
            "words": [w.to_dict() for w in v.words],
            "highlight": _pick_highlight(v.words, v.duration),
            "lineStarts": [round(l[0].start, 3) for l in _lines_from_words(v.words)],
        })

    ad = {
        "fps": FPS,
        "cta": {"texto": cta_texto, "whatsapp": whatsapp},
        "musica": {"volumen": vol, "ducking": vol_duck},
        "sfx": sfx_names,
        "videos": entries,
    }
    (root / "ad.json").write_text(json.dumps(ad, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    (src / "index.ts").write_text(_INDEX_TS, encoding="utf-8")
    (src / "Root.tsx").write_text(_ROOT_TSX, encoding="utf-8")
    (src / "Ad.tsx").write_text(_AD_TSX, encoding="utf-8")
    (src / "Subtitles.tsx").write_text(_SUBTITLES_TSX, encoding="utf-8")
    (src / "Cta.tsx").write_text(_CTA_TSX, encoding="utf-8")
    (src / "Intro.tsx").write_text(_INTRO_TSX, encoding="utf-8")
    (src / "Highlight.tsx").write_text(_HIGHLIGHT_TSX, encoding="utf-8")
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

// Una composición por video. Cada una conserva su audio, subtítulos sincronizados,
// música con ducking, momentos full-screen y CTA final.
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
          defaultProps={{ v, cta: ad.cta, musica: ad.musica, sfx: ad.sfx }}
        />
      ))}
    </>
  );
};
"""

_AD_TSX = """\
import React from 'react';
import {
  AbsoluteFill, Audio, Sequence, Video, staticFile, useCurrentFrame, useVideoConfig,
} from 'remotion';
import { Subtitles } from './Subtitles';
import { Cta } from './Cta';
import { Intro } from './Intro';
import { Highlight } from './Highlight';

// Anuncio de un video. Mantiene SIEMPRE el audio original (<Video> lo incluye).
export const Ad: React.FC<{ v: any; cta: any; musica: any; sfx: any }> = ({ v, cta, musica, sfx }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();

  const introFrames = Math.round(1.6 * fps);
  const ctaFrames = Math.round(3 * fps);
  const ctaStart = durationInFrames - ctaFrames;

  // Momento full-screen a media reproducción (rompe el ritmo).
  const hl = v.highlight;
  const hlDur = Math.round(1.3 * fps);
  const hlStart = hl ? Math.round(hl.start * fps) : -1;
  const hlOn = hl && frame >= hlStart && frame < hlStart + hlDur;

  // Ducking: la música baja mientras hay una palabra sonando (sincronía real).
  const isSpeaking = (f: number) =>
    v.words.some((w: any) => f / fps >= w.start && f / fps < w.end);

  const hasVoz = !!v.voz;

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      {/* Si hay locución subida, el video se silencia y se repite para cubrir
          toda la narración; si no, el video conserva su propio audio. */}
      <Video src={staticFile(v.video)} muted={hasVoz} loop={hasVoz} />
      {hasVoz ? <Audio src={staticFile(v.voz)} /> : null}

      {v.music ? (
        <Audio
          src={staticFile(v.music)}
          loop
          volume={(f) => (isSpeaking(f) ? musica.ducking : musica.volumen)}
        />
      ) : null}

      {/* SFX (con moderación): whoosh en los momentos full-screen, pop en la
          aparición de cada línea de subtítulo, ding en el CTA. */}
      {sfx && sfx.whoosh ? (
        <>
          <Sequence from={0} durationInFrames={Math.round(0.6 * fps)}>
            <Audio src={staticFile(sfx.whoosh)} volume={0.5} />
          </Sequence>
          {hl ? (
            <Sequence from={hlStart} durationInFrames={Math.round(0.6 * fps)}>
              <Audio src={staticFile(sfx.whoosh)} volume={0.5} />
            </Sequence>
          ) : null}
          <Sequence from={ctaStart} durationInFrames={Math.round(0.6 * fps)}>
            <Audio src={staticFile(sfx.whoosh)} volume={0.55} />
          </Sequence>
        </>
      ) : null}
      {sfx && sfx.pop ? (v.lineStarts || []).map((s: number, i: number) => (
        <Sequence key={`pop${i}`} from={Math.round(s * fps)} durationInFrames={Math.round(0.18 * fps)}>
          <Audio src={staticFile(sfx.pop)} volume={0.3} />
        </Sequence>
      )) : null}
      {sfx && sfx.ding ? (
        <Sequence from={ctaStart + Math.round(0.18 * fps)} durationInFrames={Math.round(0.7 * fps)}>
          <Audio src={staticFile(sfx.ding)} volume={0.5} />
        </Sequence>
      ) : null}

      {/* Subtítulos sincronizados (se ocultan durante los momentos full-screen). */}
      {!hlOn && frame >= introFrames && frame < ctaStart ? (
        <Subtitles words={v.words} />
      ) : null}

      {/* Full-screen #1: intro con el gancho. */}
      {frame < introFrames ? <Intro words={v.words} /> : null}

      {/* Full-screen #2: frase clave a media reproducción. */}
      {hlOn ? <Highlight text={hl.text} startFrame={hlStart} /> : null}

      {/* Full-screen #3: CTA final con botón a WhatsApp. */}
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
// (margen ~8%) y con auto-ajuste para que NUNCA se salga del cuadro.
type W = { word: string; start: number; end: number };

function buildLines(words: W[]): W[][] {
  const lines: W[][] = [];
  let cur: W[] = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const prev = words[i - 1];
    const gap = prev ? w.start - prev.end : 0;
    if (cur.length && (cur.length >= 5 || gap > 0.6)) {
      lines.push(cur);
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
  const fontSize = Math.round(width * 0.07);

  return (
    <div
      style={{
        position: 'absolute',
        left: '8%', right: '8%', bottom: '15%',          // safe-area
        display: 'flex', flexWrap: 'wrap', gap: '0.08em 0.32em',
        justifyContent: 'center', alignItems: 'center', textAlign: 'center',
      }}
    >
      {line.map((w, i) => {
        const active = i === activeIdx;
        const pop = spring({
          frame: frame - Math.round(w.start * fps), fps,
          config: { damping: 14, mass: 0.5 },
        });
        return (
          <span
            key={i}
            style={{
              fontFamily: 'Arial, Helvetica, sans-serif',
              fontWeight: 900,
              fontSize,
              lineHeight: 1.1,
              color: active ? '#FFD400' : '#FFFFFF',
              WebkitTextStroke: `${Math.max(2, fontSize * 0.06)}px #000`,
              paintOrder: 'stroke fill',
              textShadow: '0 6px 18px rgba(0,0,0,0.6)',
              transform: `translateY(${(1 - Math.min(1, pop)) * 14}px) scale(${0.86 + 0.14 * Math.min(1, pop)})`,
              opacity: Math.min(1, pop),
              display: 'inline-block',
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
import React, { useMemo } from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';

// Intro full-screen: primera frase como gancho, con entrada animada.
// Reemplázala por tu branding (logo/hook) siguiendo PROMPT_EDICION.md.
type W = { word: string; start: number; end: number };

export const Intro: React.FC<{ words: W[] }> = ({ words }) => {
  const { fps, width } = useVideoConfig();
  const frame = useCurrentFrame();

  const hook = useMemo(() => {
    const w = words || [];
    if (!w.length) return 'AHORA';
    // primeras ~5 palabras o hasta la primera pausa
    const out: string[] = [];
    for (let i = 0; i < w.length && out.length < 5; i++) {
      out.push(w[i].word);
      if (i + 1 < w.length && w[i + 1].start - w[i].end > 0.6) break;
    }
    return out.join(' ');
  }, [words]);

  const enter = spring({ frame, fps, config: { damping: 18, mass: 0.6 } });
  const o = interpolate(frame, [0, 6, fps * 1.3, fps * 1.6], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ backgroundColor: `rgba(8,8,12,${0.86 * o})`, justifyContent: 'center', alignItems: 'center' }}>
      <div style={{
        margin: '0 8%', textAlign: 'center', opacity: o,
        transform: `translateY(${(1 - enter) * 40}px) scale(${0.9 + 0.1 * enter})`,
        color: '#fff', fontFamily: 'Arial, sans-serif', fontWeight: 900,
        fontSize: Math.round(width * 0.092), lineHeight: 1.08,
        WebkitTextStroke: '3px #000', paintOrder: 'stroke fill',
      }}>{hook}</div>
    </AbsoluteFill>
  );
};
"""

_HIGHLIGHT_TSX = """\
import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';

// Momento full-screen a media reproducción: una frase clave grande que rompe el
// ritmo y capta atención. Entra y sale en ~1.3s.
export const Highlight: React.FC<{ text: string; startFrame: number }> = ({ text, startFrame }) => {
  const { fps, width } = useVideoConfig();
  const f = useCurrentFrame() - startFrame;
  const total = Math.round(1.3 * fps);
  const enter = spring({ frame: f, fps, config: { damping: 16, mass: 0.6 } });
  const out = interpolate(f, [total - 7, total], [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const o = Math.min(enter, out);

  return (
    <AbsoluteFill style={{ backgroundColor: `rgba(10,10,14,${0.93 * o})`, justifyContent: 'center', alignItems: 'center' }}>
      <div style={{
        margin: '0 8%', textAlign: 'center', opacity: o,
        transform: `scale(${0.82 + 0.18 * enter})`,
        color: '#fff', fontFamily: 'Arial, sans-serif', fontWeight: 900,
        fontSize: Math.round(width * 0.088), lineHeight: 1.1,
        WebkitTextStroke: '3px #000', paintOrder: 'stroke fill',
      }}>{text}</div>
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
  const bg = interpolate(enter, [0, 1], [0, 0.88]);

  return (
    <AbsoluteFill style={{ backgroundColor: `rgba(0,0,0,${bg})`, justifyContent: 'center', alignItems: 'center' }}>
      <div style={{ margin: '0 8%', textAlign: 'center', transform: `translateY(${(1 - enter) * 60}px)`, opacity: enter }}>
        <div style={{
          color: '#fff', fontFamily: 'Arial, sans-serif', fontWeight: 900,
          fontSize: Math.round(width * 0.078), lineHeight: 1.15,
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
Cada video es una composición `anuncio-<id>`.

## Qué incluye (ya cableado)
- **Audio original conservado** + música de fondo con **ducking**.
- **Subtítulos sincronizados** palabra por palabra (resaltan la palabra activa).
- **Safe-area** (margen ~8%) y auto-ajuste de tamaño.
- **3 momentos full-screen**: intro (gancho), una frase clave a media reproducción,
  y el CTA final con botón animado a WhatsApp (sin número).
- Datos en `ad.json` (palabras con tiempos + la frase clave de cada video).

## Cómo abrir
```bash
cd remotion-ad
npm install
npm run studio          # previsualiza y edita en Remotion Studio
```

## Renderizar
```bash
npx remotion render anuncio-0 out/anuncio-0.mp4
```

## Para afinar (siguiendo PROMPT_EDICION.md)
- Link de WhatsApp y texto del CTA: en `ad.json` (`cta`).
- Tu branding/logo en la intro: `src/Intro.tsx`.
- SFX (whoosh/pop/ding) en `public/audio`, dispáralos desde `src/Ad.tsx`.
- La frase clave full-screen se elige automática (cercana a la mitad); cámbiala
  en `ad.json` (`videos[i].highlight`) o en `src/Ad.tsx`.
"""

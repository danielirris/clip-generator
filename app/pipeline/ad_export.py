"""Modo anuncio: genera un proyecto Remotion por compendio (1 composición/video).

La IA (analyze.plan_ad) entrega un PLAN por video: estilo de subtítulos, color de
acento, palabras a resaltar, y — EN FUNCIÓN DE LA VOZ — tarjetas full-screen,
píldoras/badges y emojis con sus timestamps. Esta composición RENDERIZA ese plan:
audio original conservado, música con ducking, SFX, micro-movimiento y CTA.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.transcribe import Word

logger = logging.getLogger(__name__)

FPS = 30

_DEFAULT_PLAN = {
    "accent": "#FFD400", "secondary": "#00E0FF",
    "palette": ["#FF5C5C", "#FFB020", "#2ECC71", "#00C2FF", "#7C5CFF"],
    "subtitle_style": "pop", "intensidad": 70,
    "emphasis": [], "fullscreen": [], "pills": [], "emojis": [], "overlays": [],
}


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
    voz: Path | None = None
    plan: dict | None = None   # plan de edición de la IA


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

        plan = {**_DEFAULT_PLAN, **(v.plan or {})}
        entries.append({
            "id": v.id, "name": v.name, "video": video_name,
            "width": v.width, "height": v.height, "duration": round(v.duration, 3),
            "music": music_name, "voz": voz_name,
            "words": [w.to_dict() for w in v.words],
            "lineStarts": [round(l[0].start, 3) for l in _lines_from_words(v.words)],
            "plan": plan,
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
    (src / "font.ts").write_text(_FONT_TS, encoding="utf-8")
    (src / "Root.tsx").write_text(_ROOT_TSX, encoding="utf-8")
    (src / "Ad.tsx").write_text(_AD_TSX, encoding="utf-8")
    (src / "Subtitles.tsx").write_text(_SUBTITLES_TSX, encoding="utf-8")
    (src / "Card.tsx").write_text(_CARD_TSX, encoding="utf-8")
    (src / "Pill.tsx").write_text(_PILL_TSX, encoding="utf-8")
    (src / "EmojiPop.tsx").write_text(_EMOJIPOP_TSX, encoding="utf-8")
    (src / "Cta.tsx").write_text(_CTA_TSX, encoding="utf-8")
    (root / "package.json").write_text(_PACKAGE_JSON, encoding="utf-8")
    (root / "tsconfig.json").write_text(_TSCONFIG, encoding="utf-8")
    (root / "remotion.config.ts").write_text(_REMOTION_CONFIG, encoding="utf-8")
    (root / "README.md").write_text(_README, encoding="utf-8")
    from app import library
    (root / "PROMPT_EDICION.md").write_text(library.read_prompt(), encoding="utf-8")

    logger.info("Proyecto Remotion (anuncio) generado: %s (%d videos)", root, len(entries))
    return root


# --------------------------------------------------------------------------- #
# Plantillas Remotion
# --------------------------------------------------------------------------- #
_INDEX_TS = """\
import { registerRoot } from 'remotion';
import { fontFamily } from './font';
import { RemotionRoot } from './Root';
registerRoot(RemotionRoot);
"""

# Fuente bonita y de impacto (se hornea en el render, sin internet).
_FONT_TS = """\
import { loadFont } from '@remotion/google-fonts/Anton';
export const { fontFamily } = loadFont();
"""

_ROOT_TSX = """\
import React from 'react';
import { Composition } from 'remotion';
import { fontFamily } from './font';
import ad from '../ad.json';
import { Ad } from './Ad';

export const RemotionRoot: React.FC = () => (
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
"""

_AD_TSX = """\
import React from 'react';
import {
  AbsoluteFill, Audio, Img, Sequence, Video, interpolate, staticFile,
  useCurrentFrame, useVideoConfig,
} from 'remotion';
import { fontFamily } from './font';
import { Subtitles } from './Subtitles';
import { Card } from './Card';
import { Pill } from './Pill';
import { EmojiPop } from './EmojiPop';
import { Cta } from './Cta';

const CARD_S = 2.0;

export const Ad: React.FC<{ v: any; cta: any; musica: any; sfx: any }> = ({ v, cta, musica, sfx }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const plan = v.plan || {};
  const accent = plan.accent || '#FFD400';
  const palette = (plan.palette && plan.palette.length) ? plan.palette : [accent];
  const pick = (i: number) => palette[((i % palette.length) + palette.length) % palette.length];

  const ctaFrames = Math.round(3 * fps);
  const ctaStart = durationInFrames - ctaFrames;

  const cards = (plan.fullscreen || []).map((c: any) => ({ ...c, f: Math.round(c.at * fps) }));
  const onCard = cards.some((c: any) => frame >= c.f && frame < c.f + CARD_S * fps);

  const isSpeaking = (f: number) => v.words.some((w: any) => f / fps >= w.start && f / fps < w.end);

  // Ken Burns suave: el video nunca queda 100% quieto.
  const kb = interpolate(frame, [0, durationInFrames], [1.03, 1.1], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ backgroundColor: 'black', overflow: 'hidden' }}>
      <AbsoluteFill style={{ transform: `scale(${kb})` }}>
        <Video src={staticFile(v.video)} muted={!!v.voz} loop={!!v.voz}
               style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      </AbsoluteFill>
      {v.voz ? <Audio src={staticFile(v.voz)} /> : null}

      {v.music ? (
        <Audio src={staticFile(v.music)} loop
               volume={(f) => (isSpeaking(f) ? musica.ducking : musica.volumen)} />
      ) : null}

      {/* SFX */}
      {sfx && sfx.whoosh ? cards.map((c: any, i: number) => (
        <Sequence key={`wh${i}`} from={c.f} durationInFrames={Math.round(0.6 * fps)}>
          <Audio src={staticFile(sfx.whoosh)} volume={0.5} />
        </Sequence>
      )) : null}
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

      {/* Subtítulos (ocultos durante tarjetas full-screen y CTA). */}
      {!onCard && frame < ctaStart ? <Subtitles words={v.words} plan={plan} /> : null}

      {/* Píldoras / badges sobre el video. */}
      {(plan.pills || []).map((p: any, i: number) => {
        const from = Math.round(p.start * fps);
        const dur = Math.max(1, Math.round((p.end - p.start) * fps));
        return (
          <Sequence key={`pill${i}`} from={from} durationInFrames={dur}>
            <Pill text={p.text} emoji={p.emoji} accent={pick(i + 1)} />
          </Sequence>
        );
      })}

      {/* Emojis contextuales. */}
      {(plan.emojis || []).map((e: any, i: number) => (
        <Sequence key={`em${i}`} from={Math.round(e.at * fps)} durationInFrames={Math.round(1.0 * fps)}>
          <EmojiPop emoji={e.emoji} idx={i} />
        </Sequence>
      ))}

      {/* Overlays subidos por el usuario (imagen/video encima). */}
      {(plan.overlays || []).map((o: any, i: number) => {
        const isVid = /\\.(mp4|mov|webm|m4v)$/i.test(o.file || '');
        return (
          <Sequence key={`ov${i}`} from={Math.round((o.at || 0) * fps)} durationInFrames={Math.max(1, Math.round((o.dur || 3) * fps))}>
            <div style={{ position: 'absolute', left: `${o.x ?? 30}%`, top: `${o.y ?? 12}%`, width: `${o.w ?? 40}%` }}>
              {isVid ? <Video src={staticFile(o.file)} style={{ width: '100%', borderRadius: 8 }} />
                : <Img src={staticFile(o.file)} style={{ width: '100%' }} />}
            </div>
          </Sequence>
        );
      })}

      {/* Tarjetas full-screen (donde la IA dijo, según la voz). */}
      {cards.map((c: any, i: number) => (
        <Sequence key={`card${i}`} from={c.f} durationInFrames={Math.round(CARD_S * fps)}>
          <Card top={c.top} keyText={c.key} sub={c.sub} emoji={c.emoji} accent={pick(i)} />
        </Sequence>
      ))}

      {/* CTA final. */}
      {frame >= ctaStart ? (
        <Cta texto={cta.texto} whatsapp={cta.whatsapp} startFrame={ctaStart} accent={accent} />
      ) : null}
    </AbsoluteFill>
  );
};
"""

_SUBTITLES_TSX = """\
import React, { useMemo } from 'react';
import { useCurrentFrame, useVideoConfig, spring } from 'remotion';
import { fontFamily } from './font';

type W = { word: string; start: number; end: number };
const clean = (s: string) => s.toLowerCase().replace(/[^\\p{L}\\p{N}]/gu, '');

function buildLines(words: W[]): W[][] {
  const lines: W[][] = []; let cur: W[] = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i]; const prev = words[i - 1];
    const gap = prev ? w.start - prev.end : 0;
    if (cur.length && (cur.length >= 5 || gap > 0.6)) { lines.push(cur); cur = []; }
    cur.push(w);
  }
  if (cur.length) lines.push(cur);
  return lines;
}

export const Subtitles: React.FC<{ words: W[]; plan?: any }> = ({ words, plan }) => {
  const { fps, width } = useVideoConfig();
  const frame = useCurrentFrame();
  const t = frame / fps;
  const lines = useMemo(() => buildLines(words || []), [words]);
  const accent = plan?.accent || '#FFD400';
  const style = plan?.subtitle_style || 'pop';
  const intensidad = (plan?.intensidad ?? 70) / 100;
  const emphasis = useMemo(() => new Set((plan?.emphasis || []).map((w: string) => clean(w))), [plan]);

  const line = lines.find((l) => t >= l[0].start && t <= l[l.length - 1].end);
  if (!line) return null;
  const activeIdx = line.findIndex((w) => t >= w.start && t < w.end);
  const fontSize = Math.round(width * (0.07 + 0.012 * intensidad));

  return (
    <div style={{
      position: 'absolute', left: '8%', right: '8%', bottom: '15%',
      display: 'flex', flexWrap: 'wrap', gap: '0.28em 0.75em',
      justifyContent: 'center', alignItems: 'center', textAlign: 'center',
    }}>
      {line.map((w, i) => {
        const active = i === activeIdx;
        const isKey = emphasis.has(clean(w.word));
        const pop = Math.min(1, spring({ frame: frame - Math.round(w.start * fps), fps, config: { damping: 13, mass: 0.5 } }));
        // Estilo por video.
        const box = (style === 'box' || style === 'pop') && isKey;
        const punch = style === 'punch' && active;
        let color = '#FFFFFF';
        if (box) color = '#0b0b0b';
        else if (active && (style === 'karaoke' || style === 'pop' || style === 'punch')) color = accent;
        else if (isKey && (style === 'color' || style === 'karaoke')) color = accent;
        const baseScale = (isKey ? 1.06 : 1) * (active ? 1.05 : 1) * (punch ? 1.22 : 1);
        const scale = baseScale * (0.84 + 0.16 * pop);
        return (
          <span key={i} style={{
            fontFamily, fontWeight: 900, fontSize,
            textTransform: 'uppercase', lineHeight: 1.18, color,
            background: box ? accent : 'transparent',
            padding: box ? '0.02em 0.22em' : 0, borderRadius: box ? '0.18em' : 0,
            WebkitTextStroke: box ? '0' : `${Math.max(2, fontSize * 0.06)}px #000`,
            paintOrder: 'stroke fill',
            textShadow: box ? '0 6px 16px rgba(0,0,0,0.45)' : '0 6px 18px rgba(0,0,0,0.6)',
            transform: `translateY(${(1 - pop) * 16}px) scale(${scale})`,
            opacity: pop, display: 'inline-block',
          }}>{w.word}</span>
        );
      })}
    </div>
  );
};
"""

_CARD_TSX = """\
import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { fontFamily } from './font';

// Tarjeta de marca full-screen, CENTRADA, con emoji y animaciones escalonadas. ~2s.
function darken(hex: string, k: number) {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 255) * k), g = Math.round(((n >> 8) & 255) * k), b = Math.round((n & 255) * k);
  return `rgb(${r},${g},${b})`;
}

export const Card: React.FC<{ top?: string; keyText: string; sub?: string; emoji?: string; accent: string }> = ({ top, keyText, sub, emoji, accent }) => {
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const enter = spring({ frame: f, fps, config: { damping: 16, mass: 0.6 } });
  const out = interpolate(f, [durationInFrames - 7, durationInFrames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const o = Math.min(enter, out);
  // Entradas escalonadas: emoji -> top -> key (punch) -> sub.
  const emo = spring({ frame: f - 2, fps, config: { damping: 9, mass: 0.5 } });
  const topIn = spring({ frame: f - 6, fps, config: { damping: 18 } });
  const keyPop = spring({ frame: f - 9, fps, config: { damping: 11, mass: 0.5 } });
  const subIn = spring({ frame: f - 14, fps, config: { damping: 18 } });
  const bgScale = interpolate(enter, [0, 1], [1.15, 1]);     // fondo entra con zoom
  const pulse = 1 + 0.02 * Math.sin(f / fps * 5);             // micro-movimiento del key
  const float = Math.sin(f / fps * 3) * 6;
  const dark = darken(accent, 0.45);

  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: o, overflow: 'hidden' }}>
      <AbsoluteFill style={{
        transform: `scale(${bgScale})`,
        background: `radial-gradient(70% 55% at 50% 42%, ${accent}, ${dark})`,
      }} />
      <div style={{ margin: '0 7%', textAlign: 'center', transform: `translateY(${float}px)` }}>
        {emoji ? <div style={{ fontSize: Math.round(width * 0.18), lineHeight: 1,
          transform: `translateY(${(1 - emo) * 40}px) scale(${0.3 + 0.7 * Math.min(1, emo)})`,
          filter: 'drop-shadow(0 10px 18px rgba(0,0,0,0.45))', marginBottom: 8 }}>{emoji}</div> : null}
        {top ? <div style={{ color: '#ffffffe6', fontFamily, fontWeight: 800, letterSpacing: 2,
          fontSize: Math.round(width * 0.045), textTransform: 'uppercase', opacity: topIn,
          transform: `translateY(${(1 - topIn) * 20}px)` }}>{top}</div> : null}
        <div style={{ color: '#fff', fontFamily, fontWeight: 900, lineHeight: 1.02,
          fontSize: Math.round(width * 0.135), textTransform: 'uppercase',
          WebkitTextStroke: '2px rgba(0,0,0,0.3)', paintOrder: 'stroke fill',
          textShadow: '0 10px 30px rgba(0,0,0,0.35)',
          transform: `scale(${(0.6 + 0.4 * Math.min(1, keyPop)) * pulse})` }}>{keyText}</div>
        {sub ? <div style={{ color: '#ffffffe6', fontFamily, fontWeight: 700, marginTop: 14,
          fontSize: Math.round(width * 0.046), opacity: subIn, transform: `translateY(${(1 - subIn) * 16}px)` }}>{sub}</div> : null}
      </div>
    </AbsoluteFill>
  );
};
"""

_PILL_TSX = """\
import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { fontFamily } from './font';

// Píldora/badge lower-third: fondo blanco, borde de acento, emoji + texto. Con float.
export const Pill: React.FC<{ text: string; emoji?: string; accent: string }> = ({ text, emoji, accent }) => {
  const { fps, width, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const enter = spring({ frame: f, fps, config: { damping: 14, mass: 0.5 } });
  const out = interpolate(f, [durationInFrames - 6, durationInFrames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const o = Math.min(1, enter) * out;
  const float = Math.sin(f / fps * 3) * 6;          // micro-movimiento
  const fontSize = Math.round(width * 0.05);

  return (
    <div style={{
      position: 'absolute', left: 0, right: 0, bottom: '30%', display: 'flex', justifyContent: 'center',
      opacity: o, transform: `translateY(${float + (1 - enter) * 30}px)`,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 16, maxWidth: '84%',
        background: '#fff', border: `4px solid ${accent}`, borderRadius: 999,
        padding: '14px 26px 14px 14px', boxShadow: '0 12px 30px rgba(0,0,0,0.35)',
      }}>
        {emoji ? <div style={{
          width: fontSize * 1.6, height: fontSize * 1.6, borderRadius: '50%', background: `${accent}22`,
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize, flexShrink: 0,
        }}>{emoji}</div> : null}
        <div style={{ color: accent, fontFamily, fontWeight: 900, fontSize,
          textTransform: 'uppercase', lineHeight: 1.05, filter: 'brightness(0.7)' }}>{text}</div>
      </div>
    </div>
  );
};
"""

_EMOJIPOP_TSX = """\
import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { fontFamily } from './font';

// Emoji contextual con pop + float, en posiciones alternadas (no tapa el centro).
export const EmojiPop: React.FC<{ emoji: string; idx: number }> = ({ emoji, idx }) => {
  const { fps, width, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const enter = spring({ frame: f, fps, config: { damping: 10, mass: 0.5 } });
  const out = interpolate(f, [durationInFrames - 6, durationInFrames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const o = Math.min(1, enter) * out;
  const float = Math.sin(f / fps * 4) * 8;
  const left = idx % 2 === 0 ? '16%' : '70%';
  const top = idx % 3 === 0 ? '24%' : '32%';
  return (
    <div style={{
      position: 'absolute', left, top, fontSize: Math.round(width * 0.13),
      opacity: o, transform: `translateY(${float}px) scale(${0.4 + 0.6 * Math.min(1, enter)})`,
      filter: 'drop-shadow(0 8px 14px rgba(0,0,0,0.4))',
    }}>{emoji}</div>
  );
};
"""

_CTA_TSX = """\
import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { fontFamily } from './font';

export const Cta: React.FC<{ texto: string; whatsapp: string; startFrame: number; accent?: string }> = ({ texto, whatsapp, startFrame, accent }) => {
  const { fps, width } = useVideoConfig();
  const f = useCurrentFrame() - startFrame;
  const enter = spring({ frame: f, fps, config: { damping: 200 } });
  const pulse = 1 + 0.04 * Math.sin((f / fps) * 6);
  const bg = interpolate(enter, [0, 1], [0, 0.88]);

  return (
    <AbsoluteFill style={{ backgroundColor: `rgba(0,0,0,${bg})`, justifyContent: 'center', alignItems: 'center' }}>
      <div style={{ margin: '0 8%', textAlign: 'center', transform: `translateY(${(1 - enter) * 60}px)`, opacity: enter }}>
        <div style={{ color: '#fff', fontFamily, fontWeight: 900, fontSize: Math.round(width * 0.078),
          lineHeight: 1.15, WebkitTextStroke: '3px #000', paintOrder: 'stroke fill', marginBottom: 40 }}>{texto}</div>
        <a href={whatsapp} style={{ textDecoration: 'none' }}>
          <div style={{ display: 'inline-block', background: '#25D366', color: '#0b3d2e', fontFamily,
            fontWeight: 900, fontSize: Math.round(width * 0.05), padding: '24px 48px', borderRadius: 999,
            transform: `scale(${pulse})`, boxShadow: '0 10px 30px rgba(0,0,0,0.4)' }}>WhatsApp →</div>
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
  "scripts": { "studio": "remotion studio", "render": "remotion render" },
  "dependencies": {
    "@remotion/cli": "^4.0.0", "@remotion/google-fonts": "^4.0.0",
    "react": "^18.0.0", "react-dom": "^18.0.0", "remotion": "^4.0.0"
  },
  "devDependencies": { "@types/react": "^18.0.0", "typescript": "^5.0.0" }
}
"""

_TSCONFIG = """\
{
  "compilerOptions": {
    "target": "ES2018", "module": "ESNext", "jsx": "react-jsx", "esModuleInterop": true,
    "moduleResolution": "node", "resolveJsonModule": true, "strict": false, "skipLibCheck": true
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

Cada video es la composición `anuncio-<id>`. La IA decidió, en función de la voz,
las tarjetas full-screen, las píldoras, los emojis, el estilo de subtítulos y el
color de acento (todo en `ad.json` → `videos[i].plan`).

## Abrir / renderizar
```bash
cd remotion-ad && npm install
npm run studio                 # editar/previsualizar
npx remotion render anuncio-0 out/anuncio-0.mp4
```

## Afinar
- Cambia textos/tiempos del plan en `ad.json` (`plan.fullscreen`, `plan.pills`, `plan.emojis`).
- Componentes en `src/`: Card (tarjeta), Pill (badge), EmojiPop, Subtitles, Cta.
- Transiciones entre planos (whip-pan/zoom/glitch) y SFX riser/swoosh: ajuste manual aquí.
"""

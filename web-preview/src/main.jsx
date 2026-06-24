import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Player } from '@remotion/player';
import {
  AbsoluteFill, Audio, Sequence, Video, interpolate, spring,
  useCurrentFrame, useVideoConfig,
} from 'remotion';
import { loadFont } from '@remotion/google-fonts/Anton';

const { fontFamily } = loadFont();

// --------------------------------------------------------------------------- //
// Composición (espejo de la del proyecto, pero usando assetBase para los media)
// --------------------------------------------------------------------------- //
const clean = (s) => (s || '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
function darken(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 255) * k), g = Math.round(((n >> 8) & 255) * k), b = Math.round((n & 255) * k);
  return `rgb(${r},${g},${b})`;
}
function buildLines(words) {
  const lines = []; let cur = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i], prev = words[i - 1];
    const gap = prev ? w.start - prev.end : 0;
    if (cur.length && (cur.length >= 5 || gap > 0.6)) { lines.push(cur); cur = []; }
    cur.push(w);
  }
  if (cur.length) lines.push(cur);
  return lines;
}

function Subtitles({ words, plan }) {
  const { fps, width } = useVideoConfig();
  const frame = useCurrentFrame();
  const t = frame / fps;
  const lines = useMemo(() => buildLines(words || []), [words]);
  const accent = plan?.accent || '#FFD400';
  const style = plan?.subtitle_style || 'pop';
  const intensidad = (plan?.intensidad ?? 70) / 100;
  const emphasis = useMemo(() => new Set((plan?.emphasis || []).map((w) => clean(w))), [plan]);
  const line = lines.find((l) => t >= l[0].start && t <= l[l.length - 1].end);
  if (!line) return null;
  const activeIdx = line.findIndex((w) => t >= w.start && t < w.end);
  const fontSize = Math.round(width * (0.07 + 0.012 * intensidad));
  return (
    <div style={{ position: 'absolute', left: '8%', right: '8%', bottom: '15%', display: 'flex',
      flexWrap: 'wrap', gap: '0.28em 0.75em', justifyContent: 'center', alignItems: 'center', textAlign: 'center' }}>
      {line.map((w, i) => {
        const active = i === activeIdx;
        const isKey = emphasis.has(clean(w.word));
        const pop = Math.min(1, spring({ frame: frame - Math.round(w.start * fps), fps, config: { damping: 13, mass: 0.5 } }));
        const box = (style === 'box' || style === 'pop') && isKey;
        const punch = style === 'punch' && active;
        let color = '#FFFFFF';
        if (box) color = '#0b0b0b';
        else if (active && (style === 'karaoke' || style === 'pop' || style === 'punch')) color = accent;
        else if (isKey && (style === 'color' || style === 'karaoke')) color = accent;
        const scale = (isKey ? 1.06 : 1) * (active ? 1.05 : 1) * (punch ? 1.22 : 1) * (0.84 + 0.16 * pop);
        return (
          <span key={i} style={{ fontFamily, fontWeight: 900, fontSize, textTransform: 'uppercase',
            lineHeight: 1.18, color, background: box ? accent : 'transparent',
            padding: box ? '0.02em 0.22em' : 0, borderRadius: box ? '0.18em' : 0,
            WebkitTextStroke: box ? '0' : `${Math.max(2, fontSize * 0.06)}px #000`, paintOrder: 'stroke fill',
            textShadow: box ? '0 6px 16px rgba(0,0,0,0.45)' : '0 6px 18px rgba(0,0,0,0.6)',
            transform: `translateY(${(1 - pop) * 16}px) scale(${scale})`, opacity: pop, display: 'inline-block' }}>{w.word}</span>
        );
      })}
    </div>
  );
}

function Card({ top, keyText, sub, emoji, accent }) {
  const { fps, width, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const enter = spring({ frame: f, fps, config: { damping: 16, mass: 0.6 } });
  const out = interpolate(f, [durationInFrames - 7, durationInFrames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const o = Math.min(enter, out);
  const emo = spring({ frame: f - 2, fps, config: { damping: 9, mass: 0.5 } });
  const topIn = spring({ frame: f - 6, fps, config: { damping: 18 } });
  const keyPop = spring({ frame: f - 9, fps, config: { damping: 11, mass: 0.5 } });
  const subIn = spring({ frame: f - 14, fps, config: { damping: 18 } });
  const bgScale = interpolate(enter, [0, 1], [1.15, 1]);
  const pulse = 1 + 0.02 * Math.sin(f / fps * 5);
  const float = Math.sin(f / fps * 3) * 6;
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: o, overflow: 'hidden' }}>
      <AbsoluteFill style={{ transform: `scale(${bgScale})`, background: `radial-gradient(70% 55% at 50% 42%, ${accent}, ${darken(accent, 0.45)})` }} />
      <div style={{ margin: '0 7%', textAlign: 'center', transform: `translateY(${float}px)` }}>
        {emoji ? <div style={{ fontSize: Math.round(width * 0.18), lineHeight: 1, transform: `translateY(${(1 - emo) * 40}px) scale(${0.3 + 0.7 * Math.min(1, emo)})`, filter: 'drop-shadow(0 10px 18px rgba(0,0,0,0.45))', marginBottom: 8 }}>{emoji}</div> : null}
        {top ? <div style={{ color: '#ffffffe6', fontFamily, fontWeight: 800, letterSpacing: 2, fontSize: Math.round(width * 0.045), textTransform: 'uppercase', opacity: topIn, transform: `translateY(${(1 - topIn) * 20}px)` }}>{top}</div> : null}
        <div style={{ color: '#fff', fontFamily, fontWeight: 900, lineHeight: 1.02, fontSize: Math.round(width * 0.135), textTransform: 'uppercase', WebkitTextStroke: '2px rgba(0,0,0,0.3)', paintOrder: 'stroke fill', textShadow: '0 10px 30px rgba(0,0,0,0.35)', transform: `scale(${(0.6 + 0.4 * Math.min(1, keyPop)) * pulse})` }}>{keyText}</div>
        {sub ? <div style={{ color: '#ffffffe6', fontFamily, fontWeight: 700, marginTop: 14, fontSize: Math.round(width * 0.046), opacity: subIn, transform: `translateY(${(1 - subIn) * 16}px)` }}>{sub}</div> : null}
      </div>
    </AbsoluteFill>
  );
}

function Pill({ text, emoji, accent }) {
  const { fps, width, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const enter = spring({ frame: f, fps, config: { damping: 14, mass: 0.5 } });
  const out = interpolate(f, [durationInFrames - 6, durationInFrames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const o = Math.min(1, enter) * out;
  const float = Math.sin(f / fps * 3) * 6;
  const fontSize = Math.round(width * 0.05);
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, bottom: '30%', display: 'flex', justifyContent: 'center', opacity: o, transform: `translateY(${float + (1 - enter) * 30}px)` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, maxWidth: '84%', background: '#fff', border: `4px solid ${accent}`, borderRadius: 999, padding: '14px 26px 14px 14px', boxShadow: '0 12px 30px rgba(0,0,0,0.35)' }}>
        {emoji ? <div style={{ width: fontSize * 1.6, height: fontSize * 1.6, borderRadius: '50%', background: `${accent}22`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize, flexShrink: 0 }}>{emoji}</div> : null}
        <div style={{ color: accent, fontFamily, fontWeight: 900, fontSize, textTransform: 'uppercase', lineHeight: 1.05, filter: 'brightness(0.7)' }}>{text}</div>
      </div>
    </div>
  );
}

function EmojiPop({ emoji, idx }) {
  const { fps, width, durationInFrames } = useVideoConfig();
  const f = useCurrentFrame();
  const enter = spring({ frame: f, fps, config: { damping: 10, mass: 0.5 } });
  const out = interpolate(f, [durationInFrames - 6, durationInFrames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const o = Math.min(1, enter) * out;
  const float = Math.sin(f / fps * 4) * 8;
  const left = idx % 2 === 0 ? '16%' : '70%';
  const top = idx % 3 === 0 ? '24%' : '32%';
  return <div style={{ position: 'absolute', left, top, fontSize: Math.round(width * 0.13), opacity: o, transform: `translateY(${float}px) scale(${0.4 + 0.6 * Math.min(1, enter)})`, filter: 'drop-shadow(0 8px 14px rgba(0,0,0,0.4))' }}>{emoji}</div>;
}

function Cta({ texto, whatsapp, startFrame }) {
  const { fps, width } = useVideoConfig();
  const f = useCurrentFrame() - startFrame;
  const enter = spring({ frame: f, fps, config: { damping: 200 } });
  const pulse = 1 + 0.04 * Math.sin((f / fps) * 6);
  const bg = interpolate(enter, [0, 1], [0, 0.88]);
  return (
    <AbsoluteFill style={{ backgroundColor: `rgba(0,0,0,${bg})`, justifyContent: 'center', alignItems: 'center' }}>
      <div style={{ margin: '0 8%', textAlign: 'center', transform: `translateY(${(1 - enter) * 60}px)`, opacity: enter }}>
        <div style={{ color: '#fff', fontFamily, fontWeight: 900, fontSize: Math.round(width * 0.078), lineHeight: 1.15, WebkitTextStroke: '3px #000', paintOrder: 'stroke fill', marginBottom: 40 }}>{texto}</div>
        <div style={{ display: 'inline-block', background: '#25D366', color: '#0b3d2e', fontFamily, fontWeight: 900, fontSize: Math.round(width * 0.05), padding: '24px 48px', borderRadius: 999, transform: `scale(${pulse})`, boxShadow: '0 10px 30px rgba(0,0,0,0.4)' }}>WhatsApp →</div>
      </div>
    </AbsoluteFill>
  );
}

const CARD_S = 2.0;
function Ad({ v, cta, musica, sfx, assetBase }) {
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const plan = v.plan || {};
  const accent = plan.accent || '#FFD400';
  const palette = (plan.palette && plan.palette.length) ? plan.palette : [accent];
  const pick = (i) => palette[((i % palette.length) + palette.length) % palette.length];
  const src = (n) => `${assetBase}/${n}`;
  const ctaStart = durationInFrames - Math.round(3 * fps);
  const cards = (plan.fullscreen || []).map((c) => ({ ...c, f: Math.round(c.at * fps) }));
  const onCard = cards.some((c) => frame >= c.f && frame < c.f + CARD_S * fps);
  const isSpeaking = (f) => v.words.some((w) => f / fps >= w.start && f / fps < w.end);
  const kb = interpolate(frame, [0, durationInFrames], [1.03, 1.1], { extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill style={{ backgroundColor: 'black', overflow: 'hidden' }}>
      <AbsoluteFill style={{ transform: `scale(${kb})` }}>
        <Video src={src(v.video)} muted={!!v.voz} loop={!!v.voz} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      </AbsoluteFill>
      {v.voz ? <Audio src={src(v.voz)} /> : null}
      {v.music ? <Audio src={src(v.music)} loop volume={(f) => (isSpeaking(f) ? musica.ducking : musica.volumen)} /> : null}
      {sfx && sfx.whoosh ? cards.map((c, i) => (
        <Sequence key={`wh${i}`} from={c.f} durationInFrames={Math.round(0.6 * fps)}><Audio src={src(sfx.whoosh)} volume={0.5} /></Sequence>
      )) : null}
      {sfx && sfx.pop ? (v.lineStarts || []).map((s, i) => (
        <Sequence key={`pop${i}`} from={Math.round(s * fps)} durationInFrames={Math.round(0.18 * fps)}><Audio src={src(sfx.pop)} volume={0.3} /></Sequence>
      )) : null}
      {sfx && sfx.ding ? <Sequence from={ctaStart + Math.round(0.18 * fps)} durationInFrames={Math.round(0.7 * fps)}><Audio src={src(sfx.ding)} volume={0.5} /></Sequence> : null}
      {!onCard && frame < ctaStart ? <Subtitles words={v.words} plan={plan} /> : null}
      {(plan.pills || []).map((p, i) => (
        <Sequence key={`pill${i}`} from={Math.round(p.start * fps)} durationInFrames={Math.max(1, Math.round((p.end - p.start) * fps))}><Pill text={p.text} emoji={p.emoji} accent={pick(i + 1)} /></Sequence>
      ))}
      {(plan.emojis || []).map((e, i) => (
        <Sequence key={`em${i}`} from={Math.round(e.at * fps)} durationInFrames={Math.round(1.0 * fps)}><EmojiPop emoji={e.emoji} idx={i} /></Sequence>
      ))}
      {cards.map((c, i) => (
        <Sequence key={`card${i}`} from={c.f} durationInFrames={Math.round(CARD_S * fps)}><Card top={c.top} keyText={c.key} sub={c.sub} emoji={c.emoji} accent={pick(i)} /></Sequence>
      ))}
      {frame >= ctaStart ? <Cta texto={cta.texto} whatsapp={cta.whatsapp} startFrame={ctaStart} /> : null}
    </AbsoluteFill>
  );
}

// --------------------------------------------------------------------------- //
// App de preview
// --------------------------------------------------------------------------- //
function App() {
  const jobId = window.JOB_ID;
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [rendering, setRendering] = useState('');
  const [clips, setClips] = useState([]);

  useEffect(() => {
    fetch(`/api/jobs/${jobId}/ad.json`).then((r) => {
      if (!r.ok) throw new Error('No se encontró el proyecto');
      return r.json();
    }).then(setData).catch((e) => setErr(e.message));
  }, [jobId]);

  const assetBase = `/api/jobs/${jobId}/r`;

  async function render() {
    setRendering('Renderizando el video final… (puede tardar)');
    try {
      await fetch(`/api/jobs/${jobId}/render`, { method: 'POST' });
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const job = await (await fetch(`/api/jobs/${jobId}`)).json();
        setRendering(job.message || 'Renderizando…');
        if (job.clips && job.clips.length) { setClips(job.clips); setRendering(''); break; }
        if (job.status === 'error') { setRendering('Error: ' + (job.error || '')); break; }
      }
    } catch (e) { setRendering('Error: ' + e.message); }
  }

  if (err) return <div style={{ color: '#ff5c5c', padding: 30 }}>⚠️ {err}</div>;
  if (!data) return <div style={{ color: '#9aa0aa', padding: 30 }}>Cargando previsualización…</div>;

  return (
    <div style={{ maxWidth: 420, margin: '0 auto', padding: '24px 16px', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ color: '#fff', fontSize: 22 }}>👁️ Previsualización</h1>
      <p style={{ color: '#9aa0aa', fontSize: 14 }}>Así quedará el anuncio (en vivo, sin renderizar). Cuando te guste, dale a renderizar el video final.</p>
      {data.videos.map((v) => (
        <div key={v.id} style={{ marginBottom: 20 }}>
          <Player
            component={Ad}
            inputProps={{ v, cta: data.cta, musica: data.musica, sfx: data.sfx, assetBase }}
            durationInFrames={Math.max(1, Math.round(v.duration * data.fps))}
            fps={data.fps}
            compositionWidth={v.width}
            compositionHeight={v.height}
            style={{ width: '100%', borderRadius: 12, overflow: 'hidden', background: '#000' }}
            controls
            loop
          />
        </div>
      ))}

      {clips.length ? (
        <div style={{ marginTop: 16 }}>
          <p style={{ color: '#2ecc71' }}>✅ Video final listo.</p>
          {clips.map((u, i) => <a key={i} href={u} style={{ display: 'block', color: '#00d4ff', marginBottom: 6 }}>⬇️ Descargar anuncio {i + 1}</a>)}
        </div>
      ) : (
        <button onClick={render} disabled={!!rendering}
          style={{ width: '100%', padding: 14, borderRadius: 10, border: 'none', fontWeight: 700, cursor: 'pointer',
            background: 'linear-gradient(90deg,#7c5cff,#00d4ff)', color: '#fff', fontSize: 16 }}>
          🎬 Renderizar video final
        </button>
      )}
      {rendering ? <p style={{ color: '#9aa0aa', marginTop: 10 }}>{rendering}</p> : null}
      <p style={{ marginTop: 16 }}><a href="/" style={{ color: '#9aa0aa' }}>← Volver</a></p>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);

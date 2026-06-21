// Renderiza todas las composiciones de un proyecto de anuncio a mp4.
// Uso: node render.mjs <projDir> <outDir>
//   projDir: carpeta del proyecto generado (contiene src/index.ts, public/, ad.json)
//   outDir:  carpeta donde escribir clip_1.mp4, clip_2.mp4, ...
import { bundle } from '@remotion/bundler';
import { getCompositions, renderMedia, ensureBrowser } from '@remotion/renderer';
import path from 'node:path';
import fs from 'node:fs';

const projDir = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3]);
const entry = path.join(projDir, 'src', 'index.ts');
const publicDir = path.join(projDir, 'public');

fs.mkdirSync(outDir, { recursive: true });

console.log('[render] asegurando navegador…');
await ensureBrowser();

console.log('[render] bundling', entry);
const serveUrl = await bundle({ entryPoint: entry, publicDir });

const comps = await getCompositions(serveUrl, { logLevel: 'error' });
console.log('[render] composiciones:', comps.map((c) => c.id).join(', '));

let i = 1;
for (const comp of comps) {
  const out = path.join(outDir, `clip_${i}.mp4`);
  console.log(`[render] ${comp.id} -> ${out} (${comp.durationInFrames}f)`);
  await renderMedia({
    composition: comp,
    serveUrl,
    codec: 'h264',
    outputLocation: out,
    concurrency: 1,            // bajo uso de recursos
    logLevel: 'error',
  });
  console.log(`[render] OK ${out}`);
  i++;
}
console.log(`[render] LISTO ${i - 1} video(s)`);

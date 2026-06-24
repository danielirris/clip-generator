// Empaqueta la app de preview (React + @remotion/player) a un solo JS estático
// que sirve la app FastAPI: web/static/preview.js
import { build } from 'esbuild';

await build({
  entryPoints: ['src/main.jsx'],
  bundle: true,
  outfile: '../web/static/preview.js',
  format: 'iife',
  jsx: 'automatic',
  minify: true,
  define: { 'process.env.NODE_ENV': '"production"' },
  logLevel: 'info',
});
console.log('[build] preview.js listo');

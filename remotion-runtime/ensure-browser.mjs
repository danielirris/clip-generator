// Descarga el navegador headless de Remotion (Chrome Headless Shell) para
// hornearlo en la imagen Docker durante el build. Así el primer render no tiene
// que descargarlo en runtime.
import { ensureBrowser } from '@remotion/renderer';

await ensureBrowser();
console.log('[ensure-browser] Chrome Headless Shell listo.');

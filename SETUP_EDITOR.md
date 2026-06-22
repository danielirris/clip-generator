# Guía para el editor — correr y mejorar el proyecto en tu computador

Este proyecto genera anuncios (modo **Anuncio**) y montajes (modo **Montajes**).
El editor trabaja sobre todo en las **plantillas de Remotion** (la estética del
anuncio). Sigue estos pasos para tenerlo corriendo con TODAS las funciones
(incluido el render del video final).

## Requisitos
- **Python 3.11+**
- **Node.js 18+** (para renderizar los anuncios con Remotion)
- **FFmpeg con libass** (para los subtítulos). Ver nota abajo.
- Una **API key de OpenAI** (la pide quien te pasó el proyecto, o saca la tuya en
  https://platform.openai.com/api-keys).

## 1. Clonar
```bash
git clone https://github.com/danielirris/clip-generator.git
cd clip-generator
```

## 2. Entorno de Python
```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Runtime de Remotion (para renderizar el video final, una sola vez)
```bash
cd remotion-runtime && npm install && cd ..
```

## 4. FFmpeg con libass
- **Linux (Ubuntu/Debian):** `sudo apt install ffmpeg` (ya trae libass) ✅
- **macOS:** el FFmpeg de Homebrew a veces viene **sin** libass. Si los subtítulos
  no salen, descarga un FFmpeg con libass (p.ej. osxexperts.net, arm64), ponlo en
  una carpeta `bin/` del proyecto como `bin/ffmpeg` y crea `bin/ffprobe` apuntando
  al de Homebrew. El `run-local.sh` antepone `bin/` al PATH.
- **Windows:** instala FFmpeg (gyan.dev) y asegúrate de que esté en el PATH.

## 5. Clave de API
```bash
cp .env.example .env
# edita .env y pon:  OPENAI_API_KEY=sk-...
# (opcional) WHATSAPP_LINK=https://wa.me/TUNUMERO   para el botón del CTA
```

## 6. Correr
```bash
# macOS/Linux:
./run-local.sh
# o directamente:
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Abre **http://localhost:8000**.

---

## Dónde está lo que vas a mejorar (modo Anuncio)
- **Plantillas Remotion (la estética):** `app/pipeline/ad_export.py` → contiene los
  componentes `Ad.tsx`, `Subtitles.tsx`, `Cta.tsx`, `Intro.tsx` (como strings).
  Aquí ajustas subtítulos, animaciones, intro, CTA, SFX, etc.
- **Lineamientos de edición:** `remotion/PROMPT_EDICION.md`.
- **Render del video final:** `app/pipeline/ad_render.py` + `remotion-runtime/`.
- **Flujo / endpoints:** `app/jobs.py`, `app/main.py`. **Front:** `web/`.

### Probar un cambio de estilo rápido (sin la app)
La app genera, por cada job, un proyecto Remotion en
`storage/outputs/<id>/remotion-ad/`. Puedes abrirlo y editar en vivo:
```bash
cd storage/outputs/<id>/remotion-ad
npm install
npm run studio        # Remotion Studio: edita y previsualiza al instante
```
Cuando tengas la estética lista, **llévala a las plantillas de
`app/pipeline/ad_export.py`** para que TODOS los anuncios salgan así.

## Subir mejoras
```bash
git checkout -b mejora-estetica
git add -A && git commit -m "Mejora subtítulos y CTA"
git push -u origin mejora-estetica
# abre un Pull Request en GitHub
```

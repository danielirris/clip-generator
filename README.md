# 🎬 clip-generator

Aplicación web que toma un **compendio de videos** y genera automáticamente
**varios clips verticales de 48 s** (9:16) **mezclando los mejores fragmentos de
TODOS los videos**, con **subtítulos quemados**.

La IA corre **en la nube** (OpenAI: Whisper para transcribir + GPT para detectar
los ganchos). El servidor solo **orquesta** y ejecuta **FFmpeg**, así que
funciona cómodamente en una VPS pequeña (8 GB RAM / 80 GB disco).

---

## ¿Qué hace? (flujo)

1. Subes **varios videos** (`mp4` / `mov` / `mkv`) desde una web simple.
2. De cada video se extrae el audio (mono, 16 kHz) y se transcribe con
   **OpenAI Whisper** (con timestamps).
3. **GPT-4o-mini** analiza las transcripciones y detecta los mejores **ganchos**
   de apertura (frases que enganchan).
4. Se trocean **todos** los videos en fragmentos de 2 s → un **pool** grande.
5. Se componen **N clips** (5 por defecto). Cada clip = `[ganchos al inicio]` +
   `[cuerpo con fragmentos variados de todos los videos]`. Cada clip es una
   **combinación distinta**, con **cortes de duración variable (2–4 s)**.
6. FFmpeg normaliza cada fragmento a **1080×1920** (una sola vez, con caché),
   aplica **transiciones variadas** (3–6 por clip), **quita el audio original** y
   le pone **la música que subiste**. Se exporta además un **proyecto Remotion
   editable**. Ves el progreso y descargas los clips (uno a uno o todos en `.zip`).

```
[ N videos ] → [ Audio + Whisper ] → [ GPT: ganchos ] → [ Pool de fragmentos ]
            → [ Componer 5 combinaciones ] → [ FFmpeg 9:16 + subs ] → [ 5 clips de 48s ]
```

### Concepto clave
- Los **momentos impactantes** (ganchos) solo van al **inicio** de cada clip
  (los primeros `HOOK_BEATS` fragmentos). El **resto se rellena sin filtro
  estricto**, con fragmentos variados de todos los videos.
- Cada clip **mezcla todos los videos** (el pool se intercala en ronda).
- Los **N clips son combinaciones diferentes** del mismo pool.

### Especificación de cada clip
- Duración: **~48 s** (las transiciones solapan ~1–2 s; sin transiciones es 48 s exactos).
- **Cortes de duración variable** entre `BEAT_MIN_S` y `BEAT_MAX_S` (2–4 s).
- Vertical **9:16**, **1080×1920**, **H.264**, **30 fps**, **AAC**.
- Fondo configurable (`MODO_FONDO`): `blur` (fondo difuminado + video centrado),
  `crop` (recorte centrado) o `pad_negro` (barras negras).
- **Transiciones** entre fragmentos (3–6 por clip), `variadas` (fade/slide/wipe/
  zoom), `fundido` (solo crossfade) o `corte` (sin efecto). Configurable.
- Subtítulos quemados, sincronizados por video, grandes y con contorno
  (`SUBTITULOS`).
- **Audio:** se descarta el audio original y se usa la **música subida con el
  lote** (en bucle, recortada a la duración). Sin música → clip en silencio.

### Proyecto Remotion (edición)
Cada job exporta en `storage/outputs/{job_id}/remotion/` un proyecto editable:
`timeline.json` (la receta de cada clip), `beats/` (fragmentos normalizados),
la música, tu `PROMPT_EDICION.md` y una composición de ejemplo que lo lee. Ábrelo
con `npm install && npm run studio`. **Tu prompt de edición se edita una vez en
`remotion/PROMPT_EDICION.md`** (en la raíz del repo) y se copia a cada proyecto.

### Dos modos (selector en la web)
- **Montajes** (por defecto): varios videos → 5 clips verticales mezclados (lo de arriba).
- **Anuncio**: cada video → una composición en un **proyecto Remotion editable** que
  ya aplica los lineamientos de `remotion/PROMPT_EDICION.md` de forma determinista:
  **conserva el audio original**, música de fondo con **ducking**, **subtítulos
  sincronizados palabra por palabra** (timestamps reales), **safe-area** con
  auto-ajuste, **intro full-screen** y **CTA final** con botón animado a WhatsApp
  (sin número, link configurable con `WHATSAPP_LINK`). **La app renderiza el video
  TERMINADO** (mp4 listo para postear) usando un runtime de Remotion, y además te
  da el **proyecto editable** (`.zip`) por si quieres retocarlo en Remotion Studio.
  Verificado end-to-end: transcripción por palabra → render a 1080×1920 con
  subtítulos sincronizados y CTA.

  **Requisito para renderizar:** Node.js + dependencias del runtime
  (`cd remotion-runtime && npm install`, una sola vez). Si no hay Node (p.ej. en
  la imagen Docker actual), el modo anuncio degrada con elegancia y entrega solo
  el proyecto editable (`RENDERIZAR_ANUNCIO=false` para forzar ese comportamiento).

---

## Requisitos

- **Para Docker (recomendado):** solo Docker. FFmpeg (con libass) va dentro de
  la imagen.
- **Para correr local:** Python 3.11+ y **FFmpeg con libass** (para subtítulos).
- Una clave de API de **OpenAI**.

---

## Conseguir la API key

| Servicio | Dónde | Variable |
|----------|-------|----------|
| OpenAI   | https://platform.openai.com/api-keys | `OPENAI_API_KEY` |

---

## Correr en local (3 comandos)

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env   # y rellena OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

Abre <http://localhost:8000>, arrastra varios videos y genera los clips.

> En macOS, algunos builds de FFmpeg de Homebrew vienen **sin libass** (sin
> subtítulos). Ver [Troubleshooting](#troubleshooting).

### Tests

```bash
pip install -r requirements.txt
pytest -q
```

Los tests **mockean las APIs externas** (no llaman a OpenAI ni ejecutan FFmpeg):
parseo del JSON de ganchos, pool de fragmentos, composición de los clips
(mezcla de videos, ganchos al inicio, combinaciones distintas) y construcción de
comandos FFmpeg.

---

## Correr con Docker

```bash
docker build -t clip-generator .
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY=tu_clave \
  -v "$(pwd)/storage:/app/storage" \
  clip-generator
```

---

## Desplegar en EasyPanel (paso a paso)

1. **Sube el código a GitHub** (ver más abajo).
2. En EasyPanel, crea un **proyecto** y dentro un servicio **App**.
3. **Source → GitHub:** elige tu repositorio y la rama `main`.
4. **Build:** método **Dockerfile** (EasyPanel detecta el `Dockerfile` de la raíz).
5. **Environment:** añade `OPENAI_API_KEY` (el resto tienen valores por defecto).
6. **Volumen persistente (importante):** monta un volumen en **`/app/storage`**
   para que los clips no se pierdan al reiniciar y para no llenar la imagen.
7. **Puerto / Dominio:** expón el puerto **8000** y asígnale un dominio (EasyPanel
   gestiona el HTTPS).
8. **Healthcheck:** ya viene en el Dockerfile apuntando a `/healthz`.
9. **Deploy** y prueba subiendo varios videos.

> Recursos sugeridos: 1 vCPU y ~1.5–2 GB de RAM por contenedor. El cuello de
> botella es FFmpeg (un job a la vez).

### Variables de entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | **Obligatoria.** Clave de OpenAI. |
| `OPENAI_TRANSCRIBE_MODEL` | `whisper-1` | Modelo de transcripción. |
| `OPENAI_ANALYZE_MODEL` | `gpt-4o-mini` | Modelo de análisis de ganchos. |
| `NUM_CLIPS` | `5` | Cuántos clips generar por compendio (3–5 típico). |
| `DURACION_TOTAL_S` | `48` | Duración de cada clip (s). |
| `BEAT_MIN_S` | `2` | Duración mínima de cada corte (s). |
| `BEAT_MAX_S` | `4` | Duración máxima de cada corte (s). |
| `MIN_FRAGMENTOS` | `50` | Tamaño mínimo recomendado del pool (solo aviso). |
| `HOOK_BEATS` | `2` | Fragmentos "impactantes" al inicio de cada clip. |
| `MODO_FONDO` | `blur` | `blur` \| `crop` \| `pad_negro`. |
| `SUBTITULOS` | `true` | Quemar subtítulos (`true`/`false`). |
| `TRANSICIONES` | `true` | Aplicar transiciones entre fragmentos. |
| `TRANS_MIN` / `TRANS_MAX` | `3` / `6` | Nº de transiciones por clip. |
| `MODO_TRANSICION` | `variadas` | `variadas` \| `fundido` \| `corte`. |
| `TRANS_DUR_S` | `0.4` | Duración del solape de cada transición. |
| `QUITAR_AUDIO_ORIGINAL` | `true` | Quitar el audio original (usa la música). |
| `REMOTION_EXPORT` | `true` | Exportar proyecto Remotion editable. |
| `SEED` | `1234` | Semilla para reproducir cortes/transiciones. |
| `MAX_UPLOAD_MB` | `2048` | Tamaño máximo por archivo (MB). |
| `RETENCION_HORAS` | `24` | Borra outputs más antiguos que N horas. |
| `PORT` | `8000` | Puerto del servidor. |

---

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET  | `/` | Página de subida. |
| POST | `/api/jobs` | Sube videos (campo `files`) y música opcional (campo `music`) → `{ "job_id": ... }`. |
| GET  | `/api/jobs/{id}` | Estado del job + progreso + lista de URLs de clips cuando termina. |
| GET  | `/api/jobs/{id}/download/{n}` | Descarga el clip `n` (1-indexado). |
| GET  | `/api/jobs/{id}/download` | Descarga **todos** los clips en un `.zip`. |
| GET  | `/healthz` | Healthcheck. |

---

## Gestión de recursos (VPS)

- **Cola secuencial:** un único job a la vez (un hilo trabajador). Si llegan más,
  se encolan. Esto mantiene la RAM bajo control.
- **Render con caché:** cada fragmento de 2 s se normaliza **una sola vez** y se
  reutiliza en los clips que lo usen → 5 clips cuestan casi lo mismo que 1.
- Cada job trabaja en `storage/jobs/{job_id}/` y al terminar **borra todos los
  temporales** (audio, fragmentos y videos fuente), dejando solo los clips en
  `storage/outputs/{job_id}/`.
- **Purga automática:** se eliminan los outputs con más de `RETENCION_HORAS`.
- **Límite de subida:** `MAX_UPLOAD_MB` por archivo (validado en streaming).

---

## Costos aproximados

Orientativo (revisa los precios vigentes de OpenAI):

- **Whisper:** se factura por minuto de audio (~US$0.006/min). Un compendio de
  ~5 min ≈ **un par de centavos**.
- **GPT-4o-mini:** la transcripción como entrada de texto suele costar
  **una fracción de centavo**.
- **FFmpeg / VPS:** solo CPU del servidor; sin coste por API.

> Total típico por compendio: **del orden de centavos**.

---

## Troubleshooting

**`ffmpeg: command not found` / el job falla en "extracting".**
FFmpeg no está instalado o no está en el `PATH`. En Docker ya viene incluido; en
local instala FFmpeg (Debian/Ubuntu: `apt install ffmpeg`).

**Los subtítulos no aparecen / error "No such filter: 'ass'" o "No option name".**
Tu FFmpeg está compilado **sin libass**. Pasa con algunos builds de Homebrew en
macOS. Soluciones: usa Docker (incluye libass), instala un FFmpeg con libass, o
desactiva subtítulos con `SUBTITULOS=false`. El FFmpeg de Debian/Ubuntu (el de
la imagen Docker) **sí** incluye libass.

**Subtítulos con caja en vez de letras (fuente no encontrada).**
La imagen instala `fonts-dejavu-core` y el estilo usa **DejaVu Sans**.

**Los clips se parecen mucho entre sí.**
Con pocos videos o poco material, las combinaciones comparten fragmentos. Sube
**más videos y más variados** para que los clips sean más distintos. El aviso
del job indica si el pool quedó por debajo de `MIN_FRAGMENTOS`.

**Error 502 / el contenedor se reinicia al procesar.**
Es falta de recursos (CPU/RAM) en el VPS, no un fallo de la app. Soluciones:
sube el **límite de memoria** del servicio a ~2 GB en EasyPanel y mantén
`FFMPEG_THREADS=1` (limita el pico de CPU/RAM). El estado de los trabajos se
guarda en `storage/jobs.db`, así que si el contenedor se reinicia, los trabajos
en curso **se reanudan solos** y los ya terminados siguen descargables.

**Disco lleno.**
Baja `RETENCION_HORAS`, reduce `MAX_UPLOAD_MB` o amplía el volumen. Recuerda
montar `/app/storage` como volumen persistente.

**Rate limit / errores de red de OpenAI.**
Las llamadas reintentan con backoff exponencial (3 intentos). El análisis
reintenta una vez con un prompt más estricto si el JSON es inválido.

---

## Estructura del proyecto

```
clip-generator/
├── app/
│   ├── main.py              # FastAPI: endpoints + estáticos
│   ├── config.py            # variables de entorno (pydantic-settings)
│   ├── jobs.py              # cola secuencial, estado y orquestación
│   ├── retry.py             # reintentos con backoff
│   └── pipeline/
│       ├── audio.py         # extracción de audio + duración (ffmpeg/ffprobe)
│       ├── transcribe.py    # OpenAI Whisper → segmentos
│       ├── analyze.py       # OpenAI GPT → ganchos (JSON)
│       ├── fragments.py     # pool de fragmentos (cortes variables 2-4s)
│       ├── compose.py       # composición de N clips (combinaciones)
│       ├── render.py        # 9:16, subtítulos, transiciones, música, concat
│       ├── remotion_export.py # exporta el proyecto Remotion editable
│       └── cleanup.py       # borrado de temporales / purga
├── remotion/PROMPT_EDICION.md  # tu prompt de edición (se copia a cada job)
├── web/
│   ├── templates/index.html
│   └── static/ (style.css, app.js)
├── storage/                 # uploads, temporales y outputs (en .gitignore)
├── tests/                   # tests de parseo, pool, composición y comandos
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## Licencia

Uso libre. Ajusta a tus necesidades.

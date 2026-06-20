# 🎬 clip-generator

Aplicación web que toma un **video largo** y genera automáticamente un **clip
vertical de 48 segundos** (9:16) con los **momentos más impactantes** y
**subtítulos quemados**.

La IA pesada corre **en la nube** (Groq Whisper para transcribir + Gemini para
detectar momentos). El servidor solo **orquesta** y ejecuta **FFmpeg**, por lo
que funciona cómodamente en una VPS pequeña (8 GB RAM / 80 GB disco).

---

## ¿Qué hace? (flujo)

1. Subes un video (`mp4` / `mov` / `mkv`) desde una web simple.
2. Se extrae el audio con FFmpeg (mono, 16 kHz → mínimo tamaño/costo).
3. Se transcribe con **Groq Whisper large v3 turbo** (con timestamps).
4. **Gemini 2.5 Flash-Lite** analiza la transcripción y devuelve, en JSON, los
   mejores momentos para un clip.
5. FFmpeg corta esos momentos en **beats de 2 s**, los normaliza a **1080×1920**
   y los concatena en un único video de **48 s** con subtítulos.
6. Ves el progreso (polling) y descargas el resultado. Los temporales se borran.

```
[ Video ] → [ Audio 16kHz ] → [ Groq Whisper ] → [ Gemini ] → [ FFmpeg 9:16 + subs ] → [ Clip 48s ]
```

### Especificación del clip de salida
- Duración: **48 s** = **24 beats × 2 s** (configurable).
- Vertical **9:16**, **1080×1920**, **H.264**, **30 fps**, **AAC**.
- Fondo configurable (`MODO_FONDO`): `blur` (fondo difuminado + video centrado),
  `crop` (recorte centrado) o `pad_negro` (barras negras).
- Subtítulos quemados, sincronizados, grandes y con contorno (`SUBTITULOS`).
- Si no hay material para 48 s, genera el clip más largo posible (múltiplo de
  2 s) y lo avisa en la respuesta.

---

## Requisitos

- **Para Docker (recomendado):** solo Docker. FFmpeg va dentro de la imagen.
- **Para correr local:** Python 3.11+ y **FFmpeg con libass** instalado
  (la mayoría de paquetes de Linux lo incluyen; en macOS, ver troubleshooting).
- Claves de API de **Groq** y **Gemini**.

---

## Conseguir las API keys

| Servicio | Dónde | Variable |
|----------|-------|----------|
| Groq     | https://console.groq.com/keys | `GROQ_API_KEY` |
| Gemini   | https://aistudio.google.com/app/apikey | `GEMINI_API_KEY` |

Ambas tienen plan gratuito suficiente para probar.

---

## Correr en local (3 comandos)

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env   # y rellena GROQ_API_KEY y GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000
```

Abre <http://localhost:8000>.

> En macOS, el FFmpeg de Homebrew puede venir **sin libass** (sin subtítulos).
> Ver [Troubleshooting](#troubleshooting).

### Tests

```bash
pip install -r requirements.txt
pytest -q
```

Los tests **mockean las APIs externas**: cubren el parseo del JSON de Gemini,
el cálculo de beats de 2 s y la construcción de comandos FFmpeg (no ejecutan
Groq/Gemini ni FFmpeg).

---

## Correr con Docker

```bash
docker build -t clip-generator .
docker run --rm -p 8000:8000 \
  -e GROQ_API_KEY=tu_clave_groq \
  -e GEMINI_API_KEY=tu_clave_gemini \
  -v "$(pwd)/storage:/app/storage" \
  clip-generator
```

---

## Desplegar en EasyPanel (paso a paso)

1. **Sube el código a GitHub** (ver más abajo).
2. En EasyPanel, crea un **proyecto** y dentro un servicio **App**.
3. **Source → GitHub:** elige tu repositorio `clip-generator` y la rama `main`.
4. **Build:** método **Dockerfile** (EasyPanel detecta el `Dockerfile` de la raíz).
5. **Environment:** añade las variables (mínimo `GROQ_API_KEY` y `GEMINI_API_KEY`;
   el resto tienen valores por defecto). Ver tabla abajo.
6. **Volumen persistente (importante):** monta un volumen en **`/app/storage`**
   para que los outputs no se pierdan al reiniciar el contenedor y para no
   llenar la capa de la imagen.
7. **Puerto / Dominio:** expón el puerto **8000** y asígnale un dominio. EasyPanel
   gestiona el HTTPS.
8. **Healthcheck:** ya viene en el Dockerfile apuntando a `/healthz`.
9. **Deploy.** Cuando termine, entra al dominio y sube un video de prueba.

> Recursos sugeridos en EasyPanel: 1 vCPU y ~1.5–2 GB de RAM por contenedor son
> suficientes (el cuello de botella es FFmpeg, single-thread por job).

### Variables de entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `GROQ_API_KEY` | — | **Obligatoria.** Clave de Groq. |
| `GEMINI_API_KEY` | — | **Obligatoria.** Clave de Gemini. |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3-turbo` | Modelo de transcripción. |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Modelo de análisis. |
| `DURACION_TOTAL_S` | `48` | Duración total objetivo (s). |
| `DURACION_BEAT_S` | `2` | Duración de cada beat (s). |
| `MODO_FONDO` | `blur` | `blur` \| `crop` \| `pad_negro`. |
| `SUBTITULOS` | `true` | Quemar subtítulos (`true`/`false`). |
| `MAX_UPLOAD_MB` | `2048` | Tamaño máximo de subida (MB). |
| `RETENCION_HORAS` | `24` | Borra outputs más antiguos que N horas. |
| `PORT` | `8000` | Puerto del servidor. |

---

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET  | `/` | Página de subida. |
| POST | `/api/jobs` | Sube el video (multipart) y crea el job → `{ "job_id": ... }`. |
| GET  | `/api/jobs/{id}` | Estado del job (`queued`/`extracting`/`transcribing`/`analyzing`/`rendering`/`done`/`error`) + progreso. |
| GET  | `/api/jobs/{id}/download` | Descarga el `mp4` final. |
| GET  | `/healthz` | Healthcheck. |

---

## Gestión de recursos (VPS)

- **Cola secuencial:** un único job a la vez (un hilo trabajador). Si llegan más,
  se encolan. Esto mantiene la RAM bajo control.
- Cada job trabaja en `storage/jobs/{job_id}/` y al terminar (éxito o error)
  **borra todos los temporales**, dejando solo `storage/outputs/{job_id}.mp4`.
- El **video fuente** se borra al acabar el render.
- **Purga automática:** se eliminan los outputs con más de `RETENCION_HORAS`.
- **Límite de subida:** `MAX_UPLOAD_MB` (se valida en streaming, sin cargar todo
  el archivo en memoria).

---

## Costos aproximados

Orientativo, por video de ~10 minutos (varía según proveedor y precios vigentes):

- **Groq Whisper turbo:** se factura por minuto de audio; ~10 min ≈ **fracciones
  de centavo**.
- **Gemini 2.5 Flash-Lite:** transcripción como entrada de texto; un video de
  ~10 min suele costar **unos pocos centavos o menos**.
- **FFmpeg / VPS:** solo CPU del servidor; sin coste por API.

> Total típico por video: **del orden de céntimos**. Revisa los precios actuales
> de cada proveedor, que pueden cambiar.

---

## Troubleshooting

**`ffmpeg: command not found` / el job falla en "extracting".**
FFmpeg no está instalado o no está en el `PATH`. En Docker ya viene incluido; en
local instala FFmpeg (Debian/Ubuntu: `apt install ffmpeg`).

**Los subtítulos no aparecen / error "No such filter: 'ass'".**
Tu FFmpeg está compilado **sin libass**. Pasa con algunos builds de Homebrew en
macOS. Soluciones: usa Docker (incluye libass), instala un FFmpeg con libass, o
desactiva subtítulos con `SUBTITULOS=false`. El FFmpeg de Debian/Ubuntu (el de
la imagen Docker) **sí** incluye libass.

**Subtítulos con caja en vez de letras (fuente no encontrada).**
La imagen instala `fonts-dejavu-core` y el estilo usa **DejaVu Sans**. Si cambias
la fuente, asegúrate de que exista en el contenedor.

**Disco lleno.**
Baja `RETENCION_HORAS`, reduce `MAX_UPLOAD_MB`, o amplía el volumen. Recuerda
montar `/app/storage` como volumen persistente; los temporales por job se borran
solos al terminar.

**Rate limit / errores de red de Groq o Gemini.**
Las llamadas reintentan con backoff exponencial (3 intentos). Si persiste, es
límite de tu plan: espera o sube de tier. Gemini además reintenta una vez con un
prompt más estricto si devuelve un JSON inválido.

**El clip dura menos de 48 s.**
No había suficiente material "impactante". La app genera el clip más largo
posible (múltiplo de 2 s) y lo indica en el campo `aviso` del estado del job.

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
│       ├── audio.py         # extracción de audio (ffmpeg)
│       ├── transcribe.py    # Groq Whisper → segmentos
│       ├── analyze.py       # Gemini → JSON de momentos
│       ├── render.py        # beats, 9:16, subtítulos y concat
│       └── cleanup.py       # borrado de temporales / purga
├── web/
│   ├── templates/index.html
│   └── static/ (style.css, app.js)
├── storage/                 # uploads y outputs (en .gitignore)
├── tests/                   # tests de parseo, beats y comandos ffmpeg
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## Licencia

Uso libre. Ajusta a tus necesidades.

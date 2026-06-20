# clip-generator — imagen ligera con FFmpeg incluido.
FROM python:3.11-slim

# Evita prompts de apt y buffers de Python.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# FFmpeg (extracción de audio + render) y fuentes para los subtítulos.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias primero (mejor cacheo de capas).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código de la aplicación.
COPY app/ ./app/
COPY web/ ./web/

# Carpeta de almacenamiento (se monta como volumen persistente en EasyPanel).
RUN mkdir -p /app/storage

EXPOSE 8000

# Healthcheck para EasyPanel / Docker.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz').status==200 else sys.exit(1)"

# Arranque: lee el puerto de la env PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

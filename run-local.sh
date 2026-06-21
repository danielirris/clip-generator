#!/bin/bash
# Lanzador local de clip-generator (con FFmpeg + libass para subtítulos).
# Uso:  ./run-local.sh   y abre http://localhost:8000
set -e
cd "$(dirname "$0")"

# FFmpeg con libass (carpeta bin/) por delante en el PATH.
export PATH="$PWD/bin:$PATH"

# Activar el entorno virtual.
source .venv/bin/activate

echo "==============================================="
echo "  clip-generator  ->  http://localhost:8000"
echo "  (Ctrl+C para detener)"
echo "==============================================="
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

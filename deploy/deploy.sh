#!/bin/bash
# =============================================================
# deploy.sh — Script de despliegue para el VPS (Ubuntu/Debian)
# Uso: bash deploy.sh
# Ejecutar como el usuario de la app (NO root)
# =============================================================
set -euo pipefail

APP_DIR="/opt/binabot"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="binabot"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

echo ">>> [1/7] Actualizando código..."
cd "$APP_DIR"
git pull origin main

echo ">>> [2/7] Activando virtualenv..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

echo ">>> [3/7] Instalando dependencias..."
"$PIP" install --upgrade pip
"$PIP" install -r requirements.txt

echo ">>> [4/7] Ejecutando migraciones..."
"$PYTHON" manage.py migrate --noinput

echo ">>> [5/7] Recolectando archivos estáticos..."
"$PYTHON" manage.py collectstatic --noinput

echo ">>> [6/7] Reiniciando servicio..."
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl restart nginx

echo ">>> [7/7] Verificando estado..."
sudo systemctl status "$SERVICE_NAME" --no-pager
echo "Despliegue completado."

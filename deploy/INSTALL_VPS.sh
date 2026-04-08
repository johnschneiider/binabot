# Guía de instalación inicial en VPS (Ubuntu 22.04 / Debian 12)
# Ejecutar estos comandos por SSH como root o con sudo

# ─────────────────────────────────────────────
# 1. PREPARAR EL SERVIDOR
# ─────────────────────────────────────────────
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git nginx postgresql \
    postgresql-client libpq-dev build-essential

# ─────────────────────────────────────────────
# 2. CREAR USUARIO DE LA APP (no root)
# ─────────────────────────────────────────────
sudo useradd -m -s /bin/bash binabot
sudo mkdir -p /opt/binabot /var/log/binabot /run/binabot
sudo chown binabot:binabot /opt/binabot /var/log/binabot /run/binabot

# ─────────────────────────────────────────────
# 3. CLONAR EL REPOSITORIO
# ─────────────────────────────────────────────
sudo -u binabot git clone https://github.com/johnschneiider/binabot.git /opt/binabot

# ─────────────────────────────────────────────
# 4. CREAR .env DE PRODUCCIÓN
# ─────────────────────────────────────────────
# Copia env.example y rellena los valores reales
sudo cp /opt/binabot/env.example /opt/binabot/.env
sudo nano /opt/binabot/.env
# ▶ Configura al menos:
#   DJANGO_SECRET_KEY=<genera con: python3 -c "import secrets; print(secrets.token_hex(50))">
#   DJANGO_DEBUG=False
#   DJANGO_ALLOWED_HOSTS=TU_IP,TU_DOMINIO.COM
#   DB_ENGINE=postgresql
#   DB_NAME=binabot_db
#   DB_USER=binabot_user
#   DB_PASSWORD=<contraseña segura>
#   DERIV_API_TOKEN=<tu token real>

sudo chown binabot:binabot /opt/binabot/.env
sudo chmod 600 /opt/binabot/.env

# ─────────────────────────────────────────────
# 5. CONFIGURAR POSTGRESQL
# ─────────────────────────────────────────────
sudo -u postgres psql -c "CREATE DATABASE binabot_db;"
sudo -u postgres psql -c "CREATE USER binabot_user WITH PASSWORD 'CAMBIA_ESTO';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE binabot_db TO binabot_user;"

# ─────────────────────────────────────────────
# 6. INSTALAR DEPENDENCIAS Y CONFIGURAR APP
# ─────────────────────────────────────────────
sudo -u binabot bash /opt/binabot/deploy/deploy.sh

# ─────────────────────────────────────────────
# 7. INSTALAR SERVICIO SYSTEMD
# ─────────────────────────────────────────────
sudo cp /opt/binabot/deploy/binabot.service /etc/systemd/system/binabot.service
sudo systemctl daemon-reload
sudo systemctl enable binabot
sudo systemctl start binabot
sudo systemctl status binabot

# ─────────────────────────────────────────────
# 8. CONFIGURAR NGINX
# ─────────────────────────────────────────────
# Edita deploy/nginx.conf y reemplaza TU_DOMINIO_O_IP
sudo nano /opt/binabot/deploy/nginx.conf

sudo cp /opt/binabot/deploy/nginx.conf /etc/nginx/sites-available/binabot
sudo ln -s /etc/nginx/sites-available/binabot /etc/nginx/sites-enabled/binabot
sudo nginx -t && sudo systemctl reload nginx

# ─────────────────────────────────────────────
# 9. SSL CON CERTBOT (si tienes dominio propio)
# ─────────────────────────────────────────────
# sudo apt install -y certbot python3-certbot-nginx
# sudo certbot --nginx -d TU_DOMINIO.COM

# ─────────────────────────────────────────────
# ACTUALIZAR EN PRODUCCIÓN (próximas veces)
# ─────────────────────────────────────────────
# sudo -u binabot bash /opt/binabot/deploy/deploy.sh

cd /var/www/vitalmix.com.co/app
git pull origin main
source .venv/bin/activate
python manage.py mejorar_estrategia_extremos --dias 30
python manage.py auditar_bot --completo --dias 30


para reiniciar
systemctl restart binabot-vitalmix.service
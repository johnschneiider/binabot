# Corregir Servicio Bot Inverso

Si el servicio tiene errores, sigue estos pasos:

## 1. Eliminar el archivo corrupto

```bash
sudo rm /etc/systemd/system/binabot-inverso.service
```

## 2. Crear el archivo correctamente

```bash
sudo nano /etc/systemd/system/binabot-inverso.service
```

**Pegar EXACTAMENTE este contenido (sin espacios extra, sin líneas duplicadas):**

```ini
[Unit]
Description=Bot Inverso - Ejecuta estrategia opuesta al bot principal
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/vitalmix.com.co/app/src
Environment="PATH=/var/www/vitalmix.com.co/app/.venv/bin"
ExecStart=/var/www/vitalmix.com.co/app/.venv/bin/python manage.py ejecutar_bot_inverso --intervalo 5
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**IMPORTANTE:**
- No debe haber líneas duplicadas
- No debe haber espacios extra al final de las líneas
- Debe terminar con una línea vacía al final

## 3. Verificar el archivo

```bash
# Verificar que no hay líneas duplicadas
cat /etc/systemd/system/binabot-inverso.service | grep -c "ExecStart"
# Debe mostrar: 1

# Verificar formato
sudo systemctl daemon-reload
sudo systemctl status binabot-inverso.service
```

## 4. Activar el servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable binabot-inverso.service
sudo systemctl start binabot-inverso.service
sudo systemctl status binabot-inverso.service
```

## Alternativa: Usar cat para crear el archivo

```bash
sudo tee /etc/systemd/system/binabot-inverso.service > /dev/null << 'EOF'
[Unit]
Description=Bot Inverso - Ejecuta estrategia opuesta al bot principal
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/vitalmix.com.co/app/src
Environment="PATH=/var/www/vitalmix.com.co/app/.venv/bin"
ExecStart=/var/www/vitalmix.com.co/app/.venv/bin/python manage.py ejecutar_bot_inverso --intervalo 5
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable binabot-inverso.service
sudo systemctl start binabot-inverso.service
```


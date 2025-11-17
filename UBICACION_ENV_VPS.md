# Ubicación del Archivo .env en la VPS

## 📍 Ubicación del Archivo `.env`

El archivo `.env` que contiene la configuración de la API de Deriv está en:

```bash
/var/www/vitalmix.com.co/app/.env
```

**Nota:** El archivo está en el directorio **padre** del proyecto (`/app/.env`), no dentro de `/app/src/`.

## 🔍 Cómo Verificar y Editar

### 1. Verificar que existe el archivo:

```bash
ls -la /var/www/vitalmix.com.co/app/.env
```

### 2. Ver el contenido (sin editar):

```bash
cat /var/www/vitalmix.com.co/app/.env
```

### 3. Editar el archivo:

```bash
nano /var/www/vitalmix.com.co/app/.env
```

O con vim:
```bash
vim /var/www/vitalmix.com.co/app/.env
```

## 📝 Variables de la API de Deriv

Las variables que debes buscar y modificar son:

```env
DERIV_API_TOKEN=tu_token_aqui
DERIV_ACCOUNT_ID=tu_account_id_aqui
DERIV_APP_ID=1089
```

## 🔍 Buscar las Variables Específicas

Si solo quieres ver las variables de Deriv:

```bash
grep "DERIV" /var/www/vitalmix.com.co/app/.env
```

Esto mostrará solo las líneas que contienen "DERIV".

## ⚠️ Importante

- El archivo `.env` puede estar oculto (empieza con punto)
- Asegúrate de tener permisos para editarlo (generalmente necesitas `sudo`)
- Haz un backup antes de editar:

```bash
# Crear backup
cp /var/www/vitalmix.com.co/app/.env /var/www/vitalmix.com.co/app/.env.backup

# Editar
sudo nano /var/www/vitalmix.com.co/app/.env
```

## 🔄 Después de Editar

Después de cambiar las variables, **reinicia los servicios**:

```bash
sudo systemctl restart binabot-loop.service
sudo systemctl restart binabot-ticks.service
sudo systemctl restart binabot.service
```

## 📂 Estructura de Directorios

```
/var/www/vitalmix.com.co/
└── app/
    ├── .env                    ← AQUÍ está el archivo
    ├── .venv/                  ← Entorno virtual
    └── src/                    ← Código del proyecto
        ├── manage.py
        ├── bot_deriv/
        ├── core/
        └── ...
```

## 🛠️ Comandos Rápidos

### Ver solo las variables de Deriv:
```bash
grep "DERIV" /var/www/vitalmix.com.co/app/.env
```

### Ver el token actual (ocultando parte por seguridad):
```bash
grep "DERIV_API_TOKEN" /var/www/vitalmix.com.co/app/.env | sed 's/=.*/=***OCULTO***/'
```

### Verificar que el archivo se está cargando:
```bash
cd /var/www/vitalmix.com.co/app/src
source /var/www/vitalmix.com.co/app/.venv/bin/activate
python manage.py shell -c "from django.conf import settings; print('Token configurado:', bool(settings.DERIV_API_TOKEN))"
```

## 🔐 Seguridad

- **NUNCA** subas el archivo `.env` a Git
- El archivo `.env` está en `.gitignore` por seguridad
- Mantén los permisos restrictivos:

```bash
# Ver permisos actuales
ls -la /var/www/vitalmix.com.co/app/.env

# Ajustar permisos (solo lectura para otros, lectura/escritura para propietario)
chmod 600 /var/www/vitalmix.com.co/app/.env
```


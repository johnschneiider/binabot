# Guía de Migración de SQLite a PostgreSQL

Esta guía te ayudará a migrar de forma segura de SQLite a PostgreSQL.

## ¿Por qué migrar a PostgreSQL?

- **Concurrencia**: PostgreSQL maneja múltiples procesos simultáneos sin bloqueos
- **Rendimiento**: Mejor para aplicaciones en producción
- **Escalabilidad**: Soporta mayor volumen de datos y transacciones
- **Características avanzadas**: Funciones, triggers, vistas materializadas, etc.

## Requisitos Previos

1. PostgreSQL instalado y corriendo
2. Usuario de PostgreSQL con permisos para crear bases de datos
3. Python con `psycopg2-binary` instalado

## Paso 1: Instalar PostgreSQL (si no está instalado)

### En Debian/Ubuntu:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

## Paso 2: Crear Base de Datos y Usuario

```bash
# Acceder como usuario postgres
sudo -u postgres psql

# Crear base de datos
CREATE DATABASE binabot;

# Crear usuario (opcional, puedes usar postgres)
CREATE USER binabot_user WITH PASSWORD 'tu_password_segura';

# Dar permisos
GRANT ALL PRIVILEGES ON DATABASE binabot TO binabot_user;

# Si usas el usuario postgres, asegúrate de tener la contraseña configurada
ALTER USER postgres PASSWORD 'tu_password_segura';

# Salir
\q
```

## Paso 3: Configurar Variables de Entorno

Edita tu archivo `.env` y agrega:

```bash
# Base de datos
DB_ENGINE=postgresql
DB_NAME=binabot
DB_USER=postgres  # o binabot_user si creaste uno
DB_PASSWORD=tu_password_segura
DB_HOST=localhost
DB_PORT=5432
```

**IMPORTANTE**: No cambies `DB_ENGINE` todavía. Lo haremos después de la migración.

## Paso 4: Instalar Dependencias

```bash
source /var/www/vitalmix.com.co/app/.venv/bin/activate
pip install psycopg2-binary
```

## Paso 5: Verificar Conexión

```bash
# Probar conexión manualmente
psql -h localhost -U postgres -d binabot
# Ingresa la contraseña cuando se solicite
# Si conecta correctamente, escribe \q para salir
```

## Paso 6: Hacer Backup de SQLite

```bash
cd /var/www/vitalmix.com.co/app/src
cp db.sqlite3 db.sqlite3.backup_$(date +%Y%m%d_%H%M%S)
```

## Paso 7: Detener Servicios

```bash
systemctl stop binabot-loop.service
systemctl stop binabot-ticks.service
systemctl stop binabot.service
```

## Paso 8: Ejecutar Migración

```bash
cd /var/www/vitalmix.com.co/app/src
source /var/www/vitalmix.com.co/app/.venv/bin/activate

# Actualizar código
git pull

# Ejecutar migración (aún con SQLite activo)
python manage.py migrar_a_postgresql --confirmar
```

El comando:
1. Verificará la conexión a PostgreSQL
2. Creará backup automático de SQLite
3. Creará el esquema en PostgreSQL
4. Migrará todos los datos
5. Verificará la integridad

## Paso 9: Activar PostgreSQL

Edita tu archivo `.env` y asegúrate de que tenga:

```bash
DB_ENGINE=postgresql
```

## Paso 10: Reiniciar Servicios

```bash
systemctl start binabot-loop.service
systemctl start binabot-ticks.service
systemctl start binabot.service

# Verificar que están corriendo
systemctl status binabot-loop.service
systemctl status binabot-ticks.service
systemctl status binabot.service
```

## Paso 11: Verificar Funcionamiento

```bash
# Verificar que los datos están en PostgreSQL
python manage.py shell
```

En el shell de Django:
```python
from core.models import ConfiguracionBot
from historial.models import Operacion

# Verificar datos
print(f"Configuraciones: {ConfiguracionBot.objects.count()}")
print(f"Operaciones: {Operacion.objects.count()}")

# Verificar una configuración
config = ConfiguracionBot.obtener()
print(f"Balance actual: {config.balance_actual}")
```

## Solución de Problemas

### Error: "password authentication failed"

1. Verifica que la contraseña en `.env` sea correcta
2. Verifica el archivo `pg_hba.conf`:
   ```bash
   sudo nano /etc/postgresql/*/main/pg_hba.conf
   ```
   Asegúrate de que tenga:
   ```
   local   all             postgres                                md5
   host    all             all             127.0.0.1/32            md5
   ```
3. Reinicia PostgreSQL:
   ```bash
   sudo systemctl restart postgresql
   ```

### Error: "could not connect to server"

1. Verifica que PostgreSQL esté corriendo:
   ```bash
   sudo systemctl status postgresql
   ```
2. Verifica que el puerto 5432 esté abierto:
   ```bash
   sudo netstat -tlnp | grep 5432
   ```

### Error: "database does not exist"

Ejecuta:
```bash
sudo -u postgres createdb binabot
```

### Verificar que PostgreSQL está usando la configuración correcta

```bash
python manage.py shell
```

```python
from django.conf import settings
print(settings.DATABASES['default']['ENGINE'])
# Debe mostrar: django.db.backends.postgresql
```

## Rollback (Volver a SQLite)

Si necesitas volver a SQLite:

1. Edita `.env` y cambia:
   ```bash
   DB_ENGINE=sqlite
   ```
   O simplemente elimina/comenta las líneas de DB_*.

2. Reinicia los servicios

3. El archivo `db.sqlite3` sigue existiendo con todos los datos

## Notas Importantes

- El archivo `db.sqlite3` NO se elimina automáticamente (se mantiene como backup)
- Puedes eliminarlo manualmente después de verificar que todo funciona
- Los backups se guardan con timestamp: `db.sqlite3.backup_YYYYMMDD_HHMMSS`
- PostgreSQL es mucho más robusto para producción con múltiples procesos


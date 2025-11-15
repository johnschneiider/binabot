# Comandos de Investigación - Error "value too long for type character varying(40)"

## 1. Verificar que el código se actualizó correctamente

```bash
# Ver el contenido del archivo que genera numero_contrato
grep -A 5 "numero_contrato = f" /var/www/vitalmix.com.co/app/src/trading/services_profesional.py

# Verificar la versión del archivo en el servidor
head -20 /var/www/vitalmix.com.co/app/src/trading/services_profesional.py | grep -E "(numero_contrato|uuid)"

# Comparar con el repositorio remoto
cd /var/www/vitalmix.com.co/app/src
git log --oneline -5
git show HEAD:trading/services_profesional.py | grep -A 5 "numero_contrato"
```

## 2. Verificar procesos y caché

```bash
# Ver todos los procesos Python relacionados con el bot
ps aux | grep -E "(binabot|manage.py|ejecutar_bot)" | grep -v grep

# Verificar si hay procesos antiguos con código en memoria
ps aux | grep python | grep ejecutar_bot

# Verificar archivos .pyc que puedan tener código antiguo
find /var/www/vitalmix.com.co/app/src -name "*.pyc" -ls
find /var/www/vitalmix.com.co/app/src -type d -name __pycache__ -ls

# Limpiar TODO el caché de Python
find /var/www/vitalmix.com.co/app/src -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find /var/www/vitalmix.com.co/app/src -name "*.pyc" -delete
find /var/www/vitalmix.com.co/app/src -name "*.pyo" -delete
```

## 3. Verificar el código específico que causa el error

```bash
# Ver exactamente qué línea genera numero_contrato
sed -n '270,290p' /var/www/vitalmix.com.co/app/src/trading/services_profesional.py

# Verificar si hay múltiples definiciones de numero_contrato
grep -n "numero_contrato" /var/www/vitalmix.com.co/app/src/trading/services_profesional.py

# Verificar el modelo Operacion para confirmar max_length
grep -A 2 "numero_contrato" /var/www/vitalmix.com.co/app/src/historial/models.py
```

## 4. Verificar la base de datos

```bash
# Conectarse a PostgreSQL y verificar la estructura de la tabla
psql -U postgres -d binabot -c "\d historial_operacion"

# Verificar si hay registros con numero_contrato largo
psql -U postgres -d binabot -c "SELECT numero_contrato, LENGTH(numero_contrato) as len FROM historial_operacion ORDER BY creado DESC LIMIT 10;"

# Verificar el tipo de dato exacto en la BD
psql -U postgres -d binabot -c "SELECT column_name, character_maximum_length FROM information_schema.columns WHERE table_name = 'historial_operacion' AND column_name = 'numero_contrato';"
```

## 5. Verificar el entorno Python

```bash
# Verificar qué Python está usando el servicio
systemctl cat binabot-loop.service | grep ExecStart

# Verificar la versión de Python
/var/www/vitalmix.com.co/app/.venv/bin/python --version

# Verificar si hay módulos importados en memoria
/var/www/vitalmix.com.co/app/.venv/bin/python -c "import sys; print(sys.path)"

# Verificar si el código se está importando desde otro lugar
/var/www/vitalmix.com.co/app/.venv/bin/python -c "import trading.services_profesional; print(trading.services_profesional.__file__)"
```

## 6. Test directo del código

```bash
# Ejecutar un test directo para ver qué genera
cd /var/www/vitalmix.com.co/app/src
source /var/www/vitalmix.com.co/app/.venv/bin/activate

python -c "
import uuid
uuid_str = str(uuid.uuid4()).replace('-', '')
numero_contrato = f'PEND-{uuid_str[:32]}'
numero_contrato = numero_contrato[:40]
print(f'UUID sin guiones: {uuid_str}')
print(f'Longitud UUID: {len(uuid_str)}')
print(f'numero_contrato: {numero_contrato}')
print(f'Longitud numero_contrato: {len(numero_contrato)}')
print(f'¿Excede 40? {len(numero_contrato) > 40}')
"

# Verificar el código exacto que se ejecuta
python -c "
import sys
sys.path.insert(0, '/var/www/vitalmix.com.co/app/src')
import inspect
from trading import services_profesional
source = inspect.getsource(services_profesional.MotorTradingProfesional.ejecutar_ciclo)
lines = source.split('\n')
for i, line in enumerate(lines[270:290], start=271):
    if 'numero_contrato' in line.lower():
        print(f'{i}: {line}')
"
```

## 7. Verificar logs detallados

```bash
# Ver los últimos errores con más contexto
journalctl -u binabot-loop.service -n 100 --no-pager | grep -A 20 "value too long"

# Ver si hay errores de importación
journalctl -u binabot-loop.service -n 200 --no-pager | grep -E "(ImportError|ModuleNotFoundError|SyntaxError)"

# Ver el proceso completo desde el inicio
journalctl -u binabot-loop.service --since "10 minutes ago" --no-pager
```

## 8. Verificar si hay código en otro lugar

```bash
# Buscar todos los archivos que contienen "PEND-" y uuid
find /var/www/vitalmix.com.co/app/src -name "*.py" -exec grep -l "PEND-.*uuid" {} \;

# Verificar si hay archivos .pyc compilados con código antiguo
find /var/www/vitalmix.com.co/app/src -name "*.pyc" -exec strings {} \; | grep -i "pend-.*uuid" | head -5

# Verificar si hay archivos .pyc en __pycache__
find /var/www/vitalmix.com.co/app/src -path "*/__pycache__/*.pyc" -exec ls -lh {} \;
```

## 9. Reinicio completo del servicio

```bash
# Detener completamente el servicio
systemctl stop binabot-loop.service

# Esperar a que termine
sleep 2

# Verificar que no hay procesos colgados
ps aux | grep ejecutar_bot | grep -v grep

# Matar procesos si los hay
pkill -f "ejecutar_bot" || true

# Limpiar TODO
find /var/www/vitalmix.com.co/app/src -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find /var/www/vitalmix.com.co/app/src -name "*.pyc" -delete

# Reiniciar
systemctl start binabot-loop.service

# Ver logs en tiempo real
journalctl -u binabot-loop.service -f --no-pager
```

## 10. Verificar el archivo de servicio systemd

```bash
# Ver la configuración completa del servicio
cat /etc/systemd/system/binabot-loop.service

# Verificar el WorkingDirectory y el comando exacto
systemctl show binabot-loop.service | grep -E "(WorkingDirectory|ExecStart)"
```


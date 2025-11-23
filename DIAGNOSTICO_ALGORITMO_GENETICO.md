# Diagnóstico y Corrección del Algoritmo Genético

## Problema Reportado
El algoritmo genético no se inicia desde la plantilla. No se ve nada, no se inicia nada.

## Cambios Realizados

### 1. Mejoras en el Manejo de Errores (`ai_trading/services_entrenamiento.py`)
- ✅ **Búsqueda mejorada de `manage.py`**: Ahora busca en múltiples ubicaciones y valida que exista
- ✅ **Manejo separado de stdout y stderr**: Captura errores por separado para mejor diagnóstico
- ✅ **Logging detallado**: Registra la ruta de `manage.py`, directorio de trabajo, y ejecutable de Python
- ✅ **Mensajes de error más descriptivos**: Incluye detalles del error y código de salida
- ✅ **Validación de archivos**: Verifica que `manage.py` exista antes de ejecutar

### 2. Mejoras en la Vista (`ai_trading/views.py`)
- ✅ **Logging detallado**: Registra todos los parámetros recibidos y el resultado
- ✅ **Manejo de excepciones mejorado**: Captura y registra errores con stack trace
- ✅ **Respuestas más informativas**: Incluye detalles del error en la respuesta

### 3. Mejoras en el Frontend (`static/js/ai_trading/dashboard.js`)
- ✅ **Feedback visual**: El botón muestra "⏳ Iniciando..." mientras procesa
- ✅ **Logging en consola**: Registra todos los pasos para facilitar el debugging
- ✅ **Manejo de errores mejorado**: Muestra mensajes de error más descriptivos
- ✅ **Actualización de UI**: Actualiza el estado visual inmediatamente

## Cómo Diagnosticar Problemas

### 1. Verificar Logs del Servidor
```bash
# Ver logs de Django
tail -f /var/log/django.log

# O si usas systemd
sudo journalctl -u binabot.service -f
```

### 2. Verificar en la Consola del Navegador
1. Abre las herramientas de desarrollador (F12)
2. Ve a la pestaña "Console"
3. Intenta iniciar el entrenamiento
4. Revisa los mensajes de log que empiezan con:
   - `Iniciando entrenamiento con datos:`
   - `Respuesta del servidor:`
   - `Resultado:`
   - `✅` o `❌` para éxito/error

### 3. Verificar que el Comando Existe
```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
python manage.py entrenar_ia --help
```

### 4. Probar el Comando Manualmente
```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
python manage.py entrenar_ia \
  --generaciones 5 \
  --poblacion 10 \
  --mutacion 0.10 \
  --crossover 0.80 \
  --elite 2 \
  --dias-datos 1 \
  --nombre "Test_Manual"
```

### 5. Verificar Permisos
```bash
# Verificar que manage.py es ejecutable
ls -la /var/www/vitalmix.com.co/app/src/manage.py

# Verificar permisos del directorio
ls -la /var/www/vitalmix.com.co/app/src/
```

## Posibles Problemas y Soluciones

### Problema 1: "No se encontró manage.py"
**Solución**: Verificar la estructura de directorios y ajustar la búsqueda en `services_entrenamiento.py`

### Problema 2: "Error al iniciar entrenamiento: [error]"
**Solución**: 
1. Revisar los logs del servidor
2. Verificar que todas las dependencias estén instaladas
3. Verificar que la base de datos esté accesible

### Problema 3: El proceso se inicia pero no se ve progreso
**Solución**:
1. Verificar que el WebSocket esté conectado (ver consola del navegador)
2. Verificar que el consumer de WebSocket esté funcionando
3. Revisar los logs para ver si hay errores en el proceso

### Problema 4: Error de permisos
**Solución**:
```bash
# Asegurar que el usuario del servidor web tenga permisos
sudo chown -R www-data:www-data /var/www/vitalmix.com.co/app/
sudo chmod +x /var/www/vitalmix.com.co/app/src/manage.py
```

## Próximos Pasos

1. **Probar el inicio del entrenamiento** desde la plantilla
2. **Revisar la consola del navegador** para ver los logs
3. **Revisar los logs del servidor** si hay errores
4. **Verificar que el WebSocket esté conectado** (debería aparecer "Conectado al entrenamiento de IA en tiempo real" en la consola)

## Comandos Útiles

```bash
# Verificar estado del entrenamiento en la BD
python manage.py shell -c "
from ai_trading.models import EntrenamientoIA
ultimo = EntrenamientoIA.objects.order_by('-iniciada').first()
if ultimo:
    print(f'Último entrenamiento: {ultimo.nombre}')
    print(f'Estado: {ultimo.estado}')
    print(f'Iniciado: {ultimo.iniciada}')
    print(f'Finalizado: {ultimo.finalizada}')
else:
    print('No hay entrenamientos registrados')
"

# Ver procesos de Python relacionados con entrenamiento
ps aux | grep entrenar_ia

# Ver logs en tiempo real
tail -f /var/log/django.log | grep -i entrenamiento
```


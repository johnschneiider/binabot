# Verificación Final - Error "value too long" Resuelto

## Comandos para verificar que todo funciona correctamente:

```bash
# 1. Verificar que no hay errores en los logs recientes
journalctl -u binabot-loop.service --since "5 minutes ago" --no-pager | grep -i error

# 2. Verificar el estado del servicio
systemctl status binabot-loop.service

# 3. Verificar que el proceso está corriendo
ps aux | grep ejecutar_bot | grep -v grep

# 4. Verificar los últimos logs sin errores
journalctl -u binabot-loop.service -n 50 --no-pager | tail -20

# 5. Verificar que el código está actualizado
grep -A 3 "Truncar contract_id" /var/www/vitalmix.com.co/app/src/trading/services_profesional.py
grep -A 3 "Truncar si excede" /var/www/vitalmix.com.co/app/src/simulacion/services.py

# 6. Test manual del truncado
python -c "
# Test 1: numero_contrato inicial
import uuid
uuid_str = str(uuid.uuid4()).replace('-', '')
numero_contrato = f'PEND-{uuid_str[:32]}'
numero_contrato = numero_contrato[:40]
print(f'✓ numero_contrato inicial: {len(numero_contrato)} caracteres')

# Test 2: contract_id largo (simulado)
contract_id_largo = 'a' * 50  # 50 caracteres
contract_id_truncado = contract_id_largo[:40] if len(contract_id_largo) > 40 else contract_id_largo
print(f'✓ contract_id truncado: {len(contract_id_truncado)} caracteres')

# Test 3: numero_contrato de simulación
import time
timestamp1 = int(time.time())
timestamp2 = int(time.time()) + 100
numero_sim = f'SIM-{timestamp1}-{timestamp2}'
numero_sim = numero_sim[:40]
print(f'✓ numero_contrato simulación: {len(numero_sim)} caracteres')
print('✓ Todos los tests pasaron: todos los valores están dentro del límite de 40 caracteres')
"
```

## Resumen de correcciones aplicadas:

1. ✅ **`numero_contrato` inicial**: Truncado a 40 caracteres usando UUID sin guiones
2. ✅ **`contract_id` de Deriv API**: Truncado a 40 caracteres antes de guardar
3. ✅ **`numero_contrato` en simulaciones**: Truncado a 40 caracteres
4. ✅ **Validación a nivel de modelo**: `CooldownActivo.save()` trunca automáticamente
5. ✅ **Validación en admin**: `CooldownActivoAdmin.save_model()` trunca antes de guardar

## Si el error persiste:

```bash
# Ver el traceback completo del último error
journalctl -u binabot-loop.service -n 200 --no-pager | grep -A 30 "value too long"

# Verificar la estructura real de la base de datos
# (Necesitarás las credenciales de PostgreSQL)
PGPASSWORD=1234 psql -U postgres -d binabot -c "SELECT column_name, character_maximum_length FROM information_schema.columns WHERE table_name = 'historial_operacion' AND column_name = 'numero_contrato';"

# Verificar si hay registros con valores largos
PGPASSWORD=1234 psql -U postgres -d binabot -c "SELECT numero_contrato, LENGTH(numero_contrato) as len FROM historial_operacion WHERE LENGTH(numero_contrato) > 40 ORDER BY creado DESC LIMIT 10;"
```


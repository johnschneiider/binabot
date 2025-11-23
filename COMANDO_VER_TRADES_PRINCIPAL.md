# Comando para Ver Trades Históricos del Bot Principal

## Comando Básico

```bash
# Ver últimas 20 operaciones del bot principal
python manage.py shell -c '
from historial.models import Operacion
ops = Operacion.objetos.reales().order_by("-hora_inicio")
print(f"Total operaciones: {ops.count()}")
print("\nÚltimas 20 operaciones:")
for op in ops[:20]:
    print(f"{op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado} | ${op.beneficio}")
'
```

## Comando con Estadísticas

```bash
# Ver estadísticas completas del bot principal
python manage.py estadisticas_bot --periodo 24
```

## Comando Detallado

```bash
# Ver operaciones con detalles completos
python manage.py shell -c '
from historial.models import Operacion
from django.utils import timezone
from datetime import timedelta

ops = Operacion.objetos.reales().order_by("-hora_inicio")
print(f"Total: {ops.count()}")
print(f"Ganadas: {ops.filter(resultado="win").count()}")
print(f"Perdidas: {ops.filter(resultado="loss").count()}")

print("\nÚltimas 10 operaciones:")
for op in ops[:10]:
    print(f"\n{op.hora_inicio}")
    print(f"  Contrato: {op.numero_contrato}")
    print(f"  Activo: {op.activo} | Dirección: {op.direccion}")
    print(f"  Resultado: {op.resultado} | Beneficio: ${op.beneficio}")
    print(f"  Monto: ${op.monto_invertido}")
'
```

## Ver Operaciones de Hoy

```bash
python manage.py shell -c '
from historial.models import Operacion
from django.utils import timezone

hoy = timezone.now().date()
ops_hoy = Operacion.objetos.reales().filter(hora_inicio__date=hoy)
print(f"Operaciones de hoy ({hoy}): {ops_hoy.count()}")
for op in ops_hoy:
    print(f"{op.hora_inicio.time()} | {op.activo} {op.direccion} | {op.resultado} | ${op.beneficio}")
'
```


# Comandos para Verificar el Bot Inverso

## Ver Historial de Operaciones del Bot Inverso

### 1. Ver Todas las Operaciones Inversas

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa
ops = OperacionInversa.objetos.reales().order_by("-hora_inicio")
print(f"Total operaciones inversas: {ops.count()}")
print("\nÚltimas 20 operaciones:")
for op in ops[:20]:
    print(f"{op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado} | ${op.beneficio} | Principal: {op.operacion_principal_id}")
'
```

### 2. Ver Operaciones con Detalles Completos

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa
from django.utils import timezone

ops = OperacionInversa.objetos.reales().order_by("-hora_inicio")
print(f"Total: {ops.count()}")
print(f"Ganadas: {ops.filter(resultado="win").count()}")
print(f"Perdidas: {ops.filter(resultado="loss").count()}")
print("\nDetalles:")
for op in ops[:10]:
    print(f"\nID: {op.id}")
    print(f"  Contrato: {op.numero_contrato}")
    print(f"  Activo: {op.activo}")
    print(f"  Dirección: {op.direccion}")
    print(f"  Resultado: {op.resultado}")
    print(f"  Beneficio: ${op.beneficio}")
    print(f"  Hora inicio: {op.hora_inicio}")
    print(f"  Hora fin: {op.hora_fin}")
    print(f"  Op. Principal ID: {op.operacion_principal_id}")
    print(f"  Es simulada: {op.es_simulada}")
'
```

### 3. Verificar si Hay Operaciones Antiguas (Anómalas)

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa
from django.utils import timezone
from datetime import timedelta

hoy = timezone.now().date()
ayer = hoy - timedelta(days=1)

ops_ayer = OperacionInversa.objetos.reales().filter(hora_inicio__date=ayer)
ops_hoy = OperacionInversa.objetos.reales().filter(hora_inicio__date=hoy)

print(f"Operaciones de ayer ({ayer}): {ops_ayer.count()}")
print(f"Operaciones de hoy ({hoy}): {ops_hoy.count()}")

if ops_ayer.exists():
    print("\n⚠️ OPERACIONES DE AYER ENCONTRADAS:")
    for op in ops_ayer:
        print(f"  {op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado} | ID: {op.id}")
'
```

### 4. Verificar Fechas de Creación de las Tablas

```bash
python manage.py shell -c '
from django.db import connection

with connection.cursor() as cursor:
    # Verificar cuando se creó la tabla
    cursor.execute("""
        SELECT 
            table_name,
            table_type
        FROM information_schema.tables 
        WHERE table_schema = current_schema()
        AND table_name LIKE '%inverso%'
        ORDER BY table_name;
    """)
    
    print("Tablas relacionadas con bot inverso:")
    for row in cursor.fetchall():
        print(f"  {row[0]} ({row[1]})")
    
    # Verificar registros más antiguos
    cursor.execute("""
        SELECT 
            MIN(creado) as primera_operacion,
            MAX(creado) as ultima_operacion,
            COUNT(*) as total
        FROM trading_inverso_operacioninversa;
    """)
    
    result = cursor.fetchone()
    if result and result[2] > 0:
        print(f"\nPrimera operación: {result[0]}")
        print(f"Última operación: {result[1]}")
        print(f"Total: {result[2]}")
    else:
        print("\nNo hay operaciones en la tabla")
'
```

### 5. Eliminar Operaciones Anómalas (si es necesario)

```bash
# ⚠️ CUIDADO: Esto elimina operaciones. Solo ejecutar si estás seguro.

python manage.py shell -c '
from trading_inverso.models import OperacionInversa
from django.utils import timezone
from datetime import timedelta

hoy = timezone.now().date()
ayer = hoy - timedelta(days=1)

# Ver qué se va a eliminar
ops_ayer = OperacionInversa.objetos.reales().filter(hora_inicio__date=ayer)
print(f"Operaciones de ayer que se eliminarán: {ops_ayer.count()}")

# Descomentar para eliminar:
# ops_ayer.delete()
# print("✅ Operaciones de ayer eliminadas")
'
```

### 6. Ver Estadísticas del Bot Inverso

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa

ops = OperacionInversa.objetos.reales()
total = ops.count()
ganadas = ops.filter(resultado="win").count()
perdidas = ops.filter(resultado="loss").count()
winrate = (ganadas / total * 100) if total > 0 else 0
beneficio_total = sum(float(op.beneficio) for op in ops)

print("ESTADÍSTICAS BOT INVERSO:")
print("=" * 50)
print(f"Total operaciones: {total}")
print(f"Ganadas: {ganadas}")
print(f"Perdidas: {perdidas}")
print(f"Winrate: {winrate:.2f}%")
print(f"Beneficio total: ${beneficio_total:.2f}")
'
```

### 7. Ver Operaciones por Fecha

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa
from django.utils import timezone
from django.db.models import Count, Q

# Agrupar por fecha
ops = OperacionInversa.objetos.reales()
fechas = {}

for op in ops:
    fecha = op.hora_inicio.date()
    if fecha not in fechas:
        fechas[fecha] = {"total": 0, "ganadas": 0, "perdidas": 0}
    fechas[fecha]["total"] += 1
    if op.resultado == "win":
        fechas[fecha]["ganadas"] += 1
    else:
        fechas[fecha]["perdidas"] += 1

print("OPERACIONES POR FECHA:")
print("=" * 50)
for fecha in sorted(fechas.keys(), reverse=True):
    stats = fechas[fecha]
    winrate = (stats["ganadas"] / stats["total"] * 100) if stats["total"] > 0 else 0
    print(f"{fecha} | {stats['total']} ops | {stats['ganadas']}G/{stats['perdidas']}P | Winrate: {winrate:.1f}%")
'
```

### 8. Verificar Relación con Operaciones del Bot Principal

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa
from historial.models import Operacion

ops_inverso = OperacionInversa.objetos.reales()
print(f"Total operaciones inversas: {ops_inverso.count()}")

# Verificar cuántas tienen referencia al bot principal
con_referencia = ops_inverso.exclude(operacion_principal_id__isnull=True).exclude(operacion_principal_id="")
print(f"Con referencia al bot principal: {con_referencia.count()}")

# Verificar si las referencias son válidas
print("\nVerificando referencias:")
for op in ops_inverso[:10]:
    if op.operacion_principal_id:
        principal = Operacion.objetos.filter(numero_contrato=op.operacion_principal_id).first()
        if principal:
            print(f"✅ {op.numero_contrato} → {op.operacion_principal_id} (válida)")
        else:
            print(f"❌ {op.numero_contrato} → {op.operacion_principal_id} (NO encontrada)")
'
```


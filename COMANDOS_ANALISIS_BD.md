# Comandos para Análisis de Base de Datos

Ejecuta estos comandos y comparte los resultados para mejorar el desempeño del bot.

---

## 1. Análisis de Activos por Winrate

```bash
python manage.py shell -c "
from historial.models import Operacion
from django.db.models import Count, Q, Sum
from decimal import Decimal

activos = Operacion.objetos.reales().values('activo').annotate(
    total=Count('id'),
    ganadas=Count('id', filter=Q(resultado='win')),
    perdidas=Count('id', filter=Q(resultado='loss')),
    beneficio=Sum('beneficio')
).order_by('-ganadas')

print('ACTIVOS POR WINRATE (Top 20):')
print('=' * 80)
for a in activos[:20]:
    total = a['total']
    ganadas = a['ganadas']
    winrate = (ganadas / total * 100) if total > 0 else 0
    beneficio = a['beneficio'] or Decimal('0')
    print(f\"{a['activo']:15} | {total:3} ops | {ganadas:2}G/{a['perdidas']:2}P | Winrate: {winrate:5.1f}% | Beneficio: \${beneficio:7.2f}\")
"
```

---

## 2. Análisis de Horarios (¿Qué horas funcionan mejor?)

```bash
python manage.py shell -c "
from historial.models import Operacion
from django.db.models import Count, Q, Sum
from django.utils import timezone

operaciones = Operacion.objetos.reales()
horas_stats = {}

for op in operaciones:
    hora = timezone.localtime(op.hora_inicio).hour
    if hora not in horas_stats:
        horas_stats[hora]] = {'total': 0, 'ganadas': 0, 'perdidas': 0, 'beneficio': 0}
    
    horas_stats[hora]['total'] += 1
    if op.resultado == 'win':
        horas_stats[hora]['ganadas'] += 1
    else:
        horas_stats[hora]['perdidas'] += 1
    horas_stats[hora]['beneficio'] += float(op.beneficio)

print('ANÁLISIS POR HORA DEL DÍA:')
print('=' * 80)
for hora in sorted(horas_stats.keys()):
    stats = horas_stats[hora]
    total = stats['total']
    ganadas = stats['ganadas']
    winrate = (ganadas / total * 100) if total > 0 else 0
    print(f\"{hora:2}:00 | {total:3} ops | {ganadas:2}G/{stats['perdidas']:2}P | Winrate: {winrate:5.1f}% | Beneficio: \${stats['beneficio']:7.2f}\")
"
```

---

## 3. Análisis CALL vs PUT por Activo

```bash
python manage.py shell -c "
from historial.models import Operacion
from django.db.models import Count, Q

activos = Operacion.objetos.reales().values('activo').distinct()

print('CALL vs PUT POR ACTIVO (Top 15):')
print('=' * 80)

for activo_data in activos[:15]:
    activo = activo_data['activo']
    ops = Operacion.objetos.reales().filter(activo=activo)
    
    call_ops = ops.filter(direccion='CALL')
    put_ops = ops.filter(direccion='PUT')
    
    call_total = call_ops.count()
    call_ganadas = call_ops.filter(resultado='win').count()
    call_winrate = (call_ganadas / call_total * 100) if call_total > 0 else 0
    
    put_total = put_ops.count()
    put_ganadas = put_ops.filter(resultado='win').count()
    put_winrate = (put_ganadas / put_total * 100) if put_total > 0 else 0
    
    if call_total > 0 or put_total > 0:
        print(f\"{activo:15} | CALL: {call_ganadas}/{call_total} ({call_winrate:.1f}%) | PUT: {put_ganadas}/{put_total} ({put_winrate:.1f}%)\")
"
```

---

## 4. Análisis de Momentum vs Resultado

```bash
python manage.py shell -c "
from historial.models import Operacion
from trading.models import IndicadoresActivo
from core.models import ActivoPermitido

print('MOMENTUM VS RESULTADO (Últimas 50 operaciones):')
print('=' * 80)

ops = Operacion.objetos.reales().order_by('-hora_inicio')[:50]

momentum_ganadas = []
momentum_perdidas = []

for op in ops:
    try:
        activo = ActivoPermitido.objects.get(nombre=op.activo)
        indicadores = IndicadoresActivo.objects.filter(activo=activo).order_by('-id').first()
        
        if indicadores and indicadores.momentum_pct:
            momentum = float(indicadores.momentum_pct)
            if op.resultado == 'win':
                momentum_ganadas.append(momentum)
            else:
                momentum_perdidas.append(momentum)
    except:
        pass

if momentum_ganadas:
    avg_ganadas = sum(momentum_ganadas) / len(momentum_ganadas)
    print(f\"Momentum promedio en GANADAS: {avg_ganadas:.4f}% ({len(momentum_ganadas)} ops)\")
    
if momentum_perdidas:
    avg_perdidas = sum(momentum_perdidas) / len(momentum_perdidas)
    print(f\"Momentum promedio en PERDIDAS: {avg_perdidas:.4f}% ({len(momentum_perdidas)} ops)\")
    
if momentum_ganadas and momentum_perdidas:
    diferencia = avg_ganadas - avg_perdidas
    print(f\"Diferencia: {diferencia:.4f}% (ganadas tienen {'más' if diferencia > 0 else 'menos'} momentum)\")
"
```

---

## 5. Análisis de Volatilidad vs Resultado

```bash
python manage.py shell -c "
from historial.models import Operacion
from trading.models import IndicadoresActivo
from core.models import ActivoPermitido

print('VOLATILIDAD VS RESULTADO:')
print('=' * 80)

ops = Operacion.objetos.reales().order_by('-hora_inicio')[:50]

vol_ganadas = []
vol_perdidas = []

for op in ops:
    try:
        activo = ActivoPermitido.objects.get(nombre=op.activo)
        indicadores = IndicadoresActivo.objects.filter(activo=activo).order_by('-id').first()
        
        if indicadores and indicadores.volatilidad:
            vol = float(indicadores.volatilidad)
            if op.resultado == 'win':
                vol_ganadas.append(vol)
            else:
                vol_perdidas.append(vol)
    except:
        pass

if vol_ganadas:
    avg_ganadas = sum(vol_ganadas) / len(vol_ganadas)
    print(f\"Volatilidad promedio en GANADAS: {avg_ganadas:.6f} ({len(vol_ganadas)} ops)\")
    
if vol_perdidas:
    avg_perdidas = sum(vol_perdidas) / len(vol_perdidas)
    print(f\"Volatilidad promedio en PERDIDAS: {avg_perdidas:.6f} ({len(vol_perdidas)} ops)\")
"
```

---

## 6. Análisis de Secuencias (Rachas)

```bash
python manage.py shell -c "
from historial.models import Operacion

ops = list(Operacion.objetos.reales().order_by('hora_inicio'))

print('ANÁLISIS DE RACHAS (Secuencias de ganadas/perdidas):')
print('=' * 80)

racha_actual = 1
ultimo_resultado = None
rachas_ganadas = []
rachas_perdidas = []

for op in ops:
    resultado = op.resultado
    
    if ultimo_resultado is None:
        ultimo_resultado = resultado
        continue
    
    if resultado == ultimo_resultado:
        racha_actual += 1
    else:
        if ultimo_resultado == 'win':
            rachas_ganadas.append(racha_actual)
        else:
            rachas_perdidas.append(racha_actual)
        racha_actual = 1
        ultimo_resultado = resultado

# Última racha
if ultimo_resultado == 'win':
    rachas_ganadas.append(racha_actual)
else:
    rachas_perdidas.append(racha_actual)

if rachas_ganadas:
    print(f\"Rachas de GANADAS: Max={max(rachas_ganadas)}, Promedio={sum(rachas_ganadas)/len(rachas_ganadas):.1f}\")
if rachas_perdidas:
    print(f\"Rachas de PERDIDAS: Max={max(rachas_perdidas)}, Promedio={sum(rachas_perdidas)/len(rachas_perdidas):.1f}\")
"
```

---

## 7. Análisis de Beneficio por Operación

```bash
python manage.py shell -c "
from historial.models import Operacion
from decimal import Decimal

ops = Operacion.objetos.reales()

ganadas = [float(op.beneficio) for op in ops if op.resultado == 'win']
perdidas = [float(op.beneficio) for op in ops if op.resultado == 'loss']

print('ANÁLISIS DE BENEFICIOS:')
print('=' * 80)

if ganadas:
    print(f\"Ganadas: Min=\${min(ganadas):.2f}, Max=\${max(ganadas):.2f}, Promedio=\${sum(ganadas)/len(ganadas):.2f}\")
if perdidas:
    print(f\"Perdidas: Min=\${min(perdidas):.2f}, Max=\${max(perdidas):.2f}, Promedio=\${sum(perdidas)/len(perdidas):.2f}\")

if ganadas and perdidas:
    ratio = abs(sum(ganadas)/len(ganadas) / (sum(perdidas)/len(perdidas)))
    print(f\"Ratio ganancia/pérdida: {ratio:.2f} (debe ser >1 para ser rentable con winrate 50%)\")
"
```

---

## 8. Análisis de Activos con Mejor Winrate (Mínimo 10 operaciones)

```bash
python manage.py shell -c "
from historial.models import Operacion
from django.db.models import Count, Q, Sum

activos = Operacion.objetos.reales().values('activo').annotate(
    total=Count('id'),
    ganadas=Count('id', filter=Q(resultado='win')),
    beneficio=Sum('beneficio')
).filter(total__gte=10).order_by('-ganadas')

print('ACTIVOS CON MEJOR WINRATE (Mínimo 10 operaciones):')
print('=' * 80)
for a in activos:
    total = a['total']
    ganadas = a['ganadas']
    winrate = (ganadas / total * 100) if total > 0 else 0
    beneficio = a['beneficio'] or 0
    print(f\"{a['activo']:15} | {total:3} ops | Winrate: {winrate:5.1f}% | Beneficio: \${beneficio:7.2f}\")
"
```

---

## 9. Análisis de Días de la Semana

```bash
python manage.py shell -c "
from historial.models import Operacion
from django.utils import timezone

ops = Operacion.objetos.reales()
dias_stats = {}

dias_nombres = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

for op in ops:
    dia_num = timezone.localtime(op.hora_inicio).weekday()
    dia = dias_nombres[dia_num]
    
    if dia not in dias_stats:
        dias_stats[dia] = {'total': 0, 'ganadas': 0, 'perdidas': 0, 'beneficio': 0}
    
    dias_stats[dia]['total'] += 1
    if op.resultado == 'win':
        dias_stats[dia]['ganadas'] += 1
    else:
        dias_stats[dia]['perdidas'] += 1
    dias_stats[dia]['beneficio'] += float(op.beneficio)

print('ANÁLISIS POR DÍA DE LA SEMANA:')
print('=' * 80)
for dia in dias_nombres:
    if dia in dias_stats:
        stats = dias_stats[dia]
        total = stats['total']
        ganadas = stats['ganadas']
        winrate = (ganadas / total * 100) if total > 0 else 0
        print(f\"{dia:12} | {total:3} ops | {ganadas:2}G/{stats['perdidas']:2}P | Winrate: {winrate:5.1f}% | Beneficio: \${stats['beneficio']:7.2f}\")
"
```

---

## 10. Análisis de Score vs Resultado

```bash
python manage.py shell -c "
from historial.models import Operacion
from trading.models import IndicadoresActivo
from core.models import ActivoPermitido

print('SCORE VS RESULTADO:')
print('=' * 80)

ops = Operacion.objetos.reales().order_by('-hora_inicio')[:50]

scores_ganadas = []
scores_perdidas = []

for op in ops:
    try:
        activo = ActivoPermitido.objects.get(nombre=op.activo)
        indicadores = IndicadoresActivo.objects.filter(activo=activo).order_by('-id').first()
        
        if indicadores and indicadores.score_total:
            score = float(indicadores.score_total)
            if op.resultado == 'win':
                scores_ganadas.append(score)
            else:
                scores_perdidas.append(score)
    except:
        pass

if scores_ganadas:
    avg_ganadas = sum(scores_ganadas) / len(scores_ganadas)
    print(f\"Score promedio en GANADAS: {avg_ganadas:.2f} ({len(scores_ganadas)} ops)\")
    
if scores_perdidas:
    avg_perdidas = sum(scores_perdidas) / len(scores_perdidas)
    print(f\"Score promedio en PERDIDAS: {avg_perdidas:.2f} ({len(scores_perdidas)} ops)\")
    
if scores_ganadas and scores_perdidas:
    diferencia = avg_ganadas - avg_perdidas
    print(f\"Diferencia: {diferencia:.2f} (ganadas tienen {'mayor' if diferencia > 0 else 'menor'} score)\")
    print(f\"Umbral actual: 15.00 - Considerar ajustar a {avg_ganadas:.2f} si la diferencia es significativa\")
"
```

---

## 11. Análisis de Tendencias Temporales

```bash
python manage.py shell -c "
from historial.models import Operacion
from django.utils import timezone
from datetime import timedelta

print('TENDENCIA TEMPORAL (Últimas 4 semanas):')
print('=' * 80)

ahora = timezone.now()
semanas = []

for i in range(4):
    inicio = ahora - timedelta(weeks=i+1)
    fin = ahora - timedelta(weeks=i)
    
    ops = Operacion.objetos.reales().filter(hora_inicio__gte=inicio, hora_inicio__lt=fin)
    total = ops.count()
    ganadas = ops.filter(resultado='win').count()
    winrate = (ganadas / total * 100) if total > 0 else 0
    beneficio = sum(float(op.beneficio) for op in ops)
    
    semanas.append({
        'semana': f\"Semana {4-i}\",
        'total': total,
        'ganadas': ganadas,
        'winrate': winrate,
        'beneficio': beneficio
    })

for s in semanas:
    print(f\"{s['semana']:10} | {s['total']:3} ops | {s['ganadas']:2}G | Winrate: {s['winrate']:5.1f}% | Beneficio: \${s['beneficio']:7.2f}\")
"
```

---

## 12. Resumen Ejecutivo

```bash
python manage.py shell -c "
from historial.models import Operacion
from django.db.models import Count, Q, Sum, Avg

ops = Operacion.objetos.reales()

total = ops.count()
ganadas = ops.filter(resultado='win').count()
winrate = (ganadas / total * 100) if total > 0 else 0

call_ops = ops.filter(direccion='CALL')
put_ops = ops.filter(direccion='PUT')

call_winrate = (call_ops.filter(resultado='win').count() / call_ops.count() * 100) if call_ops.count() > 0 else 0
put_winrate = (put_ops.filter(resultado='win').count() / put_ops.count() * 100) if put_ops.count() > 0 else 0

beneficio_total = sum(float(op.beneficio) for op in ops)
beneficio_promedio = beneficio_total / total if total > 0 else 0

print('RESUMEN EJECUTIVO:')
print('=' * 80)
print(f\"Total operaciones: {total}\")
print(f\"Winrate general: {winrate:.2f}%\")
print(f\"Winrate CALL: {call_winrate:.2f}%\")
print(f\"Winrate PUT: {put_winrate:.2f}%\")
print(f\"Beneficio total: \${beneficio_total:.2f}\")
print(f\"Beneficio promedio: \${beneficio_promedio:.2f}\")
print(f\"\")
print(f\"Recomendación: {'✅ Estrategia funcionando' if winrate >= 50 and beneficio_total > 0 else '⚠️ Necesita ajustes'}\")
"
```

---

## Cómo usar estos comandos

1. Copia cada comando completo
2. Ejecútalo en la VPS (con el venv activado)
3. Comparte los resultados
4. Analizaremos los datos para mejorar la estrategia

**Nota**: Algunos comandos pueden tardar si hay muchas operaciones. Empieza con los comandos 1, 2, 8 y 12 que son los más importantes.


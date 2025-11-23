# Análisis: Stop Loss entre Bot Principal y Bot Inverso

## Comando para Ver Trades Históricos del Bot Principal

```bash
# Ver últimas 20 operaciones del bot principal
python manage.py shell -c '
from historial.models import Operacion
ops = Operacion.objetos.reales().order_by("-hora_inicio")
print(f"Total operaciones: {ops.count()}")
print("\nÚltimas 20 operaciones:")
for op in ops[:20]:
    print(f"{op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado} | ${op.beneficio} | Balance después: ${op.balance_despues if hasattr(op, \"balance_despues\") else \"N/A\"}")
'

# O usar el comando de estadísticas
python manage.py estadisticas_bot --periodo 24
```

## Problema Identificado

### Situación Actual

1. **Balance Compartido**: Ambos bots sincronizan desde la misma API de Deriv (`obtener_balance_sync()`)
2. **Stop Loss Independientes**: Cada bot tiene su propio `stop_loss_actual` y `balance_stop_loss_base`
3. **Problema**: Cuando un bot gana, el balance de Deriv sube, afectando el stop loss del otro bot

### Ejemplo del Problema

```
Estado Inicial:
- Balance Deriv: $100.00
- Bot Principal: stop_loss = $98.00 (2%)
- Bot Inverso: stop_loss = $95.00 (5%)

Bot Principal gana $5.00:
- Balance Deriv: $105.00
- Bot Principal: stop_loss = $102.90 (trailing, sube)
- Bot Inverso: sincroniza → balance = $105.00 → stop_loss = $99.75 (trailing, sube)

Bot Inverso ahora tiene stop_loss = $99.75 pero su balance inicial era $100.00
Si el balance baja a $99.00, el bot inverso se pausa aunque nunca perdió desde su balance inicial
```

## Análisis de la Lógica Actual

### Bot Principal (`core/services.py`)

```python
def sincronizar_balance_desde_api(self):
    balance = obtener_balance_sync()  # Balance compartido de Deriv
    
    # Trailing stop loss: solo sube si balance sube
    if estado == OPERANDO:
        nuevo_stop_loss = calcular_stop_loss(balance)  # 98% del balance actual
        if nuevo_stop_loss > stop_loss_actual:
            stop_loss_actual = nuevo_stop_loss  # ✅ Correcto para bot principal
```

### Bot Inverso (`trading_inverso/services.py`)

```python
def sincronizar_balance_desde_api(self):
    balance = obtener_balance_sync()  # Balance compartido de Deriv
    
    # Trailing stop loss: solo sube si balance sube
    if estado == OPERANDO:
        nuevo_stop_loss = calcular_stop_loss(balance)  # 95% del balance actual
        if nuevo_stop_loss > stop_loss_actual:
            stop_loss_actual = nuevo_stop_loss  # ❌ PROBLEMA: usa balance compartido
```

## Solución Propuesta

### Opción 1: Stop Loss Basado en Balance Inicial de Cada Bot (RECOMENDADA)

Cada bot debe calcular su stop loss basado en su propio balance inicial, no en el balance compartido de Deriv.

**Concepto:**
- Bot Principal: stop_loss = 98% de su `balance_stop_loss_base` (balance inicial del bot principal)
- Bot Inverso: stop_loss = 95% de su `balance_stop_loss_base` (balance inicial del bot inverso)

**Ventajas:**
- Stop loss independiente para cada bot
- No se afectan mutuamente
- Cada bot protege su propio capital inicial

**Desventajas:**
- Requiere rastrear el balance inicial de cada bot
- El stop loss no sube con ganancias del otro bot (pero esto es correcto)

### Opción 2: Balance Virtual Separado

Cada bot mantiene un "balance virtual" que solo cambia con sus propias operaciones.

**Concepto:**
- Bot Principal: `balance_virtual = balance_inicial_principal + beneficios_principal`
- Bot Inverso: `balance_virtual = balance_inicial_inverso + beneficios_inverso`
- Stop loss se calcula sobre el balance virtual

**Ventajas:**
- Completamente independiente
- Fácil de entender

**Desventajas:**
- Requiere rastrear operaciones de cada bot
- Más complejo de implementar

### Opción 3: Stop Loss Relativo al Balance Inicial (HÍBRIDA)

Cada bot calcula su stop loss como porcentaje de su balance inicial, pero permite trailing solo con sus propias ganancias.

**Concepto:**
- Bot Principal: `stop_loss = max(98% * balance_inicial_principal, 98% * balance_actual_principal)`
- Bot Inverso: `stop_loss = max(95% * balance_inicial_inverso, 95% * balance_actual_inverso)`
- `balance_actual_X` solo cambia con operaciones del bot X

## Implementación Recomendada (Opción 1)

Modificar la lógica para que cada bot calcule su stop loss basado en su propio `balance_stop_loss_base` en lugar del balance compartido de Deriv.

### Cambios Necesarios

1. **Bot Principal**: Ya está correcto (usa trailing stop loss sobre balance compartido, que es correcto para el bot principal)

2. **Bot Inverso**: Modificar para que el stop loss se base en su propio balance inicial, no en el balance compartido

```python
# En trading_inverso/services.py
def sincronizar_balance_desde_api(self):
    balance_deriv = obtener_balance_sync()  # Balance compartido
    
    # Actualizar balance actual (para mostrar en dashboard)
    self.configuracion.balance_actual = balance_deriv
    
    # PERO: calcular stop loss basado en balance inicial del bot inverso
    # No usar balance_deriv directamente para stop loss
    balance_base = self.configuracion.balance_stop_loss_base
    
    if balance_base <= 0:
        # Primera vez: inicializar con balance actual
        balance_base = balance_deriv
        self.configuracion.balance_stop_loss_base = balance_base
    
    # Stop loss = 95% del balance base (inicial del bot inverso)
    # Solo sube si el balance base sube (con ganancias del bot inverso)
    nuevo_stop_loss = self.configuracion.calcular_stop_loss(balance_base)
    
    # Trailing stop loss: solo sube
    if nuevo_stop_loss > self.configuracion.stop_loss_actual:
        self.configuracion.stop_loss_actual = nuevo_stop_loss
```

**Problema**: Esto requiere que el bot inverso actualice su `balance_stop_loss_base` solo cuando él gana, no cuando el bot principal gana.

## Solución Final: Balance Virtual por Bot

Cada bot debe mantener un balance virtual que solo cambia con sus propias operaciones.

### Implementación

1. **Agregar campo `balance_virtual`** a cada configuración
2. **Actualizar `balance_virtual`** solo cuando el bot correspondiente ejecuta una operación
3. **Calcular stop loss** sobre `balance_virtual` en lugar de `balance_actual`

Esto requiere cambios más profundos en la arquitectura.


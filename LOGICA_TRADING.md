# Lógica de Trading del Bot

Este documento explica cómo el bot decide cuándo y cómo hacer un trade.

## 📋 Resumen Ejecutivo

El bot usa una estrategia simple basada en **análisis de momentum** comparando los últimos 2 ticks de precio. Selecciona el activo con la mayor variación de precio y ejecuta un trade en esa dirección.

---

## 🔄 Flujo Principal

### 1. Loop Principal (`ejecutar_bot.py`)

El bot ejecuta un loop infinito que:

1. **Sincroniza el balance** desde la API de Deriv
2. **Verifica si debe reanudar** (si está pausado)
3. **Evalúa el estado actual**:
   - Si está `OPERANDO` → ejecuta un ciclo de trading
   - Si está `PAUSADO` → ejecuta simulaciones para encontrar el mejor horario
4. **Espera** el intervalo configurado (por defecto: 60 segundos)

```python
while True:
    sincronizar_balance()
    if debe_reanudar():
        reanudar_operativa()
    
    if estado == OPERANDO:
        ejecutar_ciclo()  # Aquí se decide hacer un trade
    else:
        ejecutar_simulacion_pausa()
    
    sleep(intervalo)
```

---

## 🎯 Lógica de Decisión de Trading

### 2. Condiciones Previas (`ejecutar_ciclo()`)

Antes de considerar hacer un trade, el bot verifica:

✅ **Estado del bot**: Debe estar `OPERANDO` y no tener una operación en curso
```python
if config.estado != Estado.OPERANDO or config.en_operacion:
    return None  # No opera
```

✅ **Balance y objetivos válidos**: 
```python
if config.stop_loss_actual <= 0 or config.meta_actual <= 0:
    return None  # No opera
```

✅ **Activos disponibles**: Debe haber al menos un activo habilitado
```python
activos = ActivoPermitido.objects.filter(habilitado=True)
if not activos:
    return None  # No opera
```

---

## 📊 Generación de Señales (`generar_senal()`)

### 3. Análisis de Momentum Simple

Para cada activo habilitado, el bot:

1. **Obtiene los últimos 2 ticks** de precio desde la API de Deriv
   ```python
   respuesta = obtener_ticks_history_sync(activo, count=2)
   precios = respuesta["history"]["prices"]
   ```

2. **Compara los precios**:
   ```python
   anterior = precios[-2]  # Penúltimo tick
   actual = precios[-1]    # Último tick
   ```

3. **Calcula la variación porcentual**:
   ```python
   variacion = abs(actual - anterior) / anterior * 100
   ```

4. **Determina la dirección**:
   - Si `actual > anterior` → Señal **CALL** (subida)
   - Si `actual < anterior` → Señal **PUT** (bajada)
   - Si `actual == anterior` → **No hay señal** (sin variación)

5. **Calcula la confianza**:
   ```python
   confianza = min(variacion, 99.99)  # Máximo 99.99%
   ```

### Ejemplo de Señal

```
Activo: R_100
Tick anterior: 100.50
Tick actual: 100.75
Variación: 0.25% (subida)
Dirección: CALL
Confianza: 0.25%
```

---

## 🏆 Selección del Mejor Activo

### 4. Comparación de Señales

El bot evalúa **todos los activos habilitados** y selecciona el que tenga:

1. **Mayor variación de precio** (mayor momentum)
2. **Ordenados por winrate de simulación** (si hay empate)

```python
mejor_activo = None
mejor_senal = None

for activo in activos:  # Ordenados por winrate_simulacion
    senal = generar_senal(activo.nombre)
    if senal and senal["variacion"] > mejor_senal["variacion"]:
        mejor_activo = activo
        mejor_senal = senal
```

**Ejemplo:**
```
Activo A: variación 0.15% → CALL
Activo B: variación 0.30% → PUT  ← SELECCIONADO (mayor variación)
Activo C: variación 0.10% → CALL
```

---

## 💰 Ejecución del Trade

### 5. Parámetros del Contrato

Una vez seleccionado el mejor activo y señal:

- **Monto**: Calculado dinámicamente basado en el balance actual
  ```python
  monto_trade = gestor.obtener_monto_trade()
  # Usualmente: 1% del balance actual
  ```

- **Duración**: **5 ticks** (fija)
  ```python
  duracion = 5
  unidad_duracion = "t"  # ticks
  ```

- **Tipo de contrato**: CALL o PUT (según la señal)
  ```python
  contract_type = "CALL" if direccion == CALL else "PUT"
  ```

### 6. Ejecución en Deriv

```python
respuesta = operar_contrato_sync(
    symbol=mejor_activo.nombre,
    amount=float(monto_trade),
    duration=5,
    duration_unit="t",
    contract_type="CALL" o "PUT"
)
```

El bot espera el resultado del contrato (ganado/perdido) y actualiza el balance.

---

## ⏸️ Sistema de Pausas

### 7. Cuándo se Pausa el Bot

El bot se pausa automáticamente cuando:

1. **Stop Loss alcanzado**:
   ```python
   if perdida_acumulada >= stop_loss_actual:
       pausar()
   ```

2. **Meta alcanzada** (configurable)

### 8. Cuándo se Reanuda

El bot se reanuda automáticamente cuando:

1. **Ha pasado el tiempo de pausa** (`pausa_finaliza`)
2. **Es el mejor horario** (si hay simulación):
   ```python
   if hora_actual >= mejor_horario:
       reanudar()
   ```

Durante la pausa, el bot ejecuta **simulaciones** para encontrar el mejor horario de trading basado en datos históricos.

---

## 📈 Características Clave

### Ventajas de esta Estrategia

✅ **Simple y rápida**: Solo necesita 2 ticks para decidir
✅ **Baja latencia**: Respuesta inmediata a cambios de precio
✅ **Multi-activo**: Evalúa todos los activos disponibles
✅ **Selección inteligente**: Elige el activo con mayor momentum

### Limitaciones

⚠️ **Muy simple**: Solo usa 2 ticks (puede ser ruidoso)
⚠️ **Sin filtros**: No considera volatilidad, tendencias, etc.
⚠️ **Duración fija**: Siempre 5 ticks (no adaptativo)
⚠️ **Sin gestión de riesgo avanzada**: Solo stop loss básico

---

## 🔧 Parámetros Configurables

- **Intervalo de ciclo**: Tiempo entre evaluaciones (default: 60s)
- **Duración del contrato**: Fija en 5 ticks
- **Monto por trade**: Calculado como % del balance
- **Stop Loss**: Basado en pérdida acumulada
- **Meta diaria**: Basada en ganancia acumulada

---

## 📝 Flujo Completo Resumido

```
1. Loop cada 60 segundos
   ↓
2. Sincronizar balance desde API
   ↓
3. ¿Está pausado? → Simular y esperar
   ↓
4. ¿Está operando? → Continuar
   ↓
5. Obtener todos los activos habilitados
   ↓
6. Para cada activo:
   - Obtener últimos 2 ticks
   - Calcular variación %
   - Determinar dirección (CALL/PUT)
   ↓
7. Seleccionar activo con MAYOR variación
   ↓
8. Calcular monto del trade
   ↓
9. Ejecutar contrato en Deriv (5 ticks)
   ↓
10. Esperar resultado y actualizar balance
   ↓
11. Verificar stop loss / meta
   ↓
12. Volver al paso 1
```

---

## 💡 Mejoras Potenciales

1. **Más ticks para análisis**: Usar 5-10 ticks en lugar de 2
2. **Filtros de volatilidad**: Solo operar si la variación supera un umbral mínimo
3. **Análisis de tendencia**: Considerar la dirección de los últimos N ticks
4. **Gestión de riesgo adaptativa**: Ajustar monto según volatilidad
5. **Filtros de horario**: Evitar operar en horarios de baja liquidez
6. **Indicadores técnicos**: RSI, MACD, medias móviles, etc.

---

## 📚 Archivos Clave

- `core/management/commands/ejecutar_bot.py` - Loop principal
- `trading/services.py` - Lógica de trading (`MotorTrading`)
- `core/services.py` - Gestión de estado y balance (`GestorBotCore`)
- `core/models.py` - Modelos de configuración y activos


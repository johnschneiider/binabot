# Motor de Trading Profesional

## 🎯 Resumen

Se ha implementado un motor de trading profesional que reemplaza el sistema simple basado en 2 ticks por un análisis robusto multi-activo con indicadores técnicos avanzados.

## ✨ Características Principales

### 1. Análisis Multi-Activo
- Evalúa **88 activos simultáneamente**
- Usa **10-20 ticks** por activo (en lugar de solo 2)
- Cache optimizado en PostgreSQL para consultas rápidas

### 2. Indicadores Técnicos Profesionales
- **Momentum**: Simple y porcentual
- **Volatilidad**: Desviación estándar
- **EMA(10)**: Media móvil exponencial
- **Rate of Change**: Pendiente de regresión lineal
- **Fuerza de movimiento**: |EMA - precio actual|
- **Consistencia**: Porcentaje de ticks en la misma dirección

### 3. Sistema de Scoring
Score combinado (0-100) con pesos:
- Momentum: 30%
- ROC: 20%
- Tendencia EMA: 20%
- Volatilidad: 10%
- Consistencia: 10%
- Historial winrate: 10%

### 4. Gestión de Riesgo Dinámica
- **Monto adaptativo** según volatilidad
- **Cooldown automático** para activos problemáticos
- **Límites por activo** para evitar sobre-operación
- **Detección de micro-congestión**

### 5. Optimización por Horario
- **Winrate por franja horaria**
- **Confianza horaria** basada en historial
- **Ranking de mejores horarios** por activo

## 📁 Estructura de Módulos

```
trading/
├── models.py                    # Nuevos modelos (TickCache, IndicadoresActivo, etc.)
├── services.py                  # Motor original (simple)
├── services_profesional.py      # Motor profesional (nuevo)
├── signals/                     # Cálculo de indicadores
│   ├── __init__.py
│   └── calculadores.py
├── ranking/                     # Sistema de scoring
│   ├── __init__.py
│   └── scorer.py
├── risk/                        # Gestión de riesgo
│   ├── __init__.py
│   └── gestor_riesgo.py
├── database/                    # Interacción con PostgreSQL
│   ├── __init__.py
│   └── cache_manager.py
└── scheduler/                   # Optimización por horario
    ├── __init__.py
    └── horario_manager.py
```

## 🗄️ Nuevos Modelos de Base de Datos

### TickCache
Cache de los últimos 20 ticks por activo para análisis rápido.

### IndicadoresActivo
Almacena todos los indicadores técnicos calculados por activo.

### RendimientoActivo
Rendimiento histórico y dinámico por activo y franja horaria.

### CooldownActivo
Control de cooldown para activos que generan señales contradictorias.

## 🚀 Cómo Usar

### Opción 1: Usar Motor Profesional (Recomendado)

Modificar `core/management/commands/ejecutar_bot.py`:

```python
from trading.services_profesional import MotorTradingProfesional

# En lugar de:
# motor = MotorTrading()

# Usar:
motor = MotorTradingProfesional()
```

### Opción 2: Mantener Motor Simple

El motor original (`MotorTrading`) sigue disponible en `trading/services.py`.

## 📊 Flujo del Motor Profesional

1. **Actualizar cache de ticks** para todos los activos
2. **Calcular indicadores** técnicos (momentum, volatilidad, EMA, etc.)
3. **Calcular score** para cada activo
4. **Filtrar por umbrales**:
   - Score mínimo: 40
   - Consistencia mínima: 30%
   - Volatilidad mínima: 0.001
   - Confianza horaria: 45%
5. **Seleccionar Top 1** por score
6. **Verificar cooldown y límites**
7. **Calcular monto adaptativo** según volatilidad
8. **Ejecutar trade**
9. **Actualizar rendimiento horario**

## ⚙️ Configuración

Los umbrales se pueden ajustar en `MotorTradingProfesional.__init__()`:

```python
self.umbral_score_minimo = Decimal("40.00")
self.umbral_consistencia = Decimal("30.00")
self.umbral_volatilidad_minima = Decimal("0.001")
self.umbral_confianza_horaria = Decimal("45.00")
```

## 🔄 Migración

1. **Aplicar migraciones**:
```bash
python manage.py migrate trading
```

2. **Actualizar comando ejecutar_bot** para usar `MotorTradingProfesional`

3. **Reiniciar servicios**:
```bash
systemctl restart binabot-loop.service
```

## 📈 Ventajas sobre el Sistema Anterior

✅ **Más robusto**: Usa 10-20 ticks en lugar de 2
✅ **Más predecible**: Múltiples indicadores técnicos
✅ **Menos ruidoso**: Filtros de volatilidad y consistencia
✅ **Altamente escalable**: Optimizado para 88 activos
✅ **Selección inteligente**: Score combinado de múltiples factores
✅ **Gestión profesional de riesgo**: Monto adaptativo y cooldowns
✅ **Optimización horaria**: Aprende de patrones históricos

## 🔍 Monitoreo

Los indicadores y scores se almacenan en la base de datos y se pueden consultar:

```python
from trading.models import IndicadoresActivo

# Ver top 10 activos por score
top_activos = IndicadoresActivo.objects.order_by('-score_total')[:10]
for ind in top_activos:
    print(f"{ind.activo.nombre}: Score {ind.score_total}")
```

## 🛠️ Mejoras Futuras

- [ ] Backtesting con datos históricos
- [ ] Machine Learning para optimizar pesos
- [ ] Alertas de señales fuertes
- [ ] Dashboard de indicadores en tiempo real
- [ ] Optimización automática de umbrales


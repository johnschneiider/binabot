# Estrategia Binance Bot

## Descripción General

El bot de Binance utiliza una estrategia de **EMA Crossover** con filtro **RSI** para operar en criptomonedas con timeframe de 120 segundos.

## Activos

- BTC (Bitcoin)
- ETH (Ethereum)
- SOL (Solana)
- XRP (Ripple)

## Configuración

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| STAKE | $1.0 | Monto por operación |
| PAYOUT | 0.95 | Retorno por operación ganadora |
| DURACION_SEGUNDOS | 120 | Duración de cada operación |
| COOLDOWN_TICKS | 10-15 | Espera entre operaciones (ticks) |
| EMA_GAP_MIN | 0.2% | Mínima separación EMA |
| ADX_MIN | 20.0 | Mínimo ADX para tendencia |
| RSI_MIN | 30.0 | Mínimo RSI |
| RSI_MAX | 70.0 | Máximo RSI |

## Indicadores Técnicos

### 1. EMA (Exponential Moving Average)

Se utilizan tres EMAs:
- **EMA Rápida**: 8 periodos
- **EMA Media**: 21 periodos  
- **EMA Lenta**: 55 periodos

**Cálculo:**
```
EMA = (α * precio_actual) + ((1 - α) * EMA_anterior)
donde α = 2 / (periodo + 1)
```

### 2. RSI (Relative Strength Index)

- **Período**: 14 velas
- **Rango**: 0-100
- **Zona sobrecompra**: >70
- **Zona sobreventa**: <30

**Cálculo:**
```
RSI = 100 - (100 / (1 + RS))
donde RS = Ganancia_promedio / Pérdida_promedio
```

### 3. Bollinger Bands (calculado pero no usado en señal principal)

- **Período**: 20
- **Desviación estándar**: 2.0

### 4. ADX (Average Directional Index)

- **Período**: 14
- Mide la fuerza de la tendencia

## Lógica de Entrada

### Condiciones para CALL (Compra)

1. **EMA Crossover Alcista**: EMA Rápida > EMA Media
2. **RSI**: < 65 (no sobrecomprado)
3. **Cooldown**: Debe haber transcurrido el cooldown

### Condiciones para PUT (Venta)

1. **EMA Crossover Bajista**: EMA Rápida < EMA Media
2. **RSI**: > 35 (no sobrevendido)
3. **Cooldown**: Debe haber transcurrido el cooldown

## Flujo de la Estrategia

```
1. Recibir nuevo precio
2. Actualizar lista de precios (máximo 300)
3. Verificar cooldown (si > 0, retornar NEUTRAL)
4. Verificar datos suficientes (mínimo 50 precios)
5. Calcular EMAs (8, 21, 55)
6. Calcular RSI (14 periodos)
7. Evaluar condiciones:
   - Si EMA_rapida > EMA_media AND RSI < 65 → CALL
   - Si EMA_rapida < EMA_media AND RSI > 35 → PUT
   - Si no → NEUTRAL
8. Si hay señal: activar cooldown (15 ticks)
9. Retornar señal con razón y confianza
```

## Gestión de Operaciones Pendientes

- Cada operación tiene duración de 120 segundos
- Se verifica el resultado al final del tiempo
- **WIN**: Precio cierre favorable (CALL: precio_subió, PUT: precio_bajó)
- **LOSS**: Precio cierre desfavorable

## Estadísticas Actuales

- **Win Rate**: 64.6% (62/96 operaciones)
- **Profit Total**: +$24.90
- **Balance Actual**: $962.70

## Mejoras Pendientes

1. Optimizar win rate para alcanzar >80%
2. Ajustar parámetros de RSI según volatilidad
3. Considerar filtro de volumen
4. Implementar trailing stop loss
5. Ajustar cooldown dinámico según win rate reciente

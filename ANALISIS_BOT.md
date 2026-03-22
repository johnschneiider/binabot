# ANALISIS Y OPTIMIZACION DEL BOT - 22 MAR 2026

## RESUMEN EJECUTIVO

El bot de trading tiene varios problemas que causan bajo rendimiento:
1. Winrate insuficiente (36-48%) vs breakeven (~54%)
2. Operación en horas no óptimas
3. Parámetros subóptimos de la estrategia

## HALLAZGOS DEL BACKTEST

### Horas Óptimas (UTC)
| Hora UTC | WR | Edge | Status |
|----------|-----|------|--------|
| 22h | 78.3% | +24.2% | EXCELENTE |
| 20h | 57.1% | +3.1% | BUENO |
| 18h | 60.7% | +6.7% | BUENO |
| 14h | 73.3% | +19.3% | MUY BUENO |
| 04h | 71.4% | +17.4% | MUY BUENO |
| 02h | 64.3% | +10.2% | BUENO |

### Horas Malas (UTC)
| Hora UTC | WR | Edge | Status |
|----------|-----|------|--------|
| 23h | 45.5% | -8.6% | MALO |
| 21h | 40.0% | -14.1% | MUY MALO |
| 16h | 35.0% | -19.1% | MUY MALO |
| 15h | 43.8% | -10.3% | MALO |
| 11h | 40.0% | -14.1% | MUY MALO |
| 01h | 33.3% | -20.7% | MUY MALO |

### Mejores Combinaciones Testadas
1. **Solo 22h**: WR=78.3%, Edge=+24.2%, 23 trades
2. **20h-22h**: WR=68.2%, Edge=+14.1%, 44 trades, Profit=$11.50
3. **18h-19h-22h**: WR=63.4%, Edge=+9.3%, 71 trades, Profit=$12.25

## CONFIGURACION OPTIMA APLICADA

### .env
```
DERIV_BLOQUEO_HORAS_LOCAL=0,1,2,3,4,5,6,7,8,10,11,12,14,16,18,19,20,21,22,23,24
# PERMITIDAS (no bloqueadas): 09,13,15,17 Colombia (UTC-5)

DERIV_CONTRACT_TYPES_PERMITIDOS=CALL,PUT
DERIV_DURACION_TICKS=20
SPP_COOLDOWN_TICKS=15
SPP_EMA_FAST=5
SPP_EMA_SLOW=13
SPP_SLOPE_N=5
SPP_MIN_EMA_GAP_R100=0.30
SPP_SLOPE_THRESHOLD_R100=0.30
```

### Equivalencia de Horas
- Colombia (UTC-5) = UTC - 5 horas
- Buenos: 09, 13, 15, 17 Colombia = 14, 18, 20, 22 UTC

## ESTADO ACTUAL DE CUENTAS

| Symbol | Balance | Capital | WR | Profit | Estado |
|--------|---------|---------|-----|--------|--------|
| R_100 | $33.73 | $53.34 | 36.6% | -$5.41 | OK (desbloqueado) |
| R_10 | $34.18 | $100.00 | 48.3% | -$7.09 | OK |
| frxEURUSD | $39.42 | $100.00 | 0% | $0 | Sin ops |

## PROBLEMAS IDENTIFICADOS

1. **Winrate bajo**: 36-48% vs breakeven 54%
   - Causa: Operación en horas no óptimas
   - Solución: Aplicar horarios boas (09, 13, 15, 17 Colombia)

2. **Balance bajo**: $33.73 (de $100 inicial)
   - Causa: Pérdidas acumuladas por mal timing
   - Solución: Con WR >54% en horas boas, debería recuperar

3. **Parámetros subóptimos**:
   - EMA 50/100 en uso (debería ser 5/13)
   - CALL only (debería ser CALL+PUT)
   - Cooldown 80 (debería ser 15)

## ACCIONES REALIZADAS

1. ✅ Backtest completo con 29K ticks
2. ✅ Optimización de parámetros SPP
3. ✅ Actualización de .env con config óptima
4. ✅ Desbloqueo de cuenta R_100
5. ✅ Actualización de settings.py

## PROXIMOS PASOS

1. **Reiniciar bot** con nueva configuración
2. **Esperar hora boa** (09:00 Colombia = 14:00 UTC)
3. **Monitorear 8 horas** para validar mejora
4. **Ajustar en tiempo real** según resultados

## MONITOREO PROGRAMADO

- Script: `python status_rapido.py` (instantáneo)
- Script: `python monitoreo_8h.py` (cada 60 segundos por 8 horas)
- Revisar logs: `tail -f logs/runtime.log`

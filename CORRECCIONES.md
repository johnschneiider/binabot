# CORRECCIONES Y NUEVA ESTRATEGIA - 22 MAR 2026

## PROBLEMAS IDENTIFICADOS (Del análisis del usuario)

| Problema | Evidencia | Impacto |
|----------|-----------|---------|
| Sobreajuste | 100% WR con 1 trade | Falsa confianza |
| Sample size bajo | Solo 5 días (~30K ticks) | Estadísticas no confiables |
| Filtros excesivos | 0 ops en 1000 ticks | Sistema paralizado |
| Discrepancia UTC/Colombia | Backtest UTC vs bot Colombia | Horas equivocadas |
| Divergencia backtest/real | 78% teórico vs 36% real | Pérdidas confirmadas |

## CORRECCIONES APLICADAS

### 1. Hora boa simplificada
**Antes:** Múltiples horas (09, 13, 15, 17 Colombia)
**Ahora:** Solo **17:00 Colombia = 22:00 UTC**

### 2. Filtros desactivados
- ~~ADX_ENABLED~~ → `ADX_ENABLED=False`
- ~~ATR_FILTER~~ → `ATR_VOLATILITY_FILTER=False`
- ~~mercado_choppy~~ → Comentado
- ~~rango_lateral~~ → Comentado

### 3. PUT habilitado para R_100
- ~~put_bloqueado_r100~~ → Habilitado (backtest mostró +2.5% edge)

### 4. Cooldown reducido
- `SPP_COOLDOWN_TICKS=15` → `SPP_COOLDOWN_TICKS=5`

### 5. Duración aumentada
- `DERIV_DURACION_TICKS=20` → `DERIV_DURACION_TICKS=25`

## BACKTEST REALISTA (Hora 22h UTC)

```
Dur=5:  WR=55.0% | 20 trades | +1.0% edge | +$0.35
Dur=10: WR=65.0% | 20 trades | +11.0% edge | +$4.05
Dur=15: WR=60.0% | 20 trades | +6.0% edge | +$2.20
Dur=20: WR=70.0% | 20 trades | +16.0% edge | +$5.90
Dur=25: WR=75.0% | 20 trades | +21.0% edge | +$7.75
```

**ADVERTENCIA:** Solo 20 trades - necesita validación con más datos.

## CONFIGURACIÓN FINAL

```env
# Solo hora boa 22h UTC = 17h Colombia
DERIV_BLOQUEO_HORAS_LOCAL=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,18,19,20,21,23,24

# Duración 25 ticks (mejor WR en backtest)
DERIV_DURACION_TICKS=25
DERIV_MAX_DURACION_TICKS=25

# Cooldown mínimo para generar más señales
SPP_COOLDOWN_TICKS=5
SPP_DYNAMIC_COOLDOWN=false

# EMA óptimos según backtest
SPP_EMA_FAST=5
SPP_EMA_SLOW=13
SPP_MIN_EMA_GAP_R100=0.30

# PUT habilitado
DERIV_CONTRACT_TYPES_PERMITIDOS=CALL,PUT

# Filtros desactivados
ADX_ENABLED=False
ATR_VOLATILITY_FILTER=False
```

## PRÓXIMOS PASOS

1. **Reiniciar bot** con nueva configuración
2. **Esperar 17:00 Colombia** (22:00 UTC)
3. **Ejecutar demo por 2 semanas** mínimo 50 trades
4. **Validar WR > 54%** (breakeven)

## MÉTRICAS DE VALIDACIÓN

| Métrica | Mínimo | Bueno | Excelente |
|---------|--------|-------|-----------|
| Winrate | 54% | 58% | 65%+ |
| Trades | 50 | 100 | 200+ |
| Profit Factor | 1.0 | 1.2 | 1.5+ |
| Drawdown | <20% | <10% | <5% |

## ESTRATEGIA KELLY FRACCIONAL (Opcional)

Cuando valides WR > 60% con 50+ trades:

```python
# Fraccional Kelly = 0.25
kelly = 0.25 * (wr - (1 - wr) / payout)
stake = balance * kelly
```

Ejemplo: WR=65%, payout=0.85
- Kelly = 0.25 * (0.65 - 0.35/0.85) = 0.25 * 0.24 = 6%
- Si balance=$100 → stake=$6 por trade

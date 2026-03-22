"""
Configuración de la estrategia Multi-Activo Adaptativa
"""

# Parámetros multi-activo
MULTIACTIVO_PARAMS = {
    'activos_principales': ['R_100', '1HZ75V', 'R_10'],
    'activo_principal': 'R_100',
    'max_operaciones_simultaneas': 2,
    'riesgo_por_activo_pct': 0.02,  # 2% por activo
    'riesgo_total_max_pct': 0.05,   # 5% riesgo total máximo
}

# Configuraciones específicas por activo
CONFIGS_ACTIVOS = {
    '1HZ75V': {  # Volatility 75
        'ema_fast': 9,
        'ema_slow': 21,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 75,
        'rsi_sobreventa': 25,
        'momentum_periodo': 15,
        'volatilidad_periodo': 30,
        'cooldown_minimo': 5,
        'umbral_fuerza_tendencia': 0.00005,
        'umbral_volatilidad_min': 0.0001,
        'stake_base': 0.5,
        'max_stake': 1.0
    },
    'R_100': {
        'ema_fast': 9,
        'ema_slow': 21,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 70,
        'rsi_sobreventa': 30,
        'momentum_periodo': 10,
        'volatilidad_periodo': 20,
        'cooldown_minimo': 3,
        'umbral_fuerza_tendencia': 0.00002,
        'umbral_volatilidad_min': 0.00002,
        'stake_base': 1.0,
        'max_stake': 2.0
    },
    'R_10': {
        'ema_fast': 9,
        'ema_slow': 21,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 68,
        'rsi_sobreventa': 32,
        'momentum_periodo': 10,
        'volatilidad_periodo': 20,
        'cooldown_minimo': 3,
        'umbral_fuerza_tendencia': 0.00002,
        'umbral_volatilidad_min': 0.00002,
        'stake_base': 1.0,
        'max_stake': 2.0
    }
}

# Parámetros de gestión de riesgo
RISK_PARAMS = {
    'max_risk_per_trade': 0.02,  # 2% por trade
    'max_daily_loss': 0.05,      # 5% pérdida máxima diaria
    'max_daily_profit': 0.10,    # 10% objetivo diario
    'target_winrate': 0.60,      # 60% winrate objetivo
    'min_trades_per_day': 5,     # Mínimo trades por día
    'max_trades_per_day': 20,    # Máximo trades por día
    'fatigue_threshold': 3,      # 3 pérdidas consecutivas -> pausa
    'recovery_cooldown': 10      # 10 trades después de fatiga
}

# Configuración del símbolo
SYMBOL_CONFIG = {
    'symbol': 'R_10',
    'contract_duration': 5,      # 5 ticks
    'contract_type': 'CALL,PUT',
    'payout': 0.85               # Payout promedio para R_10
}

# Configuración de monitoreo
MONITORING_CONFIG = {
    'log_interval_ticks': 50,
    'stats_interval_minutes': 5,
    'alert_drawdown_pct': 0.10,  # Alerta si drawdown > 10%
    'alert_winrate_drop': 0.40   # Alerta si winrate < 40%
}
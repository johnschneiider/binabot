"""
ESTRATEGIA ULTRA CONSERVADORA - SIN ML, SOLO PATRONES ALTAMENTE CONFIABLES
Diseñada para 80%+ winrate con operaciones muy selectivas
"""

def evaluar_senal_ultra_conservadora(estado, precio):
    """
    Estrategia ultra conservadora que solo opera en condiciones ideales
    """
    estado.precios.append(precio)
    estado.ultimo_precio = precio
    
    if len(estado.precios) > 300:
        estado.precios = estado.precios[-300:]
    
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ("NEUTRAL", f"cooldown_{estado.cooldown}", "baja")
    
    if len(estado.precios) < 100:  # Más datos para mejor precisión
        return ("NEUTRAL", "warmup_extendido", "baja")
    
    # ============================================================
    #  INDICADORES ULTRA ESTRICTOS
    # ============================================================
    
    from binance_bot_django_v2 import calcular_ema, calcular_rsi, calcular_adx, calcular_bollinger, calcular_stoch
    
    # EMAs con períodos Fibonacci más largos para mayor estabilidad
    estado.ema_rapida = calcular_ema(precio, estado.ema_rapida, 8)
    estado.ema_media = calcular_ema(precio, estado.ema_media, 21)
    estado.ema_lenta = calcular_ema(precio, estado.ema_lenta, 55)
    
    # Indicadores adicionales
    estado.rsi = calcular_rsi(estado.precios, 14)
    estado.adx = calcular_adx(estado.precios, 14)
    estado.stoch = calcular_stoch(estado.precios, 14)
    
    banda_sup, banda_med, banda_inf, bb_pos = calcular_bollinger(estado.precios, 20, 2.0)
    estado.bb_posicion = bb_pos
    
    # ============================================================
    #  FILTROS ULTRA ESTRICTOS
    # ============================================================
    
    # 1. ADX muy fuerte (tendencia muy definida)
    if estado.adx < 35:  # Mucho más estricto
        return ("NEUTRAL", f"adx_insuficiente_{estado.adx:.1f}", "baja")
    
    # 2. Gap EMA muy amplio (evita rangos)
    if not (estado.ema_rapida and estado.ema_media and estado.ema_lenta):
        return ("NEUTRAL", "emas_no_inicializadas", "baja")
        
    ema_gap = abs(estado.ema_rapida - estado.ema_lenta) / estado.ema_lenta * 100
    if ema_gap < 0.5:  # Gap mínimo 0.5%
        return ("NEUTRAL", f"gap_insuficiente_{ema_gap:.3f}", "baja")
    
    # 3. Volatilidad controlada
    if len(estado.precios) >= 50:
        import statistics
        volatilidad = statistics.stdev(estado.precios[-50:]) / estado.precios[-1] * 100
        if volatilidad < 0.3 or volatilidad > 1.5:  # Rango muy específico
            return ("NEUTRAL", f"volatilidad_fuera_rango_{volatilidad:.3f}", "baja")
    
    # 4. Confirmación de múltiples timeframes (EMAs alineadas perfectamente)
    tendencia_alcista_perfecta = (
        estado.ema_rapida > estado.ema_media > estado.ema_lenta and
        (estado.ema_rapida - estado.ema_media) > (estado.ema_media - estado.ema_lenta) * 0.3  # Aceleración
    )
    
    tendencia_bajista_perfecta = (
        estado.ema_rapida < estado.ema_media < estado.ema_lenta and
        (estado.ema_media - estado.ema_rapida) > (estado.ema_lenta - estado.ema_media) * 0.3  # Aceleración
    )
    
    # ============================================================
    #  CONDICIONES CALL - ULTRA SELECTIVAS
    # ============================================================
    
    if tendencia_alcista_perfecta:
        # RSI en zona ideal (ni muy alto ni muy bajo)
        if not (40 <= estado.rsi <= 65):
            return ("NEUTRAL", f"rsi_fuera_zona_call_{estado.rsi:.1f}", "baja")
        
        # Bollinger en posición favorable (no sobrecomprado)
        if estado.bb_posicion > 0.75:
            return ("NEUTRAL", f"bb_sobrecomprado_{estado.bb_posicion:.2f}", "baja")
        
        # Estocástico favorable
        if estado.stoch > 75:
            return ("NEUTRAL", f"stoch_sobrecomprado_{estado.stoch:.1f}", "baja")
        
        # Momentum reciente (precio subiendo en los últimos ticks)
        if len(estado.precios) >= 10:
            momentum_reciente = (precio - estado.precios[-10]) / estado.precios[-10] * 100
            if momentum_reciente < 0.1:  # Al menos 0.1% de subida reciente
                return ("NEUTRAL", f"momentum_insuficiente_{momentum_reciente:.3f}", "baja")
        
        # Confirmación final: todo perfecto
        estado.cooldown = 40  # Cooldown largo para evitar overtrading
        confianza = "maxima"
        return ("CALL", f"ultra_call_adx{estado.adx:.0f}_gap{ema_gap:.2f}_mom{momentum_reciente:.2f}", confianza)
    
    # ============================================================
    #  CONDICIONES PUT - ULTRA SELECTIVAS
    # ============================================================
    
    if tendencia_bajista_perfecta:
        # RSI en zona ideal
        if not (35 <= estado.rsi <= 60):
            return ("NEUTRAL", f"rsi_fuera_zona_put_{estado.rsi:.1f}", "baja")
        
        # Bollinger en posición favorable (no sobrevendido)
        if estado.bb_posicion < 0.25:
            return ("NEUTRAL", f"bb_sobrevendido_{estado.bb_posicion:.2f}", "baja")
        
        # Estocástico favorable
        if estado.stoch < 25:
            return ("NEUTRAL", f"stoch_sobrevendido_{estado.stoch:.1f}", "baja")
        
        # Momentum bajista reciente
        if len(estado.precios) >= 10:
            momentum_reciente = (precio - estado.precios[-10]) / estado.precios[-10] * 100
            if momentum_reciente > -0.1:  # Al menos 0.1% de bajada reciente
                return ("NEUTRAL", f"momentum_bajista_insuficiente_{momentum_reciente:.3f}", "baja")
        
        # Confirmación final: todo perfecto
        estado.cooldown = 40  # Cooldown largo
        confianza = "maxima"
        return ("PUT", f"ultra_put_adx{estado.adx:.0f}_gap{ema_gap:.2f}_mom{momentum_reciente:.2f}", confianza)
    
    return ("NEUTRAL", "condiciones_ultra_no_cumplidas", "baja")

def filtros_horarios_conservadores():
    """Sin restricciones horarias — el bot opera 24/7"""
    return True, "hora_favorable"

def filtros_simbolo_conservadores(simbolo):
    """Filtros por símbolo basados en performance histórica"""
    
    # BTC: El más estable, preferido
    if simbolo == "BTC":
        return True, "btc_preferido"
    
    # ETH: Segundo más estable
    if simbolo == "ETH":
        return True, "eth_aceptable"
    
    # Otros símbolos: más restrictivos
    if simbolo in ["SOL", "XRP"]:
        from datetime import datetime
        hora = datetime.now().hour
        if hora not in [9, 10, 15, 16]:  # Solo en horas muy específicas
            return False, f"{simbolo.lower()}_hora_restringida"
        return True, f"{simbolo.lower()}_condicional"
    
    return False, f"simbolo_no_autorizado_{simbolo}"
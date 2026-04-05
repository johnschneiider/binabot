"""
ESTRATEGIA ML - ANÁLISIS DE PATRONES HISTÓRICOS PARA 80% WINRATE
Aprende de las operaciones pasadas y ajusta filtros dinámicamente
"""

import json
import time
from datetime import datetime, timedelta, timezone
import statistics
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()
from gestion_riesgo.models import OperacionBinance

class MLStrategy:
    def __init__(self):
        self.analizar_historico()
        
    def analizar_historico(self):
        """Analiza las últimas 200 operaciones para extraer patrones"""
        print("🧠 ANÁLISIS ML DE PATRONES HISTÓRICOS...")
        
        ops = list(OperacionBinance.objects.order_by('-created_at')[:200])
        
        # Análisis por hora del día
        self.horas_ganadoras = {}
        self.horas_perdedoras = {}
        
        for hora in range(24):
            ops_hora = [op for op in ops if op.created_at.hour == hora]
            if len(ops_hora) >= 5:
                wins = sum(1 for op in ops_hora if op.es_win)
                wr = (wins / len(ops_hora)) * 100
                
                if wr >= 70:
                    self.horas_ganadoras[hora] = wr
                elif wr <= 30:
                    self.horas_perdedoras[hora] = wr
        
        # Análisis por símbolo
        self.simbolos_performance = {}
        for simbolo in ['BTC', 'ETH', 'SOL', 'XRP']:
            ops_simbolo = [op for op in ops if op.simbolo == simbolo]
            if ops_simbolo:
                wins = sum(1 for op in ops_simbolo if op.es_win)
                wr = (wins / len(ops_simbolo)) * 100
                self.simbolos_performance[simbolo] = {
                    'winrate': wr,
                    'total_ops': len(ops_simbolo),
                    'activo': wr >= 45  # Solo activos con >45% WR
                }
        
        # Análisis por dirección (CALL vs PUT)
        calls = [op for op in ops if op.direccion == 'CALL']
        puts = [op for op in ops if op.direccion == 'PUT']
        
        self.call_wr = (sum(1 for op in calls if op.es_win) / len(calls) * 100) if calls else 0
        self.put_wr = (sum(1 for op in puts if op.es_win) / len(puts) * 100) if puts else 0
        
        # Análisis por razones (estrategias que más funcionan)
        self.razones_exitosas = {}
        razones = {}
        
        for op in ops:
            razon_base = op.razon.split('_out:')[0].replace('v2_', '')
            if razon_base not in razones:
                razones[razon_base] = {'wins': 0, 'total': 0}
            razones[razon_base]['total'] += 1
            if op.es_win:
                razones[razon_base]['wins'] += 1
        
        for razon, data in razones.items():
            if data['total'] >= 5:  # Mínimo 5 operaciones
                wr = (data['wins'] / data['total']) * 100
                if wr >= 60:  # Solo patrones exitosos
                    self.razones_exitosas[razon] = wr
        
        print(f"✅ Análisis completado:")
        print(f"   Horas ganadoras: {list(self.horas_ganadoras.keys())}")
        print(f"   Símbolos activos: {[s for s, d in self.simbolos_performance.items() if d['activo']]}")
        print(f"   CALL WR: {self.call_wr:.1f}% | PUT WR: {self.put_wr:.1f}%")
        print(f"   Mejores estrategias: {list(self.razones_exitosas.keys())[:3]}")
    
    def evaluar_momento_optimal(self):
        """Evalúa si es un buen momento para operar"""
        hora_actual = datetime.now().hour
        
        # Factor hora
        factor_hora = 1.0
        if hora_actual in self.horas_ganadoras:
            factor_hora = 1.5  # Boost en horas ganadoras
        elif hora_actual in self.horas_perdedoras:
            factor_hora = 0.3  # Penalización en horas perdedoras
        
        return factor_hora
    
    def filtrar_simbolo(self, simbolo):
        """Determina si un símbolo es bueno para operar"""
        if simbolo not in self.simbolos_performance:
            return False
        
        performance = self.simbolos_performance[simbolo]
        return performance['activo'] and performance['total_ops'] >= 10
    
    def ajustar_direccion(self, direccion_original):
        """Ajusta la dirección basada en performance histórica"""
        if self.call_wr > self.put_wr + 10:  # CALL significativamente mejor
            if direccion_original == "PUT":
                return None  # Evitar PUTs si CALL es mucho mejor
        elif self.put_wr > self.call_wr + 10:  # PUT significativamente mejor
            if direccion_original == "CALL":
                return None  # Evitar CALLs si PUT es mucho mejor
        
        return direccion_original
    
    def calcular_score_confianza(self, simbolo, direccion, razon, hora_actual):
        """Calcula un score de confianza basado en análisis histórico"""
        score = 50.0  # Base
        
        # Factor símbolo
        if self.filtrar_simbolo(simbolo):
            perf = self.simbolos_performance[simbolo]
            score += (perf['winrate'] - 50) * 0.5
        else:
            score -= 20
        
        # Factor hora
        if hora_actual in self.horas_ganadoras:
            score += 15
        elif hora_actual in self.horas_perdedoras:
            score -= 25
        
        # Factor dirección
        if direccion == "CALL" and self.call_wr > 50:
            score += (self.call_wr - 50) * 0.3
        elif direccion == "PUT" and self.put_wr > 50:
            score += (self.put_wr - 50) * 0.3
        
        # Factor estrategia
        for razon_exitosa in self.razones_exitosas:
            if razon_exitosa in razon:
                score += 10
                break
        
        return max(0, min(100, score))

# Instancia global
ml_strategy = MLStrategy()

def aplicar_filtros_ml(simbolo, direccion, razon, precio):
    """Aplica filtros de ML antes de ejecutar operación"""
    hora_actual = datetime.now().hour
    
    # 1. Filtro de símbolo
    if not ml_strategy.filtrar_simbolo(simbolo):
        return False, f"simbolo_filtrado_{simbolo}"
    
    # 2. Filtro de hora
    factor_hora = ml_strategy.evaluar_momento_optimal()
    if factor_hora < 0.5:
        return False, f"hora_mala_{hora_actual}"
    
    # 3. Filtro de dirección
    direccion_ajustada = ml_strategy.ajustar_direccion(direccion)
    if direccion_ajustada is None:
        return False, f"direccion_filtrada_{direccion}"
    
    # 4. Score de confianza
    score = ml_strategy.calcular_score_confianza(simbolo, direccion, razon, hora_actual)
    if score < 70:  # Solo operaciones con alta confianza
        return False, f"score_bajo_{score:.0f}"
    
    return True, f"ml_approved_{score:.0f}"

def recalcular_estrategia():
    """Recalcula la estrategia cada 50 operaciones"""
    try:
        ops_recientes = OperacionBinance.objects.filter(
            created_at__gte=datetime.now() - timedelta(hours=6)
        ).count()
        
        if ops_recientes >= 50:
            print("🔄 RECALCULANDO ESTRATEGIA ML...")
            global ml_strategy
            ml_strategy = MLStrategy()
            return True
    except Exception as e:
        print(f"Error recalculando: {e}")
    return False

if __name__ == "__main__":
    # Test de la estrategia
    ml = MLStrategy()
    
    print("\n=== TEST FILTROS ML ===")
    test_cases = [
        ("BTC", "CALL", "multi_alcista", 67000),
        ("ETH", "PUT", "multi_bajista", 2050),
        ("SOL", "CALL", "ema_crossover_up", 80),
        ("XRP", "PUT", "ema_crossover_dn", 1.32),
    ]
    
    for simbolo, direccion, razon, precio in test_cases:
        aprobado, motivo = aplicar_filtros_ml(simbolo, direccion, razon, precio)
        status = "✅ APROBADO" if aprobado else "❌ RECHAZADO"
        print(f"{simbolo} {direccion}: {status} - {motivo}")
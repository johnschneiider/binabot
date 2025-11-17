"""
Vistas para el dashboard de entrenamiento de IA.
"""
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Count, Sum, Avg, Q
from ai_trading.models import EstrategiaGenetica, TradeIA, EntrenamientoIA, PoblacionGenetica


def dashboard_ia(request):
    """
    Dashboard principal para observar el entrenamiento de la IA.
    """
    return render(request, 'ai_trading/dashboard.html')


class EstadoEntrenamientoIAView(APIView):
    """
    Estado general del entrenamiento de IA.
    """
    def get(self, request):
        estrategias_activas = EstrategiaGenetica.objects.filter(activa=True)
        mejor_estrategia = estrategias_activas.order_by('-fitness').first()
        
        total_trades = TradeIA.objects.count()
        trades_ganados = TradeIA.objects.filter(resultado=TradeIA.Resultado.GANADO).count()
        trades_perdidos = TradeIA.objects.filter(resultado=TradeIA.Resultado.PERDIDO).count()
        
        return Response({
            "total_estrategias": estrategias_activas.count(),
            "mejor_estrategia": {
                "id": mejor_estrategia.id if mejor_estrategia else None,
                "nombre": mejor_estrategia.nombre if mejor_estrategia else None,
                "fitness": float(mejor_estrategia.fitness) if mejor_estrategia else 0.0,
                "winrate": float(mejor_estrategia.winrate) if mejor_estrategia else 0.0,
                "operaciones_evaluadas": mejor_estrategia.operaciones_evaluadas if mejor_estrategia else 0,
            },
            "trades_totales": total_trades,
            "trades_ganados": trades_ganados,
            "trades_perdidos": trades_perdidos,
            "winrate_global": (trades_ganados / total_trades * 100) if total_trades > 0 else 0.0,
        })


class TopEstrategiasView(APIView):
    """
    Top estrategias por fitness.
    """
    def get(self, request):
        limite = int(request.query_params.get("limite", 10))
        estrategias = EstrategiaGenetica.objects.filter(activa=True).order_by('-fitness')[:limite]
        
        return Response({
            "estrategias": [
                {
                    "id": e.id,
                    "nombre": e.nombre,
                    "generacion": e.generacion,
                    "fitness": float(e.fitness),
                    "winrate": float(e.winrate),
                    "operaciones_evaluadas": e.operaciones_evaluadas,
                    "ganadas": e.ganadas,
                    "perdidas": e.perdidas,
                    "beneficio_total": float(e.beneficio_total),
                }
                for e in estrategias
            ]
        })


class TradesRecientesIAView(APIView):
    """
    Trades recientes de la IA.
    """
    def get(self, request):
        limite = int(request.query_params.get("limite", 20))
        trades = TradeIA.objects.select_related('estrategia').order_by('-hora_inicio')[:limite]
        
        return Response({
            "trades": [
                {
                    "id": t.id,
                    "estrategia": t.estrategia.nombre,
                    "activo": t.activo,
                    "direccion": t.direccion,
                    "resultado": t.resultado,
                    "beneficio": float(t.beneficio),
                    "reward": float(t.reward),
                    "hora_inicio": t.hora_inicio.isoformat(),
                    "hora_fin": t.hora_fin.isoformat() if t.hora_fin else None,
                }
                for t in trades
            ]
        })


class EstadisticasEstrategiaView(APIView):
    """
    Estadísticas detalladas de una estrategia específica.
    """
    def get(self, request, estrategia_id):
        try:
            estrategia = EstrategiaGenetica.objects.get(id=estrategia_id)
        except EstrategiaGenetica.DoesNotExist:
            return Response({"error": "Estrategia no encontrada"}, status=404)
        
        trades = TradeIA.objects.filter(estrategia=estrategia)
        
        return Response({
            "estrategia": {
                "id": estrategia.id,
                "nombre": estrategia.nombre,
                "generacion": estrategia.generacion,
                "fitness": float(estrategia.fitness),
                "winrate": float(estrategia.winrate),
                "operaciones_evaluadas": estrategia.operaciones_evaluadas,
                "ganadas": estrategia.ganadas,
                "perdidas": estrategia.perdidas,
                "beneficio_total": float(estrategia.beneficio_total),
            },
            "parametros": {
                "umbral_variacion_min": float(estrategia.umbral_variacion_min),
                "umbral_confianza_min": float(estrategia.umbral_confianza_min),
                "ventana_ticks": estrategia.ventana_ticks,
                "peso_winrate_simulacion": float(estrategia.peso_winrate_simulacion),
                "peso_confianza_horario": float(estrategia.peso_confianza_horario),
                "umbral_riesgo_max": float(estrategia.umbral_riesgo_max),
            },
            "trades": {
                "total": trades.count(),
                "ganados": trades.filter(resultado=TradeIA.Resultado.GANADO).count(),
                "perdidos": trades.filter(resultado=TradeIA.Resultado.PERDIDO).count(),
                "reward_promedio": float(trades.aggregate(avg=Avg('reward'))['avg'] or 0.0),
                "beneficio_total": float(trades.aggregate(total=Sum('beneficio'))['total'] or 0.0),
            }
        })

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import connection
from django.utils import timezone
import json
import time


def dashboard(request):
    """Dashboard principal para Forex trading."""
    return render(request, 'trading/dashboard.html')


@csrf_exempt
@require_http_methods(["POST"])
def api_guardar_operacion(request):
    """API para guardar operaciones."""
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
    
    simbolo = data.get("simbolo", "").upper()
    direccion = data.get("direccion", "CALL")
    precio_entrada = float(data.get("precio_entrada", 0))
    razon = data.get("razon", "")
    confianza = data.get("confianza", "media")
    es_win = bool(data.get("es_win", False))
    profit = float(data.get("profit", 0))
    
    if not simbolo:
        return JsonResponse({"error": "simbolo requerido"}, status=400)
    
    from .models import EstadisticasTrading, OperacionTrading
    
    stats, created = EstadisticasTrading.objects.get_or_create(
        simbolo=simbolo,
        defaults={"balance_ficticio": 1000}
    )
    
    stats.total_ops += 1
    if es_win:
        stats.wins += 1
        stats.win_streak += 1
        stats.loss_streak = 0
    else:
        stats.losses += 1
        stats.loss_streak += 1
        stats.win_streak = 0
    
    from decimal import Decimal
    stats.profit_total += Decimal(str(profit))
    stats.balance_ficticio += Decimal(str(profit))
    stats.ultima_operacion = timezone.now()
    stats.save()
    
    operacion = OperacionTrading.objects.create(
        simbolo=simbolo,
        direccion=direccion,
        precio_entrada=precio_entrada,
        razon=razon,
        confianza=confianza,
        es_win=es_win,
        profit=profit,
        win_rate_momento=stats.win_rate,
        profit_total=stats.profit_total,
        num_operacion=stats.total_ops,
    )
    
    return JsonResponse({
        "ok": True,
        "operacion_id": operacion.id,
        "stats": {
            "simbolo": simbolo,
            "total_ops": stats.total_ops,
            "wins": stats.wins,
            "win_rate": stats.win_rate,
            "profit_total": float(stats.profit_total),
            "balance_ficticio": float(stats.balance_ficticio),
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_guardar_tick(request):
    """API para guardar ticks de precio."""
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
    
    simbolo = data.get("simbolo", "").upper()
    precio = float(data.get("precio", 0))
    
    if not simbolo or precio <= 0:
        return JsonResponse({"error": "datos inválidos"}, status=400)
    
    from .models import TickTrading
    from decimal import Decimal
    
    TickTrading.objects.create(
        simbolo=simbolo,
        precio=Decimal(str(precio))
    )
    
    ticks_viejos = TickTrading.objects.filter(simbolo=simbolo).order_by('-timestamp')[200:]
    if ticks_viejos:
        TickTrading.objects.filter(id__in=[t.id for t in ticks_viejos]).delete()
    
    return JsonResponse({"ok": True})


def sse_trading_stream(request):
    """Server-Sent Events para updates en tiempo real."""
    from django.http import StreamingHttpResponse
    from django.utils import timezone
    from datetime import timedelta
    from .models import OperacionTrading, EstadisticasTrading, TickTrading, ConfiguracionTrading
    from .models import calcular_ema, calcular_rsi, calcular_bollinger
    
    def event_stream():
        while True:
            try:
                connection.close()
                
                stats = EstadisticasTrading.objects.all()
                total_ops = sum(s.total_ops for s in stats)
                total_wins = sum(s.wins for s in stats)
                wr_global = (total_wins / total_ops * 100) if total_ops > 0 else 0
                total_profit = sum(float(s.profit_total) for s in stats)
                balance_ficticio = sum(float(s.balance_ficticio) for s in stats)
                
                activos_data = []
                for s in stats:
                    activos_data.append({
                        "simbolo": s.simbolo,
                        "profit": float(s.profit_total),
                        "ops": s.total_ops,
                        "wr": s.win_rate
                    })
                
                ultima_op = OperacionTrading.objects.order_by('-created_at').first()
                op_data = None
                if ultima_op:
                    hora_colombia = ultima_op.created_at - timedelta(hours=5)
                    op_data = {
                        "num": ultima_op.num_operacion,
                        "simbolo": ultima_op.simbolo,
                        "direccion": ultima_op.direccion,
                        "precio": float(ultima_op.precio_entrada),
                        "razon": ultima_op.razon,
                        "confianza": ultima_op.confianza,
                        "es_win": ultima_op.es_win,
                        "profit": float(ultima_op.profit),
                        "hora": hora_colombia.strftime("%d-%m-%Y %H:%M:%S")
                    }
                
                historial_data = []
                ultimas_ops = OperacionTrading.objects.order_by('-created_at')[:50]
                for op in ultimas_ops:
                    hora_col = op.created_at - timedelta(hours=5)
                    historial_data.append({
                        "num": op.num_operacion,
                        "simbolo": op.simbolo,
                        "direccion": op.direccion,
                        "precio": float(op.precio_entrada),
                        "razon": op.razon,
                        "confianza": op.confianza,
                        "es_win": op.es_win,
                        "profit": float(op.profit),
                        "hora": hora_col.strftime("%d-%m-%Y %H:%M:%S")
                    })
                
                simbolos = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
                ticks_data = {}
                indicadores_data = {}
                
                for sym in simbolos:
                    ticks = TickTrading.objects.filter(simbolo=sym).order_by('-timestamp')[:200]
                    ticks_list = [
                        {
                            "t": t.timestamp.strftime("%H:%M:%S"),
                            "p": float(t.precio)
                        }
                        for t in reversed(list(ticks))
                    ]
                    ticks_data[sym] = ticks_list
                    
                    if len(ticks_list) >= 60:
                        prices = [t["p"] for t in ticks_list]
                        
                        ema9 = calcular_ema(prices, 9)
                        ema21 = calcular_ema(prices, 21)
                        ema50 = calcular_ema(prices, 50)
                        rsi = calcular_rsi(prices, 14)
                        bb_sup, bb_mid, bb_inf = calcular_bollinger(prices, 20, 2)
                        
                        indicadores_data[sym] = {
                            "ema9": round(ema9, 5) if ema9 else None,
                            "ema21": round(ema21, 5) if ema21 else None,
                            "ema50": round(ema50, 5) if ema50 else None,
                            "rsi": round(rsi, 1) if rsi else None,
                            "bb_sup": round(bb_sup, 5) if bb_sup else None,
                            "bb_mid": round(bb_mid, 5) if bb_mid else None,
                            "bb_inf": round(bb_inf, 5) if bb_inf else None,
                        }
                
                senal_activa = None
                if ultima_op and (time.time() - ultima_op.created_at.timestamp()) < 120:
                    senal_activa = {
                        "simbolo": ultima_op.simbolo,
                        "direccion": ultima_op.direccion,
                        "hora": ultima_op.created_at.strftime("%H:%M:%S")
                    }
                
                data = json.dumps({
                    "type": "update",
                    "timestamp": time.time(),
                    "total_ops": total_ops,
                    "total_wins": total_wins,
                    "wr_global": round(wr_global, 1),
                    "total_profit": round(total_profit, 2),
                    "balance_ficticio": round(balance_ficticio, 2),
                    "activos": activos_data,
                    "ultima_operacion": op_data,
                    "historial": historial_data,
                    "ticks": ticks_data,
                    "indicadores": indicadores_data,
                    "senal_activa": senal_activa,
                })
                
                yield f"data: {data}\n\n"
                time.sleep(2)
                
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                time.sleep(5)
    
    return StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_configuracion(request):
    """API para obtener y modificar la configuración."""
    from django.utils import timezone
    
    config = ConfiguracionTrading.get_activa()
    
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            
            if data.get("reset"):
                config.reset_to_default()
            else:
                if "ema_gap_min" in data:
                    config.ema_gap_min = float(data["ema_gap_min"])
                if "adx_min" in data:
                    config.adx_min = float(data["adx_min"])
                if "rsi_min" in data:
                    config.rsi_min = float(data["rsi_min"])
                if "rsi_max" in data:
                    config.rsi_max = float(data["rsi_max"])
                if "bb_min" in data:
                    config.bb_min = float(data["bb_min"])
                if "bb_max" in data:
                    config.bb_max = float(data["bb_max"])
                if "cooldown_ticks" in data:
                    config.cooldown_ticks = int(data["cooldown_ticks"])
                if "stake" in data:
                    config.stake = float(data["stake"])
                if "duracion_segundos" in data:
                    config.duracion_segundos = int(data["duracion_segundos"])
                if "payout" in data:
                    config.payout = float(data["payout"])
                
                config.save()
            
            return JsonResponse({
                "ok": True,
                "config": {
                    "ema_gap_min": config.ema_gap_min,
                    "adx_min": config.adx_min,
                    "rsi_min": config.rsi_min,
                    "rsi_max": config.rsi_max,
                    "bb_min": config.bb_min,
                    "bb_max": config.bb_max,
                    "cooldown_ticks": config.cooldown_ticks,
                    "stake": config.stake,
                    "duracion_segundos": config.duracion_segundos,
                    "payout": config.payout,
                }
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    
    return JsonResponse({
        "config": {
            "ema_gap_min": config.ema_gap_min,
            "adx_min": config.adx_min,
            "rsi_min": config.rsi_min,
            "rsi_max": config.rsi_max,
            "bb_min": config.bb_min,
            "bb_max": config.bb_max,
            "cooldown_ticks": config.cooldown_ticks,
            "stake": config.stake,
            "duracion_segundos": config.duracion_segundos,
            "payout": config.payout,
        }
    })

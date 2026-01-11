from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
import re

from django.utils import timezone
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.db.models import F

from .models import BalanceDerivSnapshot, Cuenta, OperacionDeriv, TickDerivSnapshot


def _winrate_ultimas_deriv(*, n: int = 15) -> dict:
    """
    Winrate simple para el dashboard.
    - Solo operaciones reales del bot (creada_por_bot=True)
    - Solo cerradas con profit disponible
    - Win = profit > 0
    """
    n = max(1, int(n))
    qs = (
        OperacionDeriv.objects.filter(creada_por_bot=True, estado=OperacionDeriv.Estado.CERRADA, profit__isnull=False)
        .order_by("-updated_at")
        .values_list("profit", flat=True)[:n]
    )
    profits = list(qs)
    if not profits:
        return {"n": 0, "wins": 0, "losses": 0, "winrate": None}
    wins = sum(1 for p in profits if float(p) > 0.0)
    losses = len(profits) - wins
    winrate = (wins / len(profits)) * 100.0
    return {"n": len(profits), "wins": wins, "losses": losses, "winrate": winrate}


def _fecha_hora_colombia_desde_epoch(epoch: int | None) -> datetime | None:
    """
    CONVIERTE EPOCH (UTC) A FECHA/HORA EN HUSO HORARIO DEL PROYECTO (America/Bogota).

    POR QUÉ:
    - DERIV ENTREGA EPOCH EN UTC.
    - EL DASHBOARD DEBE MOSTRAR LA HORA LOCAL (COLOMBIA).
    """
    if not epoch:
        return None
    dt_utc = datetime.fromtimestamp(int(epoch), tz=dt_timezone.utc)
    return timezone.localtime(dt_utc)


def _fmt_hhmmss(total_seg: int) -> str:
    total = max(0, int(total_seg))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _riesgo_motivo_ui(riesgo_motivo: str | None) -> dict:
    """
    Traduce el motivo "técnico" a algo legible para el dashboard.

    Retorna:
      - label: string humano
      - pausa_hasta_epoch: int|None (si aplica)
    """
    rm = (riesgo_motivo or "").strip()
    if not rm:
        return {"label": "—", "pausa_hasta_epoch": None}

    # PAUSA_CICLO_HASTA_<epoch>
    m = re.match(r"^PAUSA_CICLO_HASTA_(\d+)$", rm)
    if m:
        return {"label": "PAUSA (ciclo)", "pausa_hasta_epoch": int(m.group(1))}

    # TAKE_PROFIT_<tp>_PAUSA_<secs>s
    m = re.match(r"^TAKE_PROFIT_([0-9.]+)_PAUSA_(\d+)s$", rm)
    if m:
        tp = float(m.group(1))
        pausa_s = int(m.group(2))
        return {"label": f"TAKE PROFIT (meta {tp*100:.2f}% · pausa {pausa_s//60}m)", "pausa_hasta_epoch": None}

    # TAKE_PROFIT_<tp>_SIN_PAUSA
    m = re.match(r"^TAKE_PROFIT_([0-9.]+)_SIN_PAUSA$", rm)
    if m:
        tp = float(m.group(1))
        return {"label": f"TAKE PROFIT (meta {tp*100:.2f}% · sin pausa)", "pausa_hasta_epoch": None}

    # STOPLOSS_<sl>_PAUSA_<secs>s
    m = re.match(r"^STOPLOSS_([0-9.]+)_PAUSA_(\d+)s$", rm)
    if m:
        sl = float(m.group(1))
        pausa_s = int(m.group(2))
        return {"label": f"STOP LOSS ({sl*100:.2f}% · pausa {pausa_s//60}m)", "pausa_hasta_epoch": None}

    if rm == "CICLO_ACTIVO":
        return {"label": "CICLO ACTIVO", "pausa_hasta_epoch": None}
    if rm == "DRAWDOWN":
        return {"label": "DRAWDOWN (protección)", "pausa_hasta_epoch": None}
    if rm == "OK":
        return {"label": "OK", "pausa_hasta_epoch": None}

    # Fallback: no romper UI, pero no mostrar el prefijo técnico si viene vacío.
    return {"label": rm, "pausa_hasta_epoch": None}


@require_http_methods(["GET", "HEAD"])
def dashboard(request):
    """
    DASHBOARD WEB PARA MONITOREO (BALANCE + OPERACIONES) EN "TIEMPO REAL" (POLLING).
    """
    cuenta = Cuenta.objects.order_by("-updated_at").first()
    operaciones_deriv = (
        OperacionDeriv.objects.select_related("cuenta")
        .filter(creada_por_bot=True)
        .annotate(duracion_segundos=F("closed_epoch") - F("opened_epoch"))
        .order_by("-updated_at")[:50]
    )

    # FECHA/HORA DERIVADA DE EPOCH EN HUSO HORARIO LOCAL (COLOMBIA).
    for op in operaciones_deriv:
        epoch_ref = op.closed_epoch or op.opened_epoch
        op.fecha_hora = _fecha_hora_colombia_desde_epoch(int(epoch_ref) if epoch_ref else None)
    return render(
        request,
        "gestion_riesgo/dashboard.html",
        {"cuenta": cuenta, "operaciones_deriv": operaciones_deriv, "winrate_ult15": _winrate_ultimas_deriv(n=15)},
    )


@require_http_methods(["GET", "HEAD"])
def estado_json(request):
    """
    ENDPOINT PARA POLLING DESDE EL FRONTEND.
    """
    cuenta = Cuenta.objects.order_by("-updated_at").first()
    ops_deriv = list(
        OperacionDeriv.objects.order_by("-updated_at")
        .filter(creada_por_bot=True)
        .annotate(duracion_segundos=F("closed_epoch") - F("opened_epoch"))
        .values(
            "id",
            "simbolo",
            "contract_id",
            "estado",
            "moneda",
            "profit",
            "umbral_usado",
            "opened_epoch",
            "closed_epoch",
            "duracion_segundos",
            "updated_at",
        )[:50]
    )
    for op in ops_deriv:
        epoch_ref = op.get("closed_epoch") or op.get("opened_epoch")
        dt_local = _fecha_hora_colombia_desde_epoch(int(epoch_ref) if epoch_ref else None)
        # FORMATO SIMPLE PARA UI (SIN UTC).
        op["fecha_hora"] = dt_local.strftime("%Y-%m-%d %H:%M:%S") if dt_local else None
    cuenta_dict = None
    if cuenta is not None:
        now_epoch = int(timezone.now().timestamp())
        pausa_hasta_epoch = int(cuenta.ciclo_pausa_hasta_epoch) if cuenta.ciclo_pausa_hasta_epoch is not None else None
        dt_pausa_local = _fecha_hora_colombia_desde_epoch(pausa_hasta_epoch) if pausa_hasta_epoch else None
        pausa_restante_seg = max(0, int(pausa_hasta_epoch - now_epoch)) if pausa_hasta_epoch else None

        riesgo_ui = _riesgo_motivo_ui(cuenta.riesgo_motivo)
        # Si el motivo trae epoch incrustado, preferimos ese.
        pausa_epoch_from_motivo = riesgo_ui.get("pausa_hasta_epoch")
        if pausa_epoch_from_motivo:
            pausa_hasta_epoch = int(pausa_epoch_from_motivo)
            dt_pausa_local = _fecha_hora_colombia_desde_epoch(pausa_hasta_epoch)
            pausa_restante_seg = max(0, int(pausa_hasta_epoch - now_epoch))

        # Fechas legibles para ciclo y último tick
        dt_ciclo_inicio = _fecha_hora_colombia_desde_epoch(cuenta.ciclo_inicio_epoch) if cuenta.ciclo_inicio_epoch else None
        dt_ultimo_tick = _fecha_hora_colombia_desde_epoch(cuenta.ultimo_tick_epoch) if cuenta.ultimo_tick_epoch else None

        cuenta_dict = {
            "id": cuenta.id,
            "simbolo": cuenta.simbolo,
            "balance_deriv": cuenta.balance_deriv,
            "moneda_deriv": cuenta.moneda_deriv,
            "max_balance_deriv_historico": cuenta.max_balance_deriv_historico,
            "capital_inicial": cuenta.capital_inicial,
            "capital_actual": cuenta.capital_actual,
            "max_capital_historico": cuenta.max_capital_historico,
            "bloqueado": cuenta.bloqueado,
            "riesgo_motivo": cuenta.riesgo_motivo,
            "riesgo_motivo_ui": riesgo_ui.get("label") or cuenta.riesgo_motivo,
            "ciclo_balance_inicio": cuenta.ciclo_balance_inicio,
            "ciclo_inicio_epoch": cuenta.ciclo_inicio_epoch,
            "ciclo_inicio_local": dt_ciclo_inicio.strftime("%Y-%m-%d %H:%M:%S") if dt_ciclo_inicio else None,
            "ciclo_pausa_hasta_epoch": cuenta.ciclo_pausa_hasta_epoch,
            "ciclo_pausa_hasta_local": dt_pausa_local.strftime("%Y-%m-%d %H:%M:%S") if dt_pausa_local else None,
            "ciclo_pausa_restante_seg": pausa_restante_seg,
            "ciclo_pausa_restante_hhmmss": _fmt_hhmmss(pausa_restante_seg) if pausa_restante_seg is not None else None,
            "ciclo_ultimo_evento": cuenta.ciclo_ultimo_evento,
            "ultimo_tick_epoch": cuenta.ultimo_tick_epoch,
            "ultimo_tick_local": dt_ultimo_tick.strftime("%Y-%m-%d %H:%M:%S") if dt_ultimo_tick else None,
            "ultimo_precio": cuenta.ultimo_precio,
            "senal_valor": cuenta.senal_valor,
            "senal_decision": cuenta.senal_decision,
            "senal_top_contribuciones": cuenta.senal_top_contribuciones,
            "updated_at": cuenta.updated_at,
            "winrate_ult15": _winrate_ultimas_deriv(n=15),
        }
    return JsonResponse({"cuenta": cuenta_dict, "operaciones_deriv": ops_deriv})


@require_http_methods(["GET", "HEAD"])
def balance_json(request):
    """
    Serie temporal del balance (para gráfica).

    Filtros:
    - range=hour  => últimos 60 minutos
    - range=day   => últimas 2 horas
    - range=week  => últimos 7 días
    - range=month => últimas 4 semanas
    """
    rango = (request.GET.get("range") or "hour").strip().lower()
    ahora = timezone.now()

    if rango == "hour":
        desde = ahora - timezone.timedelta(minutes=60)
    elif rango == "day":
        desde = ahora - timezone.timedelta(hours=2)
    elif rango == "week":
        desde = ahora - timezone.timedelta(days=7)
    elif rango == "month":
        desde = ahora - timezone.timedelta(days=28)
    else:
        # fallback seguro
        desde = ahora - timezone.timedelta(minutes=60)

    cuenta = Cuenta.objects.order_by("-updated_at").first()
    if not cuenta:
        return JsonResponse({"cuenta_id": None, "points": []})

    qs = (
        BalanceDerivSnapshot.objects.filter(cuenta_id=cuenta.id, created_at__gte=desde)
        .order_by("created_at")
        .values("created_at", "balance", "moneda")
    )

    points = []
    for row in qs:
        dt_local = timezone.localtime(row["created_at"])
        points.append(
            {
                "t": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
                "balance": float(row["balance"]),
                "moneda": row.get("moneda") or "",
            }
        )
    return JsonResponse({"cuenta_id": cuenta.id, "range": rango, "points": points})


@require_http_methods(["GET", "HEAD"])
def ticks_json(request):
    """
    Devuelve los últimos 50 ticks para el gráfico en tiempo real.
    """
    cuenta = Cuenta.objects.order_by("-updated_at").first()
    if not cuenta:
        return JsonResponse({"cuenta_id": None, "ticks": []})
    
    # Obtener todos los ticks ordenados por epoch descendente, luego tomar los últimos 50
    ticks_qs = (
        TickDerivSnapshot.objects.filter(cuenta=cuenta)
        .order_by("-epoch")[:50]
    )
    
    # Convertir a lista y ordenar por epoch ascendente para el gráfico
    ticks_list = []
    for tick_obj in ticks_qs:
        ticks_list.append({
            "precio": float(tick_obj.precio),
            "epoch": int(tick_obj.epoch),
        })
    
    # Ordenar por epoch ascendente (más antiguo primero)
    ticks_list.sort(key=lambda x: x["epoch"])
    
    return JsonResponse({"cuenta_id": cuenta.id, "ticks": ticks_list})


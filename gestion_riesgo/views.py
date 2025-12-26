from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.utils import timezone
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.db.models import F

from .models import Cuenta, OperacionDeriv


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
        {"cuenta": cuenta, "operaciones_deriv": operaciones_deriv},
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
            "ciclo_balance_inicio": cuenta.ciclo_balance_inicio,
            "ciclo_inicio_epoch": cuenta.ciclo_inicio_epoch,
            "ciclo_pausa_hasta_epoch": cuenta.ciclo_pausa_hasta_epoch,
            "ciclo_ultimo_evento": cuenta.ciclo_ultimo_evento,
            "ultimo_tick_epoch": cuenta.ultimo_tick_epoch,
            "ultimo_precio": cuenta.ultimo_precio,
            "senal_valor": cuenta.senal_valor,
            "senal_decision": cuenta.senal_decision,
            "senal_top_contribuciones": cuenta.senal_top_contribuciones,
            "updated_at": cuenta.updated_at,
        }
    return JsonResponse({"cuenta": cuenta_dict, "operaciones_deriv": ops_deriv})



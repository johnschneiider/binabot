from __future__ import annotations

from datetime import datetime, timezone as dt_timezone, date
import os
import re
import math
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse, FileResponse, HttpResponseNotFound, StreamingHttpResponse, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.db.utils import OperationalError
from django.db.models import Value
from django.db.models.functions import Coalesce

from .models import (
    Inversionista, RendimientoDiario, Liquidacion,
    BalanceInversionista, Cuenta, OperacionDeriv,
    Deposito, Retiro, RendimientoFondo,
    OperacionBinance, EstadisticasBinance,
    ConfiguracionEstrategia,
)
import json
import time
import queue

from .models import BalanceDerivSnapshot, Cuenta, OperacionDeriv, Operacion, TickDerivSnapshot, TickDerivHistorico
from django.contrib.auth import login
from django.contrib.auth.hashers import make_password
from subscriptions.models import Usuario
import subprocess

# cola para SSE
sse_queue = queue.Queue()

# Configuración SSE
SSE_INTERVAL = 1.0  # segundos entre cada evento


def _tail_lines(path: str, n: int) -> list[str]:
    """
    Retorna las últimas N líneas de un archivo (tail eficiente).
    Si no existe, retorna [].
    """
    try:
        n = max(1, int(n))
    except Exception:
        n = 200
    n = min(n, 2000)

    if not path or not os.path.exists(path):
        return []
    if not os.path.isfile(path):
        return []

    # Leer desde el final en bloques hasta reunir N líneas.
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            block_size = 8192
            data = b""
            pos = end
            while pos > 0 and data.count(b"\n") <= n:
                read_size = block_size if pos >= block_size else pos
                pos -= read_size
                f.seek(pos, os.SEEK_SET)
                data = f.read(read_size) + data
                if pos == 0:
                    break
            lines = data.splitlines()[-n:]
        return [ln.decode("utf-8", errors="replace") for ln in lines]
    except Exception:
        return []


def _parse_horas_bloqueadas(spec: str) -> set[int]:
    """
    spec: "2-3,22" (rangos inclusivos). Espacios/; permitidos.
    Retorna horas [0..23]. Entradas inválidas se ignoran.
    """
    raw = (spec or "").strip()
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        tok = part.strip()
        if not tok:
            continue
        if "-" in tok:
            a_s, b_s = tok.split("-", 1)
            try:
                a = int(a_s.strip())
                b = int(b_s.strip())
            except Exception:
                continue
            lo, hi = (a, b) if a <= b else (b, a)
            for h in range(lo, hi + 1):
                if 0 <= h <= 23:
                    out.add(h)
        else:
            try:
                h = int(tok)
            except Exception:
                continue
            if 0 <= h <= 23:
                out.add(h)
    return out


def _hora_local_actual() -> int:
    # TIME_ZONE del proyecto (ej: America/Bogota)
    return int(timezone.localtime(timezone.now()).hour)


def _proximo_horario_habil():
    """
    Calcula el tiempo hasta el próximo horario habilitado para operar.
    Retorna dict con:
    - disponible: True si está en horario permitido
    - segundos_restantes: segundos hasta el próximo horario (0 si está disponible)
    - hora_proxima: hora del próximo horario habilitado (None si ya está disponible)
    - mensaje: texto descriptivo
    """
    from datetime import timedelta
    
    horas_bloqueadas = _parse_horas_bloqueadas(str(getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""))
    hora_actual = _hora_local_actual()
    ahora = timezone.localtime(timezone.now())
    
    # Todas las horas del día
    todas_horas = set(range(24))
    horas_permitidas = todas_horas - horas_bloqueadas
    
    if hora_actual in horas_permitidas:
        return {
            "disponible": True,
            "segundos_restantes": 0,
            "hora_proxima": None,
            "mensaje": "Horario de operación activo",
        }
    
    # Buscar la próxima hora permitida
    hora_proxima = None
    for h in range(hora_actual + 1, 24):
        if h in horas_permitidas:
            hora_proxima = h
            break
    
    # Si no hay más horas hoy, buscar la primera de mañana
    if hora_proxima is None:
        for h in range(0, 24):
            if h in horas_permitidas:
                hora_proxima = h
                break
    
    # Calcular segundos hasta la próxima hora
    if hora_proxima is not None:
        # Hora objetivo hoy
        objetivo = ahora.replace(hour=hora_proxima, minute=0, second=0, microsecond=0)
        # Si ya pasó esa hora hoy, es para mañana
        if hora_proxima <= hora_actual:
            objetivo += timedelta(days=1)
        diferencia = objetivo - ahora
        segundos = int(diferencia.total_seconds())
    else:
        segundos = 0
    
    # Formatear mensaje
    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    
    if horas > 0:
        mensaje = f"{horas}h {minutos}m hasta horario habilitado"
    elif minutos > 0:
        mensaje = f"{minutos}m hasta horario habilitado"
    else:
        mensaje = "Próximo momento habilitado"
    
    return {
        "disponible": False,
        "segundos_restantes": segundos,
        "hora_proxima": hora_proxima,
        "mensaje": mensaje,
    }


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
    if len(profits) > 0:
        winrate = (wins / len(profits)) * 100.0
    else:
        winrate = 0.0
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

    # PAUSA_EDGE_HASTA_<epoch>
    m = re.match(r"^PAUSA_EDGE_HASTA_(\d+)$", rm)
    if m:
        return {"label": "PAUSA (edge guard)", "pausa_hasta_epoch": int(m.group(1))}

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


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def dashboard(request):
    """
    DASHBOARD WEB PARA MONITOREO (BALANCE + OPERACIONES) EN "TIEMPO REAL" (POLLING).
    """
    # Usar SOLO la cuenta del simbolo configurado para evitar mezclar dashboards (ej: R_10 vs R_100).
    cuenta = Cuenta.objects.filter(simbolo=str(getattr(settings, "DERIV_SYMBOL", "") or "").strip()).order_by(
        "-ultimo_tick_epoch", "-updated_at"
    ).first()
    
    # Operaciones REALES de Deriv
    operaciones_deriv = (
        OperacionDeriv.objects.select_related("cuenta")
        .filter(creada_por_bot=True)
        .annotate(duracion_segundos=F("closed_epoch") - F("opened_epoch"))
        .order_by("-updated_at")[:50]
    )
    
    # Marcar como tipo REAL
    for op in operaciones_deriv:
        op.tipo_cuenta = "REAL"
        epoch_ref = op.closed_epoch or op.opened_epoch
        op.fecha_hora = _fecha_hora_colombia_desde_epoch(int(epoch_ref) if epoch_ref else None)

    # Operaciones PAPER/DEMO internas
    operaciones_paper = (
        Operacion.objects.filter(cuenta=cuenta)
        .annotate(duracion_segundos=F("closed_epoch") - F("opened_epoch"))
        .order_by("-updated_at")[:50]
    )
    
    # Marcar como tipo PAPER
    for op in operaciones_paper:
        op.tipo_cuenta = "PAPER"
        epoch_ref = op.closed_epoch or op.opened_epoch
        op.fecha_hora = _fecha_hora_colombia_desde_epoch(int(epoch_ref) if epoch_ref else None)
    
    # Combinar ambas listas
    todas_operaciones = list(operaciones_deriv) + list(operaciones_paper)
    # Ordenar por fecha/hora descendente
    todas_operaciones.sort(key=lambda x: x.fecha_hora or "", reverse=True)
    # Limitar a 50
    todas_operaciones = todas_operaciones[:50]

    horas_bloqueadas = _parse_horas_bloqueadas(str(getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""))
    hora_local_actual = _hora_local_actual()
    horario_bloqueado = bool(horas_bloqueadas and (hora_local_actual in horas_bloqueadas))
    
    # Info de horario para el template
    info_horario = _proximo_horario_habil()

    return render(
        request,
        "gestion_riesgo/dashboard.html",
        {
            "cuenta": cuenta,
            "operaciones": todas_operaciones,
            "winrate_ult15": _winrate_ultimas_deriv(n=15),
            "hora_local_actual": hora_local_actual,
            "horario_bloqueado": horario_bloqueado,
            "horario_info": info_horario,
            "horas_bloqueadas": sorted(list(horas_bloqueadas)),
        },
    )


@require_http_methods(["GET"])
def scatter_ticks_png(request):
    """
    Devuelve el PNG generado por el comando `graficar_ticks`.
    Ruta esperada: BASE_DIR/plots/scatter_ticks.png
    """
    try:
        base = Path(getattr(settings, "BASE_DIR", Path(".")))
    except Exception:
        base = Path(".")
    png_path = (base / "plots" / "scatter_ticks.png").resolve()
    if not png_path.exists() or not png_path.is_file():
        return HttpResponseNotFound("No se encontró scatter_ticks.png. Genera primero con manage.py graficar_ticks.")
    try:
        download = str(request.GET.get("download", "")).strip().lower() in {"1", "true", "yes", "y", "download"}
        return FileResponse(
            open(png_path, "rb"),
            content_type="image/png",
            as_attachment=download,
            filename="scatter_ticks.png",
        )
    except Exception:
        return HttpResponseNotFound("No se pudo leer scatter_ticks.png.")


@require_http_methods(["GET"])
def ticks_scatter_json(request):
    """
    Devuelve puntos de ticks downsampleados para scatter interactivo.
    Parámetros opcionales:
      - max: máximo de puntos por símbolo (default 20000)
      - symbols: lista separada por coma (default: R_10,R_100)
    """
    try:
        max_points = max(1000, min(100_000, int(request.GET.get("max", 20000))))
    except Exception:
        max_points = 20000

    raw_symbols = str(request.GET.get("symbols") or "R_10,R_100")
    symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()]
    if not symbols:
        symbols = ["R_10", "R_100"]

    payload = []
    for sym in symbols:
        qs = (
            TickDerivHistorico.objects.filter(cuenta__simbolo=sym)
            .order_by("epoch")
            .values_list("epoch", "precio")
        )
        total = qs.count()
        if total == 0:
            payload.append({"symbol": sym, "total": 0, "sampled": 0, "points": []})
            continue
        step = max(1, math.ceil(total / max_points))
        pts = []
        idx = 0
        for epoch, precio in qs.iterator(chunk_size=5000):
            if idx % step == 0:
                pts.append({"t": int(epoch) * 1000, "p": float(precio)})
            idx += 1
        payload.append({"symbol": sym, "total": total, "sampled": len(pts), "points": pts, "step": step})

    return JsonResponse({"symbols": payload})


@require_http_methods(["GET"])
def train_status_json(request):
    """
    Lee el estado del entrenamiento escrito por entrenar_lightgbm (train_status_<symbol>.json).
    """
    sym = str(request.GET.get("symbol") or "R_10").strip()
    try:
        base = Path(getattr(settings, "BASE_DIR", Path(".")))
    except Exception:
        base = Path(".")
    status_path = (base / "models" / f"train_status_{sym}.json").resolve()
    if not status_path.exists():
        return JsonResponse({"status": "unknown", "progress": 0.0, "message": "Sin estado"})
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JsonResponse(data)
    except Exception:
        return JsonResponse({"status": "error", "progress": 0.0, "message": "No se pudo leer estado"})


@require_http_methods(["GET"])
def train_start(request):
    """
    Lanza entrenamiento en background (nohup) para el símbolo indicado.
    Params: ?symbol=R_10|R_100
    """
    sym = str(request.GET.get("symbol") or "R_10").strip().upper()
    if sym not in {"R_10", "R_100"}:
        return JsonResponse({"status": "error", "message": "Símbolo no soportado"}, status=400)
    try:
        base = Path(getattr(settings, "BASE_DIR", Path("."))).resolve()
    except Exception:
        base = Path(".").resolve()

    try:
        logs_dir = base / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"train_{sym}.log"
        # Lanzamos en background y devolvemos el PID
        proc = subprocess.Popen(
            [
                str(base / ".venv" / "bin" / "python"),
                "manage.py",
                "entrenar_lightgbm",
                "--symbol",
                sym,
                "--horizon",
                "10",
                "--max-points",
                "400000",
                "--outdir",
                "models",
            ],
            cwd=base,
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
        )
        return JsonResponse({"status": "started", "pid": proc.pid, "symbol": sym, "log": str(log_file)})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@require_http_methods(["GET", "HEAD"])
def estado_json(request):
    """
    ENDPOINT PARA POLLING DESDE EL FRONTEND.
    Soporta múltiples activos: R_10 y R_100.
    """
    # Obtener datos de ambos activos: R_10 y R_100
    simbolos = ["R_10", "R_100"]
    cuentas_dict = {}
    ticks_dict = {}
    
    for simbolo in simbolos:
        cuenta = Cuenta.objects.filter(simbolo=simbolo).order_by(
            "-ultimo_tick_epoch", "-updated_at"
        ).first()
        
        if cuenta:
            now_epoch = int(timezone.now().timestamp())
            pausa_hasta_epoch = int(cuenta.ciclo_pausa_hasta_epoch) if cuenta.ciclo_pausa_hasta_epoch is not None else None
            dt_pausa_local = _fecha_hora_colombia_desde_epoch(pausa_hasta_epoch) if pausa_hasta_epoch else None
            pausa_restante_seg = max(0, int(pausa_hasta_epoch - now_epoch)) if pausa_hasta_epoch else None

            riesgo_ui = _riesgo_motivo_ui(cuenta.riesgo_motivo)
            pausa_epoch_from_motivo = riesgo_ui.get("pausa_hasta_epoch")
            if pausa_epoch_from_motivo:
                pausa_hasta_epoch = int(pausa_epoch_from_motivo)
                dt_pausa_local = _fecha_hora_colombia_desde_epoch(pausa_hasta_epoch)
                pausa_restante_seg = max(0, int(pausa_hasta_epoch - now_epoch))

            try:
                dt_ciclo_inicio = _fecha_hora_colombia_desde_epoch(cuenta.ciclo_inicio_epoch) if cuenta.ciclo_inicio_epoch else None
            except Exception:
                dt_ciclo_inicio = None
            try:
                dt_ultimo_tick = _fecha_hora_colombia_desde_epoch(cuenta.ultimo_tick_epoch) if cuenta.ultimo_tick_epoch else None
            except Exception:
                dt_ultimo_tick = None

            horas_bloqueadas = _parse_horas_bloqueadas(str(getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""))
            hora_local_actual = _hora_local_actual()
            horario_bloqueado = bool(horas_bloqueadas and (hora_local_actual in horas_bloqueadas))
            
            # Info de horario para cuenta regresiva
            info_horario = _proximo_horario_habil()

            cuentas_dict[simbolo] = {
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
                "senal_top_contribuciones": cuenta.senal_top_contribuciones if cuenta.senal_top_contribuciones else [],
                "updated_at": cuenta.updated_at.isoformat() if cuenta.updated_at else None,
                "winrate_ult15": _winrate_ultimas_deriv(n=15),
                "hora_local_actual": hora_local_actual,
                "horario_bloqueado": horario_bloqueado,
                "horas_bloqueadas": sorted(list(horas_bloqueadas)),
                "horario_disponible": info_horario["disponible"],
                "horario_segundos_restantes": info_horario["segundos_restantes"],
                "horario_hora_proxima": info_horario["hora_proxima"],
                "horario_mensaje": info_horario["mensaje"],
                "volatilidad_100": next((x.get("x") for x in (cuenta.senal_top_contribuciones or []) if x.get("variable") == "volatilidad_100"), None),
                "ema_50": next((x.get("x") for x in (cuenta.senal_top_contribuciones or []) if x.get("variable") == "ema_50"), None),
                "ema_100": next((x.get("x") for x in (cuenta.senal_top_contribuciones or []) if x.get("variable") == "ema_100"), None),
                # Control manual del bot
                "bot_activo": bool(getattr(cuenta, "bot_activo", True)),
                # Colector de ticks (histórico)
                "ticks_colector_activo": bool(getattr(cuenta, "ticks_colector_activo", False)),
                "ticks_colector_total": int(getattr(cuenta, "ticks_colector_total", 0) or 0),
                "ticks_colector_ultimo_epoch": int(getattr(cuenta, "ticks_colector_ultimo_epoch", 0) or 0) or None,
            }
            
            # Obtener ticks para este activo
            ticks_window = 200
            if ticks_window < 10:
                ticks_window = 10
            ticks_qs = (
                TickDerivSnapshot.objects.filter(cuenta=cuenta)
                .order_by("-epoch")[:ticks_window]
            )
            ticks_list = []
            for tick_obj in ticks_qs:
                ticks_list.append({
                    "precio": float(tick_obj.precio),
                    "epoch": int(tick_obj.epoch),
                })
            ticks_list.sort(key=lambda x: x["epoch"])
            ticks_dict[simbolo] = ticks_list
    
    # Mantener compatibilidad: usar R_10 como cuenta principal para operaciones
    cuenta_principal = Cuenta.objects.filter(simbolo="R_10").order_by(
        "-ultimo_tick_epoch", "-updated_at"
    ).first()
    # Obtener operaciones de ambos activos
    ops_deriv = list(
        # Orden estable por “tiempo real” del contrato (no por updated_at),
        # para evitar que el top-50 oscile si el bot vuelve a tocar operaciones viejas.
        OperacionDeriv.objects.annotate(epoch_ref=Coalesce("closed_epoch", "opened_epoch", Value(0)))
        .order_by("-epoch_ref", "-updated_at")
        # OJO: `profit_table` puede venir sin `symbol`; en ese caso NO queremos perder visibilidad en el dashboard.
        # Filtramos por la cuenta relacionada (más confiable) en vez del campo `simbolo` del registro.
        .filter(creada_por_bot=True, cuenta__simbolo__in=["R_10", "R_100"])
        .annotate(duracion_segundos=F("closed_epoch") - F("opened_epoch"))
        .values(
            "id",
            "simbolo",
            "contract_id",
            "contract_type",
            "estado",
            "profit",
            "entry_spot",
            "exit_spot",
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
        op["tipo_cuenta"] = "REAL"
    
    # Obtener operaciones PAPER (internas/demo)
    ops_paper = list(
        Operacion.objects.filter(cuenta__simbolo__in=["R_10", "R_100"])
        .annotate(epoch_ref=Coalesce("closed_epoch", "opened_epoch", Value(0)))
        .order_by("-epoch_ref")
        .annotate(duracion_segundos=F("closed_epoch") - F("opened_epoch"))
        .values(
            "id",
            "simbolo",
            "estado",
            "pnl_realizado",
            "precio_entrada",
            "precio_salida",
            "direccion",
            "opened_epoch",
            "closed_epoch",
            "duracion_segundos",
            "updated_at",
        )[:50]
    )
    for op in ops_paper:
        epoch_ref = op.get("closed_epoch") or op.get("opened_epoch")
        dt_local = _fecha_hora_colombia_desde_epoch(int(epoch_ref) if epoch_ref else None)
        op["fecha_hora"] = dt_local.strftime("%Y-%m-%d %H:%M:%S") if dt_local else None
        op["tipo_cuenta"] = "PAPER"
        op["contract_type"] = op.get("direccion", "")
        op["profit"] = op.get("pnl_realizado")
        op["entry_spot"] = op.get("precio_entrada")
        op["exit_spot"] = op.get("precio_salida")
    
    # Combinar operaciones
    todas_ops = ops_deriv + ops_paper
    todas_ops.sort(key=lambda x: x.get("fecha_hora") or "", reverse=True)
    todas_ops = todas_ops[:50]
    
    # Mantener compatibilidad: cuenta principal es R_10
    cuenta_dict = cuentas_dict.get("R_10")
    
    # Debug: contar total de operaciones
    total_ops_deriv = OperacionDeriv.objects.filter(creada_por_bot=True, cuenta__simbolo__in=["R_10", "R_100"]).count()
    total_ops_paper = Operacion.objects.filter(cuenta__simbolo__in=["R_10", "R_100"]).count()
    
    return JsonResponse({
        "cuenta": cuenta_dict,
        "cuentas": cuentas_dict,
        "operaciones": todas_ops,
        "operaciones_deriv": ops_deriv,
        "operaciones_paper": ops_paper,
        "ticks": ticks_dict.get("R_10", []),
        "ticks_por_activo": ticks_dict,
        "_debug": {
            "ops_deriv": total_ops_deriv,
            "ops_paper": total_ops_paper,
            "ops_total": len(todas_ops),
        },
    })


@require_http_methods(["POST"])
def ticks_colector_toggle(request):
    """
    Pausar / reanudar el colector de ticks (histórico) por símbolo.
    Body JSON:
      - simbolo: "R_10" | "R_100"
      - activo: true|false (opcional; si no viene, hace toggle)
    """
    try:
        import json

        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except Exception:
        payload = {}

    simbolo = str(payload.get("simbolo") or "").strip()
    if simbolo not in {"R_10", "R_100"}:
        return JsonResponse({"ok": False, "error": "simbolo inválido"}, status=400)

    cuenta = Cuenta.objects.filter(simbolo=simbolo).order_by("-ultimo_tick_epoch", "-updated_at").first()
    if not cuenta:
        return JsonResponse({"ok": False, "error": "no hay cuenta"}, status=404)

    if "activo" in payload:
        nuevo = bool(payload.get("activo"))
    else:
        nuevo = not bool(getattr(cuenta, "ticks_colector_activo", False))

    Cuenta.objects.filter(id=cuenta.id).update(ticks_colector_activo=nuevo)

    cuenta_ref = Cuenta.objects.filter(id=cuenta.id).values(
        "id",
        "simbolo",
        "ticks_colector_activo",
        "ticks_colector_total",
        "ticks_colector_ultimo_epoch",
    ).first()
    return JsonResponse({"ok": True, "cuenta": cuenta_ref})


@require_http_methods(["GET", "HEAD"])
def balance_json(request):
    """
    Serie temporal del balance (para gráfica).

    Filtros:
    - range=hour  => últimos 60 minutos
    - range=day   => últimas 2 horas
    - range=24h    => últimas 24 horas
    - range=week  => últimos 7 días
    - range=month => últimas 4 semanas
    """
    rango = (request.GET.get("range") or "hour").strip().lower()
    ahora = timezone.now()

    if rango == "hour":
        desde = ahora - timezone.timedelta(minutes=60)
    elif rango == "day":
        desde = ahora - timezone.timedelta(hours=2)
    elif rango == "24h":
        desde = ahora - timezone.timedelta(hours=24)
    elif rango == "week":
        desde = ahora - timezone.timedelta(days=7)
    elif rango == "month":
        desde = ahora - timezone.timedelta(days=28)
    else:
        # fallback seguro
        desde = ahora - timezone.timedelta(minutes=60)

    # Usar la cuenta con el último tick más reciente (más precisa que updated_at)
    cuenta = Cuenta.objects.filter(simbolo=str(getattr(settings, "DERIV_SYMBOL", "") or "").strip()).order_by(
        "-ultimo_tick_epoch", "-updated_at"
    ).first()
    if not cuenta:
        return JsonResponse({"cuenta_id": None, "points": []})

    try:
        qs = (
            BalanceDerivSnapshot.objects.filter(cuenta_id=cuenta.id, created_at__gte=desde)
            .order_by("created_at")
            .values("created_at", "balance", "moneda")
        )
    except OperationalError:
        # Si faltan migraciones / tabla no existe, no tumbar el dashboard.
        return JsonResponse(
            {
                "cuenta_id": cuenta.id,
                "range": rango,
                "points": [],
                "error": "BalanceDerivSnapshot no está disponible (¿faltan migraciones? Ejecuta: python manage.py migrate).",
            },
            status=200,
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
    Devuelve los últimos N ticks para el gráfico en tiempo real.
    """
    # Usar la cuenta con el último tick más reciente (más precisa que updated_at)
    cuenta = Cuenta.objects.filter(simbolo=str(getattr(settings, "DERIV_SYMBOL", "") or "").strip()).order_by(
        "-ultimo_tick_epoch", "-updated_at"
    ).first()
    if not cuenta:
        return JsonResponse({"cuenta_id": None, "ticks": []})
    
    ticks_window = 200  # Guardar últimos 200 ticks
    if ticks_window < 10:
        ticks_window = 10
    # Obtener todos los ticks ordenados por epoch descendente, luego tomar los últimos N
    ticks_qs = (
        TickDerivSnapshot.objects.filter(cuenta=cuenta)
        .order_by("-epoch")[:ticks_window]
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


@require_http_methods(["GET", "HEAD"])
def logs_json(request):
    """
    Devuelve las últimas líneas de logs del bot/server para ver "cómo piensa".
    Lee de un archivo local que el bot va anexando.
    """
    try:
        lines = int(request.GET.get("lines") or 250)
    except Exception:
        lines = 250
    lines = max(50, min(lines, 1000))

    q = (request.GET.get("q") or "").strip()

    # Orden de prioridad: settings -> env -> default dentro del repo
    path = (
        str(getattr(settings, "BOT_RUNTIME_LOG_FILE", "") or "").strip()
        or str(os.environ.get("BOT_RUNTIME_LOG_FILE", "") or "").strip()
        or os.path.join(getattr(settings, "BASE_DIR", os.getcwd()), "logs", "runtime.log")
    )

    out = _tail_lines(path, lines)
    if q:
        q_low = q.lower()
        out = [ln for ln in out if q_low in ln.lower()]

    return JsonResponse(
        {
            "lines": out[-lines:],
            "meta": {
                "lines": int(lines),
                "filter": q,
                "file": os.path.basename(path) if path else None,
            },
        }
    )


@login_required
def dashboard_eurusd(request):
    """
    Dashboard específico para EURUSD con estrategia EMA 35 M5.
    """
    return render(request, "gestion_riesgo/dashboard_eurusd.html")


@require_http_methods(["GET"])
def sse_stream(request):
    """
    Server-Sent Events endpoint para actualizaciones en tiempo real.
    Envía datos de estado, ticks y operaciones.
    """
    def event_stream():
        last_ops_key = ""
        last_balance = None
        last_logs_hash = ""
        
        while True:
            try:
                # Obtener datos de estado
                simbolo = str(getattr(settings, "DERIV_SYMBOL", "") or "").strip() or "R_100"
                cuenta = Cuenta.objects.filter(simbolo=simbolo).order_by(
                    "-ultimo_tick_epoch", "-updated_at"
                ).first()
                
                data = {"type": "state", "timestamp": int(timezone.now().timestamp())}
                
                if cuenta:
                    now_epoch = int(timezone.now().timestamp())
                    pausa_hasta_epoch = int(cuenta.ciclo_pausa_hasta_epoch) if cuenta.ciclo_pausa_hasta_epoch else None
                    dt_pausa_local = _fecha_hora_colombia_desde_epoch(pausa_hasta_epoch) if pausa_hasta_epoch else None
                    pausa_restante_seg = max(0, int(pausa_hasta_epoch - now_epoch)) if pausa_hasta_epoch else None
                    
                    riesgo_ui = _riesgo_motivo_ui(cuenta.riesgo_motivo)
                    
                    try:
                        dt_ciclo_inicio = _fecha_hora_colombia_desde_epoch(cuenta.ciclo_inicio_epoch) if cuenta.ciclo_inicio_epoch else None
                    except:
                        dt_ciclo_inicio = None
                    try:
                        dt_ultimo_tick = _fecha_hora_colombia_desde_epoch(cuenta.ultimo_tick_epoch) if cuenta.ultimo_tick_epoch else None
                    except:
                        dt_ultimo_tick = None
                    
                    data["cuenta"] = {
                        "id": cuenta.id,
                        "simbolo": cuenta.simbolo,
                        "balance_deriv": float(cuenta.balance_deriv) if cuenta.balance_deriv else None,
                        "moneda_deriv": cuenta.moneda_deriv,
                        "capital_actual": float(cuenta.capital_actual) if cuenta.capital_actual else None,
                        "bloqueado": bool(cuenta.bloqueado),
                        "riesgo_motivo_ui": riesgo_ui.get("label") or cuenta.riesgo_motivo,
                        "ciclo_balance_inicio": float(cuenta.ciclo_balance_inicio) if cuenta.ciclo_balance_inicio else None,
                        "ciclo_inicio_local": dt_ciclo_inicio.strftime("%Y-%m-%d %H:%M:%S") if dt_ciclo_inicio else None,
                        "ciclo_pausa_hasta_local": dt_pausa_local.strftime("%Y-%m-%d %H:%M:%S") if dt_pausa_local else None,
                        "ciclo_pausa_restante_hhmmss": _fmt_hhmmss(pausa_restante_seg) if pausa_restante_seg else None,
                        "ultimo_tick_local": dt_ultimo_tick.strftime("%H:%M:%S") if dt_ultimo_tick else None,
                        "ultimo_precio": float(cuenta.ultimo_precio) if cuenta.ultimo_precio else None,
                        "senal_valor": float(cuenta.senal_valor) if cuenta.senal_valor else None,
                        "senal_decision": cuenta.senal_decision,
                        "senal_top_contribuciones": cuenta.senal_top_contribuciones if cuenta.senal_top_contribuciones else [],
                    }
                    
                    # Winrate
                    data["cuenta"]["winrate_ult15"] = _winrate_ultimas_deriv(n=15)
                    
                    # Horario bloqueado
                    horas_bloqueadas = _parse_horas_bloqueadas(str(getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""))
                    hora_local_actual = _hora_local_actual()
                    data["cuenta"]["hora_local_actual"] = hora_local_actual
                    data["cuenta"]["horario_bloqueado"] = bool(horas_bloqueadas and (hora_local_actual in horas_bloqueadas))
                    data["cuenta"]["horas_bloqueadas"] = sorted(list(horas_bloqueadas))
                
                # Obtener ticks por activo (estructura esperada por el frontend)
                ticks_window = 200
                ticks_por_activo = {}
                if cuenta:
                    ticks_qs = TickDerivSnapshot.objects.filter(cuenta=cuenta).order_by("-epoch")[:ticks_window]
                    ticks_por_activo[simbolo] = [{"precio": float(t.precio), "epoch": int(t.epoch)} for t in reversed(list(ticks_qs))]
                data["ticks_por_activo"] = ticks_por_activo
                
                # Obtener operaciones
                ops_qs = (
                    OperacionDeriv.objects.annotate(epoch_ref=Coalesce("closed_epoch", "opened_epoch", Value(0)))
                    .order_by("-epoch_ref", "-updated_at")
                    .filter(creada_por_bot=True, cuenta__simbolo=simbolo)
                    .annotate(duracion_segundos=F("closed_epoch") - F("opened_epoch"))
                    .values(
                        "id", "simbolo", "contract_id", "contract_type", "estado", "profit",
                        "entry_spot", "exit_spot", "umbral_usado", "opened_epoch", "closed_epoch",
                        "duracion_segundos", "updated_at",
                    )[:50]
                )
                
                ops_list = list(ops_qs)
                # Convert datetime objects to strings before building ops_key
                ops_key = str([(op.get("contract_id"), 
                               op.get("updated_at").isoformat() if op.get("updated_at") else None, 
                               op.get("estado"), op.get("profit")) for op in ops_list])
                
                if ops_key != last_ops_key:
                    last_ops_key = ops_key
                    for op in ops_list:
                        epoch_ref = op.get("closed_epoch") or op.get("opened_epoch")
                        dt_local = _fecha_hora_colombia_desde_epoch(int(epoch_ref) if epoch_ref else None)
                        op["fecha_hora"] = dt_local.strftime("%Y-%m-%d %H:%M:%S") if dt_local else None
                        # Convert updated_at datetime to string
                        if op.get("updated_at"):
                            op["updated_at"] = op["updated_at"].isoformat()
                    data["operaciones"] = ops_list
                    data["ops_changed"] = True
                else:
                    data["ops_changed"] = False
                
                # Obtener logs
                log_path = (
                    str(getattr(settings, "BOT_RUNTIME_LOG_FILE", "") or "").strip()
                    or str(os.environ.get("BOT_RUNTIME_LOG_FILE", "") or "").strip()
                    or os.path.join(getattr(settings, "BASE_DIR", os.getcwd()), "logs", "runtime.log")
                )
                log_lines = _tail_lines(log_path, 100)
                current_logs_hash = hash(tuple(log_lines[-20:])) if log_lines else ""
                
                if current_logs_hash != last_logs_hash:
                    last_logs_hash = current_logs_hash
                    data["logs"] = log_lines
                    data["logs_changed"] = True
                else:
                    data["logs_changed"] = False
                
                yield f"data: {json.dumps(data)}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            
            time.sleep(SSE_INTERVAL)
    
    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def estado_eurusd_json(request):
    """
    API para datos en tiempo real de EURUSD.
    """
    from .models import VelaEURUSD, TickEURUSD, OperacionBacktest
    from datetime import datetime, timezone as dt_timezone
    
    # Obtener último tick
    ultimo_tick = TickEURUSD.objects.first()
    
    # Obtener última vela
    ultima_vela = VelaEURUSD.objects.first()
    
    # Calcular EMA 35 desde las últimas 35+ velas
    velas = list(VelaEURUSD.objects.order_by("-epoch_inicio")[:50])
    ema35 = None
    if len(velas) >= 35:
        precios = [v.close for v in reversed(velas)]
        alpha = 2.0 / (35 + 1)
        ema35 = precios[0]
        for p in precios[1:]:
            ema35 = alpha * p + (1 - alpha) * ema35
    
    # Calcular tendencia
    tendencia = None
    pendiente = None
    if ultimo_tick and ema35:
        diff = ultimo_tick.precio - ema35
        if diff > 0.0001:
            tendencia = "ALCISTA"
            pendiente = diff / 100
        elif diff < -0.0001:
            tendencia = "BAJISTA"
            pendiente = diff / 100
        else:
            tendencia = "FLAT"
            pendiente = 0
    
    # Obtener operaciones de hoy
    hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    hoy_epoch = int(hoy_inicio.timestamp())
    
    ops_hoy = OperacionBacktest.objects.filter(epoch_entrada__gte=hoy_epoch)
    wins_hoy = ops_hoy.filter(resultado="WIN").count()
    losses_hoy = ops_hoy.filter(resultado="LOSS").count()
    winrate_hoy = (wins_hoy / ops_hoy.count() * 100) if ops_hoy.count() > 0 else 0
    
    # PnL total
    pnl_total = sum(op.pnl for op in OperacionBacktest.objects.all())
    
    # Capital
    capital = 100 + pnl_total
    
    # Obtener última señal (desde última vela procesada)
    senal = None
    senal_razon = "Sin datos suficientes"
    
    # Últimas operaciones
    ultimas_ops = OperacionBacktest.objects.order_by("-epoch_entrada")[:10]
    operaciones = []
    for op in ultimas_ops:
        fecha = datetime.fromtimestamp(op.epoch_entrada, tz=dt_timezone.utc)
        operaciones.append({
            "hora": fecha.strftime("%H:%M"),
            "direccion": op.direccion,
            "entrada": op.precio_entrada,
            "salida": op.precio_salida,
            "resultado": op.resultado,
            "pnl": op.pnl,
        })
    
    return JsonResponse({
        "precio": ultimo_tick.precio if ultimo_tick else None,
        "ema35": ema35,
        "tendencia": tendencia,
        "pendiente": pendiente,
        "senal": senal,
        "senal_razon": senal_razon,
        "hora": datetime.now().strftime("%H:%M:%S"),
        "ops_hoy": ops_hoy.count(),
        "wins_hoy": wins_hoy,
        "losses_hoy": losses_hoy,
        "winrate_hoy": winrate_hoy,
        "pnl_total": pnl_total,
        "capital": capital,
        "operaciones": operaciones,
    })


# ============================================================
# PORTAL DEL INVERSIONISTA
# ============================================================

@login_required
def portal_inversionista(request):
    """
    Dashboard principal del inversionista.
    Muestra capital, rendimiento, ganancias acumuladas y fee a pagar.
    """
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return redirect("gestion_riesgo:crear_inversionista")

    # Balance history (ultimos 90 dias)
    balance_history = (
        inv.balance_history.order_by("-fecha")[:90]
    )
    balance_history = list(reversed(balance_history))

    # Rendimientos diarios (ultimos 30 dias)
    rendimientos = list(
        inv.rendimientos_diarios.order_by("-fecha")[:30]
    )
    rendimientos = list(reversed(rendimientos))

    # Liquidaciones recientes
    liquidaciones = list(
        inv.liquidaciones.order_by("-fecha")[:10]
    )

    # Estadisticas
    dias_activos = inv.rendimientos_diarios.count()
    ganancia_total = float(inv.ganancia_acumulada)
    fee_pendiente = ganancia_total * (float(inv.fee_performance_pct) / 100.0)
    ganancia_neta = ganancia_total - fee_pendiente

    # Proyeccion (rendimiento diario promedio)
    if rendimientos:
        ultimos_7 = rendimientos[-7:] if len(rendimientos) >= 7 else rendimientos
        avg_daily = sum(float(r.rendimiento_pct) for r in ultimos_7) / len(ultimos_7)
    else:
        avg_daily = float(inv.rendimiento_diario_pct)

    dias_mes = 30
    ganancia_mes_estimada = float(inv.capital_actual) * ((1 + avg_daily / 100) ** dias_mes - 1)

    return render(request, "gestion_riesgo/portal_inversionista.html", {
        "inversionista": inv,
        "balance_history": balance_history,
        "rendimientos": rendimientos,
        "liquidaciones": liquidaciones,
        "dias_activos": dias_activos,
        "ganancia_total": ganancia_total,
        "fee_pendiente": fee_pendiente,
        "ganancia_neta": ganancia_neta,
        "avg_daily": avg_daily,
        "ganancia_mes_estimada": ganancia_mes_estimada,
    })


@login_required
def crear_inversionista(request):
    """
    Formulario para crear/editar perfil de inversionista.
    """
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        inv = None

    if request.method == "POST":
        capital = float(request.POST.get("capital_inicial", 0))
        nombre = request.POST.get("nombre", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        whatsapp = request.POST.get("whatsapp", "").strip()
        deriv_api_token = request.POST.get("deriv_api_token", "").strip()
        deriv_account_id = request.POST.get("deriv_account_id", "").strip()

        if not inv:
            inv = Inversionista(user=request.user)

        inv.nombre = nombre
        inv.telefono = telefono
        inv.whatsapp = whatsapp
        inv.deriv_api_token = deriv_api_token
        inv.deriv_account_id = deriv_account_id
        inv.capital_inicial = capital
        inv.capital_actual = capital
        inv.save()

        return redirect("gestion_riesgo:portal_inversionista")

    return render(request, "gestion_riesgo/crear_inversionista.html", {
        "inversionista": inv,
    })


@login_required
def api_rendimiento_inversionista(request):
    """
    API JSON para graficar rendimiento en tiempo real.
    """
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return JsonResponse({"error": "No existe"}, status=404)

    dias = int(request.GET.get("dias", 30))
    history = list(
        inv.balance_history.order_by("-fecha")[:dias]
    )
    history = list(reversed(history))

    labels = []
    capital_data = []
    ganancia_data = []

    for b in history:
        labels.append(b.fecha.strftime("%d %b"))
        capital_data.append(float(b.capital))
        ganancia_data.append(float(b.ganancia_acumulada))

    return JsonResponse({
        "labels": labels,
        "capital": capital_data,
        "ganancia": ganancia_data,
        "capital_actual": float(inv.capital_actual),
        "capital_inicial": float(inv.capital_inicial),
        "ganancia_acumulada": float(inv.ganancia_acumulada),
        "fee_pendiente": float(inv.ganancia_acumulada) * (float(inv.fee_performance_pct) / 100),
    })


@login_required
def admin_inversionistas(request):
    """
    Panel admin para ver todos los inversionistas (solo superusers).
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("Solo administradores.")

    invs = Inversionista.objects.select_related("user").order_by("-created_at")

    return render(request, "gestion_riesgo/admin_inversionistas.html", {
        "inversionistas": invs,
    })


@login_required
def liquidar_inversionista(request, inv_id):
    """
    Registrar una liquidacion de fee para un inversionista.
    Solo superusers o el propio inversionista.
    """
    if request.method == "POST":
        try:
            inv = Inversionista.objects.get(id=inv_id)
        except Inversionista.DoesNotExist:
            return JsonResponse({"error": "No existe"}, status=404)

        if not request.user.is_superuser and request.user != inv.user:
            return JsonResponse({"error": "Permiso denegado"}, status=403)

        ganancia = float(request.POST.get("ganancia_bruta", 0))
        monto = ganancia * (float(inv.fee_performance_pct) / 100.0)
        tipo = request.POST.get("tipo", Liquidacion.Tipo.COBRO_FEE)
        observaciones = request.POST.get("observaciones", "").strip()

        liq = Liquidacion.objects.create(
            inversionista=inv,
            tipo=tipo,
            ganancia_bruta=ganancia,
            fee_pct=float(inv.fee_performance_pct),
            monto=monto,
            observaciones=observaciones,
            fecha=date.today(),
            confirmado=False,
        )

        return redirect("gestion_riesgo:portal_inversionista")

    return JsonResponse({"error": "Metodo no permitido"}, status=405)


# ============================================================
# REGISTRO KYC
# ============================================================

@require_http_methods(["GET", "POST"])
def registro_inversionista(request):
    if request.user.is_authenticated:
        return redirect("gestion_riesgo:portal_inversionista")

    errors = {}

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        nombre = request.POST.get("nombre", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        fecha_nacimiento = request.POST.get("fecha_nacimiento", "").strip()
        nacionalidad = request.POST.get("nacionalidad", "").strip()
        genero = request.POST.get("genero", "N")
        documento = request.POST.get("documento_identidad", "").strip()
        capital_objetivo = request.POST.get("capital_objetivo", "0").strip()
        como_se_entero = request.POST.get("como_se_entero", "").strip()

        if not username:
            errors["username"] = "El nombre de usuario es requerido."
        elif Usuario.objects.filter(username=username).exists():
            errors["username"] = "Este nombre de usuario ya está registrado."
        elif len(username) < 3:
            errors["username"] = "Mínimo 3 caracteres."

        if not email:
            errors["email"] = "El correo es requerido."
        elif Usuario.objects.filter(email=email).exists():
            errors["email"] = "Este correo ya está registrado."
        elif not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            errors["email"] = "Correo inválido."

        if not password:
            errors["password"] = "La contraseña es requerida."
        elif len(password) < 8:
            errors["password"] = "Mínimo 8 caracteres."

        if password != password2:
            errors["password2"] = "Las contraseñas no coinciden."

        if not nombre:
            errors["nombre"] = "El nombre completo es requerido."

        if not telefono:
            errors["telefono"] = "El teléfono es requerido."

        dob = None
        if fecha_nacimiento:
            try:
                dob = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
            except ValueError:
                errors["fecha_nacimiento"] = "Formato de fecha inválido (YYYY-MM-DD)."

        cap_obj = 0.0
        if capital_objetivo:
            try:
                cap_obj = float(capital_objetivo)
            except ValueError:
                pass

        if not errors:
            user = Usuario.objects.create(
                username=username,
                email=email,
                password=make_password(password),
                first_name=nombre,
            )

            Inversionista.objects.create(
                user=user,
                nombre=nombre,
                telefono=telefono,
                fecha_nacimiento=dob,
                nacionalidad=nacionalidad,
                genero=genero,
                documento_identidad=documento,
                capital_objetivo=cap_obj,
                como_se_entero=como_se_entero,
                capital_inicial=0.0,
                capital_actual=0.0,
            )

            login(request, user)
            return redirect("gestion_riesgo:portal_inversionista")

    return render(request, "gestion_riesgo/registro.html", {"errors": errors})


# ============================================================
# PORTAL DEL INVERSIONISTA
# ============================================================

@login_required
def portal_inversionista(request):
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return redirect("gestion_riesgo:registro")

    cuenta = Cuenta.objects.first()
    balance_fondo = float(cuenta.balance_deriv) if cuenta and cuenta.balance_deriv else 0.0
    moneda = cuenta.moneda_deriv if cuenta else "USD"

    dias_activos = inv.balance_history.count()
    ganancia_total = float(inv.ganancia_acumulada)
    fee_pendiente = ganancia_total * 0.25
    ganancia_neta = ganancia_total - fee_pendiente
    rendimiento_pct = inv.rendimiento_pct

    depositos_confirmados = inv.depositos.filter(estado=Deposito.Estado.CONFIRMADO).count()
    retiros = inv.retiros.filter(estado__in=[Retiro.Estado.SOLICITADO, Retiro.Estado.EN_PROCESO]).count()

    return render(request, "gestion_riesgo/portal_inversionista.html", {
        "inversionista": inv,
        "balance_fondo": balance_fondo,
        "moneda": moneda,
        "dias_activos": dias_activos,
        "ganancia_total": ganancia_total,
        "fee_pendiente": fee_pendiente,
        "ganancia_neta": ganancia_neta,
        "rendimiento_pct": rendimiento_pct,
        "depositos_confirmados": depositos_confirmados,
        "retiros_pendientes": retiros,
    })


# ============================================================
# API: ESTADÍSTICAS DEL FONDO (para gráfico mensual)
# ============================================================

@login_required
def api_fondo_stats(request):
    meses = list(
        RendimientoFondo.objects.order_by("anno", "mes")[:24]
    )
    meses.reverse()

    labels = []
    rendimiento_data = []
    balance_data = []

    for m in meses:
        labels.append(f"{m.mes:02d}/{m.anno}")
        rendimiento_data.append(round(float(m.rendimiento_pct), 2))
        balance_data.append(round(float(m.balance_fin), 2))

    cuenta = Cuenta.objects.first()
    total_fondo = float(cuenta.balance_deriv) if cuenta and cuenta.balance_deriv else 0.0
    max_fondo = float(cuenta.max_balance_deriv_historico) if cuenta and cuenta.max_balance_deriv_historico else 0.0
    trades_total = sum(m.trades_count for m in meses)
    wins_total = sum(m.trades_wins for m in meses)
    wr_total = (wins_total / trades_total * 100) if trades_total > 0 else 0

    return JsonResponse({
        "labels": labels,
        "rendimiento_pct": rendimiento_data,
        "balance_fin": balance_data,
        "total_fondo": total_fondo,
        "max_fondo": max_fondo,
        "trades_total": trades_total,
        "winrate_total": round(wr_total, 1),
    })


# ============================================================
# API: BALANCE PARA NAVBAR
# ============================================================

@login_required
def api_navbar_balance(request):
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return JsonResponse({"capital": 0, "rendimiento_pct": 0, "capital_inicial": 0, "ganancia_acumulada": 0, "balance_fondo": 0})

    cuenta = Cuenta.objects.first()
    balance_fondo = float(cuenta.balance_deriv) if cuenta and cuenta.balance_deriv else 0.0

    return JsonResponse({
        "capital": float(inv.capital_actual),
        "capital_inicial": float(inv.capital_inicial),
        "ganancia_acumulada": float(inv.ganancia_acumulada),
        "rendimiento_pct": round(inv.rendimiento_pct, 2),
        "balance_fondo": balance_fondo,
    })


# ============================================================
# API: TASAS DE CAMBIO (base USD)
# ============================================================

EXCHANGE_RATES = {
    "USD": {"rate": 1.0, "symbol": "$", "flag": "🇺🇸", "code": "USD", "name": "Dólar estadounidense", "decimals": 2},
    "COP": {"rate": 4200.0, "symbol": "$", "flag": "🇨🇴", "code": "COP", "name": "Peso colombiano", "decimals": 0},
    "ARS": {"rate": 1200.0, "symbol": "$", "flag": "🇦🇷", "code": "ARS", "name": "Peso argentino", "decimals": 2},
    "MXN": {"rate": 20.0, "symbol": "$", "flag": "🇲🇽", "code": "MXN", "name": "Peso mexicano", "decimals": 2},
    "EUR": {"rate": 0.92, "symbol": "€", "flag": "🇪🇺", "code": "EUR", "name": "Euro", "decimals": 2},
    "GBP": {"rate": 0.79, "symbol": "£", "flag": "🇬🇧", "code": "GBP", "name": "Libra esterlina", "decimals": 2},
    "BRL": {"rate": 5.80, "symbol": "R$", "flag": "🇧🇷", "code": "BRL", "name": "Real brasileño", "decimals": 2},
    "CLP": {"rate": 950.0, "symbol": "$", "flag": "🇨🇱", "code": "CLP", "name": "Peso chileno", "decimals": 0},
}


def api_moneda(request):
    """
    Devuelve tasas de cambio y metadata de monedas disponibles.
    Base: USD = 1.0
    """
    return JsonResponse({"base": "USD", "rates": EXCHANGE_RATES})


def api_tasa(request):
    """
    Convierte un monto en USD a una moneda destino.
    GET params: monto, moneda (código)
    """
    try:
        monto = float(request.GET.get("monto", 0))
        moneda = request.GET.get("moneda", "USD").upper()
    except ValueError:
        return JsonResponse({"error": "Parámetros inválidos"}, status=400)

    if moneda not in EXCHANGE_RATES:
        return JsonResponse({"error": "Moneda no soportada"}, status=400)

    rate_info = EXCHANGE_RATES[moneda]
    rate = rate_info["rate"]
    convertido = round(monto * rate, rate_info["decimals"])

    return JsonResponse({
        "original": monto,
        "convertido": convertido,
        "moneda": moneda,
        "tasa": rate,
        "symbol": rate_info["symbol"],
        "decimals": rate_info["decimals"],
        "formatted": f"{rate_info['symbol']}{convertido:,.{rate_info['decimals']}f}".replace(",", "X").replace(".", ",").replace("X", "."),
    })


# ============================================================
# API: RENDIMIENTOS PROPIOS DEL INVERSIONISTA
# ============================================================

@login_required
def api_mis_rendimientos(request):
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return JsonResponse({"error": "No existe"}, status=404)

    dias = int(request.GET.get("dias", 90))
    history = list(
        inv.balance_history.order_by("fecha")[:dias]
    )

    labels = []
    capital_data = []
    ganancia_data = []
    rendimiento_pct_data = []

    for b in history:
        labels.append(b.fecha.strftime("%d %b"))
        capital_data.append(round(float(b.capital), 2))
        ganancia_data.append(round(float(b.ganancia_acumulada), 2))
        rendimiento_pct_data.append(round(float(b.rendimiento_dia_pct), 3))

    return JsonResponse({
        "labels": labels,
        "capital": capital_data,
        "ganancia": ganancia_data,
        "rendimiento_pct": rendimiento_pct_data,
        "capital_inicial": float(inv.capital_inicial),
        "capital_actual": float(inv.capital_actual),
        "rendimiento_pct_total": round(inv.rendimiento_pct, 2),
    })


# ============================================================
# API: CREAR SOLICITUD DE DEPÓSITO
# ============================================================

@login_required
def api_depositar(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return JsonResponse({"error": "No existe inversionista"}, status=404)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    monto = float(data.get("monto", 0))
    if monto < 10:
        return JsonResponse({"error": "El monto mínimo es $10 USD"}, status=400)

    bold_token = getattr(settings, "BOLD_API_TOKEN", "")
    bold_endpoint = getattr(settings, "BOLD_API_ENDPOINT", "")

    referencia = f"INV-{inv.id}-{int(time.time())}"

    if bold_token and bold_endpoint:
        try:
            import requests as req
            resp = req.post(
                bold_endpoint,
                headers={"Authorization": f"Bearer {bold_token}"},
                json={
                    "amount": monto,
                    "reference": referencia,
                    "currency": "USD",
                },
                timeout=15,
            )
            bold_data = resp.json()
            if bold_data.get("status") == "APPROVED":
                estado = Deposito.Estado.CONFIRMADO
                inv.capital_actual = float(inv.capital_actual) + monto
                inv.capital_inicial = float(inv.capital_inicial) + monto
                inv.save()
                notas = f"Confirmado vía Bold: {bold_data.get('transaction_id', '')}"
            else:
                estado = Deposito.Estado.PENDIENTE
                notas = f"Bold response: {bold_data}"
        except Exception as e:
            estado = Deposito.Estado.PENDIENTE
            notas = f"Error Bold: {str(e)[:200]}"
    else:
        estado = Deposito.Estado.PENDIENTE
        notas = "Bold no configurado — pendiente de confirmar manualmente"

    dep = Deposito.objects.create(
        inversionista=inv,
        monto=monto,
        referencia=referencia,
        estado=estado,
        notas=notas,
    )

    return JsonResponse({
        "ok": True,
        "id": dep.id,
        "referencia": referencia,
        "estado": estado,
        "monto": monto,
    })


# ============================================================
# API: CREAR SOLICITUD DE RETIRO
# ============================================================

@login_required
def api_retirar(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return JsonResponse({"error": "No existe inversionista"}, status=404)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    monto = float(data.get("monto", 0))
    destino = data.get("destino", "").strip()

    if monto < 10:
        return JsonResponse({"error": "El monto mínimo de retiro es $10 USD"}, status=400)

    if monto > float(inv.capital_actual):
        return JsonResponse({"error": "No tienes suficiente capital para este retiro"}, status=400)

    ret = Retiro.objects.create(
        inversionista=inv,
        monto=monto,
        destino=destino,
        estado=Retiro.Estado.SOLICITADO,
    )

    return JsonResponse({
        "ok": True,
        "id": ret.id,
        "estado": ret.estado,
        "monto": monto,
    })


# ============================================================
#  API: ACTIVAR/DESACTIVAR BOT
# ============================================================

@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_bot_toggle(request):
    """
    API para activar o desactivar el bot manualmente.
    GET: Returns current bot_activo status for all cuentas
         Can also toggle with ?cuenta_id=X&activo=true/false
    POST: Toggles bot_activo for specified cuenta_id
    """
    
    # Support GET toggle for simplicity
    if request.method == "GET":
        cuenta_id = request.GET.get("cuenta_id")
        activo = request.GET.get("activo")
        
        print(f"[BOT_TOGGLE] GET: cuenta_id={cuenta_id}, activo={activo}")
        
        if cuenta_id and activo is not None:
            try:
                cuenta = Cuenta.objects.get(id=int(cuenta_id))
                cuenta.bot_activo = activo.lower() in ("true", "1", "yes")
                cuenta.save()
                print(f"[BOT_TOGGLE] Saved: bot_activo={cuenta.bot_activo}")
                return JsonResponse({
                    "ok": True,
                    "cuenta_id": cuenta.id,
                    "simbolo": cuenta.simbolo,
                    "bot_activo": cuenta.bot_activo,
                })
            except Cuenta.DoesNotExist:
                return JsonResponse({"error": "Cuenta no encontrada"}, status=404)
            except Exception as e:
                print(f"[BOT_TOGGLE] Error: {e}")
                return JsonResponse({"error": str(e)}, status=500)
        cuentas = Cuenta.objects.all()
        return JsonResponse({
            "cuentas": {
                c.simbolo: {
                    "id": c.id,
                    "bot_activo": c.bot_activo,
                    "balance": c.balance_deriv,
                    "bloqueado": c.bloqueado,
                }
                for c in cuentas
            }
        })
    
    # POST - Toggle
    try:
        data = json.loads(request.body) if request.body else request.POST
    except Exception:
        data = request.POST
    
    cuenta_id = data.get("cuenta_id")
    activo = data.get("activo")  # True/False
    
    if cuenta_id is None:
        return JsonResponse({"error": "cuenta_id requerido"}, status=400)
    
    try:
        cuenta = Cuenta.objects.get(id=cuenta_id)
    except Cuenta.DoesNotExist:
        return JsonResponse({"error": "Cuenta no encontrada"}, status=404)
    
    if activo is not None:
        cuenta.bot_activo = bool(activo)
        cuenta.save()
    
    return JsonResponse({
        "ok": True,
        "cuenta_id": cuenta.id,
        "simbolo": cuenta.simbolo,
        "bot_activo": cuenta.bot_activo,
    })


# ============================================================
#  PÁGINA DE DEPÓSITO
# ============================================================

@login_required
def depositar_view(request):
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return redirect("gestion_riesgo:registro")

    depositos = list(
        inv.depositos.order_by("-fecha_creado")[:10]
    )

    cuenta = Cuenta.objects.first()
    balance_fondo = float(cuenta.balance_deriv) if cuenta and cuenta.balance_deriv else 0.0
    moneda = cuenta.moneda_deriv if cuenta else "USD"

    return render(request, "gestion_riesgo/depositar.html", {
        "inversionista": inv,
        "depositos": depositos,
        "balance_fondo": balance_fondo,
        "moneda": moneda,
    })


# ============================================================
#  PÁGINA DE RETIRO
# ============================================================

@login_required
def retirar_view(request):
    try:
        inv = request.user.inversionista
    except Inversionista.DoesNotExist:
        return redirect("gestion_riesgo:registro")

    retiros = list(
        inv.retiros.order_by("-fecha_solicitud")[:10]
    )

    cuenta = Cuenta.objects.first()
    balance_fondo = float(cuenta.balance_deriv) if cuenta and cuenta.balance_deriv else 0.0
    moneda = cuenta.moneda_deriv if cuenta else "USD"

    return render(request, "gestion_riesgo/retirar.html", {
        "inversionista": inv,
        "retiros": retiros,
        "balance_fondo": balance_fondo,
        "moneda": moneda,
    })


# ============================================================
#  DASHBOARD BINANCE - OPERACIONES FICTICIAS
# ============================================================

@login_required
def dashboard_binance(request):
    """
    Dashboard para mostrar operaciones ficticias de Binance.
    """
    from django.utils import timezone
    from datetime import datetime, timezone as dt_tz
    from decimal import Decimal
    from trading.models import BalanceGlobal
    
    # Obtener estadísticas por activo
    stats = EstadisticasBinance.objects.all().order_by("-profit_total")
    
    # Calcular totales
    total_ops = sum(s.total_ops for s in stats)
    total_wins = sum(s.wins for s in stats)
    total_profit = sum(float(s.profit_total) for s in stats)
    
    # Obtener balance global unificado
    balance_global = BalanceGlobal.get_balance_float()
    capital_inicial = float(BalanceGlobal.get_balance().capital_inicial)
    
    # Win rate global
    wr_global = (total_wins / total_ops * 100) if total_ops > 0 else 0
    
    # Últimas 50 operaciones para historial
    historial_ops = OperacionBinance.objects.all().order_by("-created_at")[:50]
    
    # Datos para gráfico de balance usando balance global
    todas_ops = OperacionBinance.objects.all().order_by("created_at")
    chart_labels = []
    chart_balance = []
    balance_acumulado = capital_inicial
    
    for op in todas_ops:
        balance_acumulado += float(op.profit)
        chart_labels.append(op.created_at.strftime("%H:%M:%S"))
        chart_balance.append(round(balance_acumulado, 2))
    
    # Verificar si bot está activo (por defecto True por ahora)
    bot_activo = True
    
    # Hora actual
    ahora = timezone.localtime(timezone.now())
    
    return render(request, "gestion_riesgo/dashboard_binance.html", {
        "stats": stats,
        "total_ops": total_ops,
        "total_wins": total_wins,
        "wr_global": wr_global,
        "total_profit": total_profit,
        "balance_ficticio": balance_global,
        "capital_inicial": capital_inicial,
        "historial_ops": historial_ops,
        "ultimas_ops": historial_ops[:20],
        "bot_activo": bot_activo,
        "ahora": ahora,
        "chart_labels": json.dumps(chart_labels),
        "chart_balance": json.dumps(chart_balance),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_guardar_operacion_binance(request):
    """
    API para guardar operaciones ficticias de Binance.
    """
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
    
    # Obtener o crear estadísticas del activo
    from decimal import Decimal
    stats, created = EstadisticasBinance.objects.get_or_create(
        simbolo=simbolo,
        defaults={
            "balance_ficticio": Decimal("1000"),
        }
    )
    
    # Actualizar estadísticas
    stats.total_ops += 1
    if es_win:
        stats.wins += 1
        stats.win_streak += 1
        stats.loss_streak = 0
        stats.max_win_streak = max(stats.max_win_streak, stats.win_streak)
    else:
        stats.losses += 1
        stats.loss_streak += 1
        stats.win_streak = 0
        stats.max_loss_streak = max(stats.max_loss_streak, stats.loss_streak)
    
    # Convertir profit a Decimal antes de sumar
    from decimal import Decimal
    profit_decimal = Decimal(str(profit))
    stats.profit_total += profit_decimal
    stats.balance_ficticio += profit_decimal
    stats.ultima_operacion = timezone.now()
    stats.save()
    
    # Actualizar balance global unificado
    from trading.models import BalanceGlobal
    BalanceGlobal.actualizar_balance(profit)
    
    # Guardar operación
    operacion = OperacionBinance.objects.create(
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
def api_guardar_tick_binance(request):
    """
    API para guardar ticks de precio de Binance.
    """
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
    
    simbolo = data.get("simbolo", "").upper()
    precio = data.get("precio", 0)
    
    if not simbolo or not precio:
        return JsonResponse({"error": "simbolo y precio requeridos"}, status=400)
    
    # Guardar tick (solo los últimos 200 por símbolo)
    from .models import TickBinance
    from decimal import Decimal
    
    TickBinance.objects.create(
        simbolo=simbolo,
        precio=Decimal(str(precio))
    )
    
    # Eliminar ticks viejos (mantener solo últimos 200 por símbolo)
    ticks_viejos = TickBinance.objects.filter(simbolo=simbolo).order_by('-timestamp')[200:]
    if ticks_viejos:
        TickBinance.objects.filter(
            id__in=[t.id for t in ticks_viejos]
        ).delete()
    
    return JsonResponse({"ok": True})


@require_http_methods(["GET"])
def api_estado_binance(request):
    """
    API para obtener estado actual del bot de Binance.
    """
    stats = EstadisticasBinance.objects.all().order_by("-profit_total")
    
    total_ops = sum(s.total_ops for s in stats)
    total_wins = sum(s.wins for s in stats)
    wr_global = (total_wins / total_ops * 100) if total_ops > 0 else 0
    total_profit = sum(float(s.profit_total) for s in stats)
    balance_ficticio = sum(float(s.balance_ficticio) for s in stats)
    
    return JsonResponse({
        "bot_activo": True,
        "total_ops": total_ops,
        "total_wins": total_wins,
        "win_rate": wr_global,
        "total_profit": total_profit,
        "balance_ficticio": balance_ficticio,
        "activos": [
            {
                "simbolo": s.simbolo,
                "ops": s.total_ops,
                "wins": s.wins,
                "win_rate": s.win_rate,
                "profit": float(s.profit_total),
                "balance": float(s.balance_ficticio),
                "win_streak": s.win_streak,
                "loss_streak": s.loss_streak,
            }
            for s in stats
        ]
    })


# ============================================================
#  SSE: UPDATES EN TIEMPO REAL PARA BINANCE
# ============================================================

def sse_binance_stream(request):
    """
    Server-Sent Events para actualizaciones en tiempo real del dashboard Binance.
    """
    import time
    from django.db import connection
    
    def calcular_ema(prices, period):
        if len(prices) < period:
            return None
        ema = prices[0]
        multiplier = 2 / (period + 1)
        for p in prices[1:]:
            ema = p * multiplier + ema * (1 - multiplier)
        return ema
    
    def calcular_bollinger(prices, period=20, std_dev=2):
        if len(prices) < period:
            return None, None, None
        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        return sma + std_dev * std, sma, sma - std_dev * std
    
    def calcular_rsi(prices, period=14):
        if len(prices) < period + 1:
            return 50
        gains = []
        losses = []
        for i in range(len(prices) - period, len(prices)):
            diff = prices[i] - prices[i - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def calcular_adx(prices, period=14):
        if len(prices) < period + 1:
            return 15
        return 25
    
    def event_stream():
        last_id = 0
        while True:
            try:
                # Cerrar conexión vieja para evitar problemas
                connection.close()
                
                # SIEMPRE enviar datos (cada 2 segundos) para gráficos en tiempo real
                stats = EstadisticasBinance.objects.all()
                total_ops = sum(s.total_ops for s in stats)
                total_wins = sum(s.wins for s in stats)
                wr_global = (total_wins / total_ops * 100) if total_ops > 0 else 0
                total_profit = sum(float(s.profit_total) for s in stats)
                balance_ficticio = sum(float(s.balance_ficticio) for s in stats)
                
                # Datos para gráfico de balance por operación
                todas_ops = OperacionBinance.objects.all().order_by('created_at')
                balance_points = []
                bal = 1000
                for op in todas_ops:
                    bal += float(op.profit)
                    balance_points.append({
                        "x": f"#{op.num_operacion}",
                        "y": round(bal, 2)
                    })
                
                # Datos para gráfico de barras por activo
                activos_data = []
                for s in stats:
                    activos_data.append({
                        "simbolo": s.simbolo,
                        "profit": float(s.profit_total),
                        "ops": s.total_ops,
                        "wr": s.win_rate
                    })
                
                # Última operación
                ultima_op = OperacionBinance.objects.order_by('-created_at').first()
                op_data = None
                if ultima_op:
                    # Convertir a hora Colombia (UTC-5)
                    from datetime import timedelta
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
                        "wr_momento": float(ultima_op.win_rate_momento),
                        "hora": hora_colombia.strftime("%d-%m-%Y %H:%M:%S")
                    }
                
                # Enviar historial completo (últimas 50 operaciones)
                historial_data = []
                ultimas_ops = OperacionBinance.objects.order_by('-created_at')[:50]
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
                
                # Ticks de precios por activo (últimos 200 cada uno) + indicadores
                from .models import TickBinance
                simbolos = ["BTC", "ETH", "SOL", "XRP"]
                ticks_data = {}
                indicadores_data = {}
                
                for sym in simbolos:
                    ticks = TickBinance.objects.filter(
                        simbolo=sym
                    ).order_by('-timestamp')[:200]
                    ticks_list = [
                        {
                            "t": t.timestamp.strftime("%H:%M:%S"),
                            "p": float(t.precio)
                        }
                        for t in reversed(list(ticks))
                    ]
                    ticks_data[sym] = ticks_list
                    
                    # Calcular indicadores
                    if len(ticks_list) >= 60:
                        prices = [t["p"] for t in ticks_list]
                        
                        ema9 = calcular_ema(prices, 9)
                        ema21 = calcular_ema(prices, 21)
                        ema50 = calcular_ema(prices, 50)
                        rsi = calcular_rsi(prices, 14)
                        bb_sup, bb_mid, bb_inf = calcular_bollinger(prices, 20, 2)
                        
                        indicadores_data[sym] = {
                            "ema9": round(ema9, 2) if ema9 else None,
                            "ema21": round(ema21, 2) if ema21 else None,
                            "ema50": round(ema50, 2) if ema50 else None,
                            "rsi": round(rsi, 1) if rsi else None,
                            "bb_sup": round(bb_sup, 2) if bb_sup else None,
                            "bb_mid": round(bb_mid, 2) if bb_mid else None,
                            "bb_inf": round(bb_inf, 2) if bb_inf else None,
                        }
                
                # Señal activa reciente
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
                    "balance_points": balance_points[-100:],
                    "ultima_operacion": op_data,
                    "historial": historial_data,
                    "ticks": ticks_data,
                    "indicadores": indicadores_data,
                    "senal_activa": senal_activa,
                })
                
                yield f"data: {data}\n\n"
                
                # Esperar 2 segundos antes de enviar de nuevo
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
def api_configuracion_estrategia(request):
    """
    API para obtener y modificar la configuración de la estrategia.
    Soporta tipos: estricta, media, flexible
    """
    from django.views.decorators.http import require_http_methods
    
    tipo_param = request.GET.get('tipo')
    tipo_activo = ConfiguracionEstrategia.get_tipo_activo(mercado='binance')
    tipo = tipo_param if tipo_param else tipo_activo
    config = ConfiguracionEstrategia.get_activa(tipo=tipo, mercado='binance')
    
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            
            # Cambiar tipo de estrategia activa
            if "tipo" in data:
                nuevo_tipo = data["tipo"]
                ConfiguracionEstrategia.objects.filter(nombre='binance', tipo=nuevo_tipo).update(activa=True)
                ConfiguracionEstrategia.objects.filter(nombre='binance').exclude(tipo=nuevo_tipo).update(activa=False)
                config = ConfiguracionEstrategia.get_activa(tipo=nuevo_tipo, mercado='binance')
            
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
                "tipo_activo": config.tipo,
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
    
    # GET
    return JsonResponse({
        "tipo_activo": config.tipo,
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


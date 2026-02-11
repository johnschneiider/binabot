from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
import os
import re
import math
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse, FileResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models import F
from django.db.utils import OperationalError
from django.db.models import Value
from django.db.models.functions import Coalesce

from .models import BalanceDerivSnapshot, Cuenta, OperacionDeriv, TickDerivSnapshot, TickDerivHistorico
import subprocess


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


@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD"])
def dashboard(request):
    """
    DASHBOARD WEB PARA MONITOREO (BALANCE + OPERACIONES) EN "TIEMPO REAL" (POLLING).
    """
    # Usar SOLO la cuenta del símbolo configurado para evitar mezclar dashboards (ej: R_10 vs R_100).
    cuenta = Cuenta.objects.filter(simbolo=str(getattr(settings, "DERIV_SYMBOL", "") or "").strip()).order_by(
        "-ultimo_tick_epoch", "-updated_at"
    ).first()
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

    horas_bloqueadas = _parse_horas_bloqueadas(str(getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""))
    hora_local_actual = _hora_local_actual()
    horario_bloqueado = bool(horas_bloqueadas and (hora_local_actual in horas_bloqueadas))

    return render(
        request,
        "gestion_riesgo/dashboard.html",
        {
            "cuenta": cuenta,
            "operaciones_deriv": operaciones_deriv,
            "winrate_ult15": _winrate_ultimas_deriv(n=15),
            "hora_local_actual": hora_local_actual,
            "horario_bloqueado": horario_bloqueado,
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

    cmd = f"cd {base} && nohup {base}/.venv/bin/python manage.py entrenar_lightgbm --symbol {sym} --horizon 10 --max-points 400000 --outdir models > /tmp/train_{sym}.log 2>&1 & echo $!"
    try:
        proc = subprocess.Popen(["/bin/bash", "-lc", cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, _ = proc.communicate(timeout=5)
        pid = out.strip()
        return JsonResponse({"status": "started", "pid": pid, "symbol": sym})
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

            dt_ciclo_inicio = _fecha_hora_colombia_desde_epoch(cuenta.ciclo_inicio_epoch) if cuenta.ciclo_inicio_epoch else None
            dt_ultimo_tick = _fecha_hora_colombia_desde_epoch(cuenta.ultimo_tick_epoch) if cuenta.ultimo_tick_epoch else None

            horas_bloqueadas = _parse_horas_bloqueadas(str(getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""))
            hora_local_actual = _hora_local_actual()
            horario_bloqueado = bool(horas_bloqueadas and (hora_local_actual in horas_bloqueadas))

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
                "volatilidad_100": next((x.get("x") for x in (cuenta.senal_top_contribuciones or []) if x.get("variable") == "volatilidad_100"), None),
                "ema_50": next((x.get("x") for x in (cuenta.senal_top_contribuciones or []) if x.get("variable") == "ema_50"), None),
                "ema_100": next((x.get("x") for x in (cuenta.senal_top_contribuciones or []) if x.get("variable") == "ema_100"), None),
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
    
    # Mantener compatibilidad: cuenta principal es R_10
    cuenta_dict = cuentas_dict.get("R_10")
    
    # Debug: contar total de operaciones (con y sin filtro)
    total_ops_sin_filtro = OperacionDeriv.objects.filter(cuenta__simbolo__in=["R_10", "R_100"]).count()
    total_ops_con_filtro = OperacionDeriv.objects.filter(creada_por_bot=True, cuenta__simbolo__in=["R_10", "R_100"]).count()
    
    return JsonResponse({
        "cuenta": cuenta_dict,  # Compatibilidad con código existente
        "cuentas": cuentas_dict,  # Nuevo: datos de todos los activos
        "operaciones_deriv": ops_deriv,
        "ticks": ticks_dict.get("R_10", []),  # Compatibilidad
        "ticks_por_activo": ticks_dict,  # Nuevo: ticks por activo
        "_debug": {
            "ops_total_sin_filtro": total_ops_sin_filtro,
            "ops_total_con_filtro_creada_por_bot": total_ops_con_filtro,
            "ops_enviadas": len(ops_deriv),
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


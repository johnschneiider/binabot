from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import OuterRef, Q, Subquery
from django.db.utils import OperationalError

from gestion_riesgo.models import BalanceDerivSnapshot, Operacion, OperacionDeriv


def _tz() -> ZoneInfo:
    return ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")


def _parse_dt_local(s: str) -> datetime:
    """
    Acepta:
      - YYYY-MM-DD
      - YYYY-MM-DD HH:MM
      - YYYY-MM-DDTHH:MM[:SS]
    Si no trae tz, se interpreta en TIME_ZONE del proyecto.
    """
    raw = (s or "").strip()
    if not raw:
        raise ValueError("datetime vacío")
    raw = raw.replace("T", " ").strip()
    if len(raw) == 10:
        raw = raw + " 00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz())
    return dt


def _dt_from_epoch(epoch: Optional[int]) -> Optional[datetime]:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=_tz())
    except Exception:
        return None


def _safe_json(x: Any, *, compact: bool) -> str:
    if x is None:
        return ""
    try:
        if compact:
            return json.dumps(x, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)


def _cols_for_table(table: str) -> set[str]:
    with connection.cursor() as cur:
        return {c.name for c in connection.introspection.get_table_description(cur, table)}


class Command(BaseCommand):
    help = "Exporta operaciones históricas (Deriv/paper) a CSV o JSONL para análisis externo."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--tipo", choices=["deriv", "paper", "ambos"], default="deriv")
        parser.add_argument("--symbol", type=str, default=None, help="Filtra por símbolo (ej: R_100).")
        parser.add_argument("--solo-bot", action="store_true", help="Solo operaciones Deriv creada_por_bot=True.")
        parser.add_argument("--solo-cerradas", action="store_true", help="Solo operaciones cerradas con profit/PnL.")

        parser.add_argument("--desde", type=str, default=None, help="Inicio (local): YYYY-MM-DD[ HH:MM].")
        parser.add_argument("--hasta", type=str, default=None, help="Fin (local): YYYY-MM-DD[ HH:MM].")
        parser.add_argument("--ultimas", type=int, default=0, help="Exporta solo las últimas N operaciones (por cierre).")

        parser.add_argument("--formato", choices=["csv", "jsonl"], default="csv")
        parser.add_argument("--out", dest="out_path", type=str, required=True, help="Ruta de salida (ej: /tmp/ops.csv).")
        parser.add_argument(
            "--compact-json",
            action="store_true",
            help="En CSV/JSONL, serializa JSON sin espacios (mejor para tamaños grandes).",
        )
        parser.add_argument(
            "--incluir-balance-al-abrir",
            action="store_true",
            help="Incluye balance aproximado al abrir (último BalanceDerivSnapshot <= opened_epoch).",
        )

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        tipo = str(opts["tipo"])
        symbol = (opts.get("symbol") or "").strip() or None
        solo_bot = bool(opts.get("solo_bot"))
        solo_cerradas = bool(opts.get("solo_cerradas"))
        ultimas = int(opts.get("ultimas") or 0)
        formato = str(opts.get("formato") or "csv")
        out_path = str(opts.get("out_path") or "").strip()
        compact_json = bool(opts.get("compact_json"))
        incluir_balance_al_abrir = bool(opts.get("incluir_balance_al_abrir"))

        if not out_path:
            raise CommandError("--out es obligatorio")

        dt_desde = _parse_dt_local(opts["desde"]) if opts.get("desde") else None
        dt_hasta = _parse_dt_local(opts["hasta"]) if opts.get("hasta") else None
        if dt_desde and dt_hasta and dt_desde > dt_hasta:
            raise CommandError("--desde no puede ser mayor que --hasta")

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Detectar columnas reales en DB (robusto si faltan migraciones).
        cols_deriv = _cols_for_table(OperacionDeriv._meta.db_table)
        cols_paper = _cols_for_table(Operacion._meta.db_table)
        cols_snap = _cols_for_table(BalanceDerivSnapshot._meta.db_table) if incluir_balance_al_abrir else set()

        # ====== ARMAR QS DERIV ======
        deriv_rows: list[dict[str, Any]] = []
        if tipo in {"deriv", "ambos"}:
            q = Q()
            if symbol:
                q &= Q(simbolo=symbol)
            if solo_bot and "creada_por_bot" in cols_deriv:
                q &= Q(creada_por_bot=True)
            if solo_cerradas:
                q &= Q(estado=OperacionDeriv.Estado.CERRADA) & Q(profit__isnull=False)

            qs = OperacionDeriv.objects.filter(q)
            if dt_desde:
                epoch_desde = int(dt_desde.astimezone(ZoneInfo("UTC")).timestamp())
                qs = qs.filter(Q(opened_epoch__gte=epoch_desde) | Q(opened_epoch__isnull=True, created_at__gte=dt_desde))
            if dt_hasta:
                epoch_hasta = int(dt_hasta.astimezone(ZoneInfo("UTC")).timestamp())
                qs = qs.filter(Q(opened_epoch__lte=epoch_hasta) | Q(opened_epoch__isnull=True, created_at__lte=dt_hasta))

            # Orden por cierre si existe; si no, por id.
            if "closed_epoch" in cols_deriv:
                qs = qs.order_by("closed_epoch", "opened_epoch", "id")
            else:
                qs = qs.order_by("id")

            # Subquery: balance al abrir (último snapshot <= opened_epoch).
            if incluir_balance_al_abrir and {"cuenta_id", "epoch", "balance"}.issubset(cols_snap) and "opened_epoch" in cols_deriv:
                snap_qs = (
                    BalanceDerivSnapshot.objects.filter(cuenta_id=OuterRef("cuenta_id"), epoch__isnull=False)
                    .filter(epoch__lte=OuterRef("opened_epoch"))
                    .order_by("-epoch")
                )
                qs = qs.annotate(balance_al_abrir=Subquery(snap_qs.values("balance")[:1]))
            else:
                incluir_balance_al_abrir = False

            fields = [
                "id",
                "cuenta_id",
                "simbolo",
                "contract_id",
                "transaction_id",
                "creada_por_bot",
                "contract_type",
                "estado",
                "moneda",
                "buy_price",
                "sell_price",
                "payout",
                "profit",
                "opened_epoch",
                "closed_epoch",
                "created_at",
                "updated_at",
                "shortcode",
                "longcode",
            ]
            # Telemetría (puede faltar en DB antigua)
            for f in ["senal_valor", "umbral_usado", "pesos_usados", "senal_top_contribuciones"]:
                if f in cols_deriv:
                    fields.append(f)
            if incluir_balance_al_abrir:
                fields.append("balance_al_abrir")

            try:
                vals = list(qs.values(*fields))
            except OperationalError:
                # Si hay mismatch raro, degradamos a campos mínimos.
                basic = [f for f in fields if f in {"id", "cuenta_id", "simbolo", "contract_id", "contract_type", "estado", "profit", "buy_price", "opened_epoch", "closed_epoch", "created_at"}]
                vals = list(qs.values(*basic))

            if ultimas > 0:
                vals = vals[-ultimas:]

            for v in vals:
                opened_epoch = v.get("opened_epoch")
                closed_epoch = v.get("closed_epoch")
                opened_dt = _dt_from_epoch(opened_epoch)
                closed_dt = _dt_from_epoch(closed_epoch)
                row: dict[str, Any] = {
                    "tipo": "deriv",
                    "id": v.get("id"),
                    "cuenta_id": v.get("cuenta_id"),
                    "simbolo": v.get("simbolo", ""),
                    "contract_id": v.get("contract_id"),
                    "transaction_id": v.get("transaction_id"),
                    "creada_por_bot": v.get("creada_por_bot"),
                    "contract_type": v.get("contract_type", ""),
                    "estado": v.get("estado", ""),
                    "moneda": v.get("moneda", ""),
                    "buy_price": v.get("buy_price"),
                    "sell_price": v.get("sell_price"),
                    "payout": v.get("payout"),
                    "profit": v.get("profit"),
                    "opened_epoch": opened_epoch,
                    "closed_epoch": closed_epoch,
                    "opened_local": opened_dt.isoformat() if opened_dt else "",
                    "closed_local": closed_dt.isoformat() if closed_dt else "",
                    "hour_local": opened_dt.hour if opened_dt else "",
                    "weekday_local": opened_dt.weekday() if opened_dt else "",
                    "duration_sec": (int(closed_epoch) - int(opened_epoch)) if (closed_epoch and opened_epoch) else "",
                    "created_at": v.get("created_at").isoformat() if v.get("created_at") else "",
                    "updated_at": v.get("updated_at").isoformat() if v.get("updated_at") else "",
                    "shortcode": v.get("shortcode", ""),
                    "longcode": v.get("longcode", ""),
                    "senal_valor": v.get("senal_valor", ""),
                    "umbral_usado": v.get("umbral_usado", ""),
                    "pesos_usados_json": _safe_json(v.get("pesos_usados"), compact=compact_json) if "pesos_usados" in v else "",
                    "top_contribuciones_json": _safe_json(v.get("senal_top_contribuciones"), compact=compact_json)
                    if "senal_top_contribuciones" in v
                    else "",
                }
                if incluir_balance_al_abrir:
                    row["balance_al_abrir"] = v.get("balance_al_abrir", "")
                deriv_rows.append(row)

        # ====== ARMAR QS PAPER ======
        paper_rows: list[dict[str, Any]] = []
        if tipo in {"paper", "ambos"}:
            q = Q()
            if symbol:
                q &= Q(simbolo=symbol)
            if solo_cerradas:
                q &= Q(estado=Operacion.Estado.CERRADA) & Q(pnl_realizado__isnull=False)

            qs = Operacion.objects.filter(q)
            if dt_desde:
                epoch_desde = int(dt_desde.astimezone(ZoneInfo("UTC")).timestamp())
                qs = qs.filter(Q(opened_epoch__gte=epoch_desde) | Q(opened_epoch=0, created_at__gte=dt_desde))
            if dt_hasta:
                epoch_hasta = int(dt_hasta.astimezone(ZoneInfo("UTC")).timestamp())
                qs = qs.filter(Q(opened_epoch__lte=epoch_hasta) | Q(opened_epoch=0, created_at__lte=dt_hasta))

            qs = qs.order_by("closed_epoch", "opened_epoch", "id") if "closed_epoch" in cols_paper else qs.order_by("id")

            fields = [
                "id",
                "cuenta_id",
                "simbolo",
                "estado",
                "direccion",
                "precio_entrada",
                "precio_salida",
                "tamanio",
                "stop_distancia",
                "pnl_realizado",
                "motivo_cierre",
                "opened_epoch",
                "closed_epoch",
                "created_at",
                "updated_at",
            ]
            fields = [f for f in fields if f in cols_paper or f in {"id", "cuenta_id", "simbolo", "created_at", "updated_at"}]
            vals = list(qs.values(*fields))
            if ultimas > 0:
                vals = vals[-ultimas:]

            for v in vals:
                opened_epoch = v.get("opened_epoch")
                closed_epoch = v.get("closed_epoch")
                opened_dt = _dt_from_epoch(opened_epoch if opened_epoch else None)
                closed_dt = _dt_from_epoch(closed_epoch if closed_epoch else None)
                row = {
                    "tipo": "paper",
                    "id": v.get("id"),
                    "cuenta_id": v.get("cuenta_id"),
                    "simbolo": v.get("simbolo", ""),
                    "estado": v.get("estado", ""),
                    "direccion": v.get("direccion", ""),
                    "precio_entrada": v.get("precio_entrada", ""),
                    "precio_salida": v.get("precio_salida", ""),
                    "tamanio": v.get("tamanio", ""),
                    "stop_distancia": v.get("stop_distancia", ""),
                    "pnl_realizado": v.get("pnl_realizado", ""),
                    "motivo_cierre": v.get("motivo_cierre", ""),
                    "opened_epoch": opened_epoch,
                    "closed_epoch": closed_epoch,
                    "opened_local": opened_dt.isoformat() if opened_dt else "",
                    "closed_local": closed_dt.isoformat() if closed_dt else "",
                    "hour_local": opened_dt.hour if opened_dt else "",
                    "weekday_local": opened_dt.weekday() if opened_dt else "",
                    "duration_sec": (int(closed_epoch) - int(opened_epoch)) if (closed_epoch and opened_epoch) else "",
                    "created_at": v.get("created_at").isoformat() if v.get("created_at") else "",
                    "updated_at": v.get("updated_at").isoformat() if v.get("updated_at") else "",
                }
                paper_rows.append(row)

        rows = deriv_rows + paper_rows
        if not rows:
            self.stdout.write("No hay operaciones que cumplan los filtros.")
            return

        # Headers estables (unión de keys)
        headers: list[str] = sorted({k for r in rows for k in r.keys()})

        if formato == "csv":
            with out.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                w.writeheader()
                for r in rows:
                    w.writerow(r)
        elif formato == "jsonl":
            with out.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        else:
            raise CommandError(f"Formato no soportado: {formato}")

        self.stdout.write(f"[OK] Exportadas {len(rows)} filas → {out_path}")


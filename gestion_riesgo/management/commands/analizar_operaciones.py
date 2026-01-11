from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_riesgo.models import OperacionDeriv


def _dt_from_epoch(epoch: int | None, tz: ZoneInfo) -> str:
    if not epoch:
        return "-"
    try:
        dt = datetime.fromtimestamp(int(epoch), tz=tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


class Command(BaseCommand):
    help = "Analiza operaciones recientes del bot mostrando estadísticas y patrones."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--horas", type=int, default=24, help="Horas hacia atrás para analizar (default: 24)")
        parser.add_argument("--top", type=int, default=50, help="Máximo de operaciones a mostrar (default: 50)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        horas = int(opts.get("horas") or 24)
        top = int(opts.get("top") or 50)

        tz = ZoneInfo("America/Bogota")
        desde_dt = timezone.now() - timedelta(hours=horas)
        desde_epoch = int(desde_dt.timestamp())

        ops = (
            OperacionDeriv.objects.filter(creada_por_bot=True, opened_epoch__gte=desde_epoch)
            .order_by("-opened_epoch")
            .select_related("cuenta")[:top]
        )

        if not ops:
            self.stdout.write(f"No hay operaciones en las últimas {horas} horas.")
            return

        cerradas = [op for op in ops if op.estado == "CERRADA" and op.profit is not None]
        ganadas = [op for op in cerradas if op.profit > 0]
        perdidas = [op for op in cerradas if op.profit < 0]

        # ===== TABLA DETALLADA =====
        self.stdout.write(f"\n{'='*100}")
        self.stdout.write(f"ÚLTIMAS {len(ops)} OPERACIONES ({horas}h)")
        self.stdout.write(f"{'='*100}\n")

        headers = ["ID", "Hora Local", "Tipo", "Profit", "Estado", "Hora", "Señal", "Umbral"]
        fmt = "{:<5} {:<19} {:<5} {:<8} {:<8} {:<3} {:<10} {:<8}"
        self.stdout.write(fmt.format(*headers))
        self.stdout.write("-" * 100)

        for op in ops:
            hora_str = _dt_from_epoch(op.opened_epoch, tz)
            hora_local = datetime.fromtimestamp(op.opened_epoch, tz).hour if op.opened_epoch else None
            profit_str = f"{op.profit:.2f}" if op.profit is not None else "-"
            senal_str = f"{op.senal_valor:.4f}" if hasattr(op, "senal_valor") and op.senal_valor is not None else "-"
            umbral_str = f"{op.umbral_usado:.3f}" if hasattr(op, "umbral_usado") and op.umbral_usado is not None else "-"
            hora_str_short = str(hora_local) if hora_local is not None else "-"

            self.stdout.write(
                fmt.format(
                    op.id,
                    hora_str,
                    op.contract_type or "-",
                    profit_str,
                    op.estado,
                    hora_str_short,
                    senal_str,
                    umbral_str,
                )
            )

        if not cerradas:
            self.stdout.write("\nNo hay operaciones cerradas para analizar.")
            return

        # ===== RESUMEN GENERAL =====
        self.stdout.write(f"\n{'='*100}")
        self.stdout.write("RESUMEN GENERAL")
        self.stdout.write(f"{'='*100}\n")

        total_profit = sum(op.profit for op in cerradas)
        winrate = len(ganadas) * 100 / len(cerradas) if cerradas else 0
        profit_prom = total_profit / len(cerradas) if cerradas else 0

        self.stdout.write(f"Total cerradas: {len(cerradas)}")
        self.stdout.write(f"Ganadas: {len(ganadas)} ({winrate:.1f}%)")
        self.stdout.write(f"Perdidas: {len(perdidas)} ({100-winrate:.1f}%)")
        self.stdout.write(f"Profit total: {total_profit:.2f} USD")
        self.stdout.write(f"Profit promedio: {profit_prom:.2f} USD")

        # ===== ANÁLISIS POR HORA =====
        self.stdout.write(f"\n{'='*100}")
        self.stdout.write("ANÁLISIS POR HORA (Local - America/Bogota)")
        self.stdout.write(f"{'='*100}\n")

        por_hora: dict[int, list] = {}
        for op in cerradas:
            if op.opened_epoch:
                hora = datetime.fromtimestamp(op.opened_epoch, tz).hour
                if hora not in por_hora:
                    por_hora[hora] = []
                por_hora[hora].append(op)

        if por_hora:
            fmt_hora = "{:<5} {:<8} {:<8} {:<10} {:<12} {:<10}"
            self.stdout.write(fmt_hora.format("Hora", "Total", "Ganadas", "Perdidas", "Profit Total", "Winrate %"))
            self.stdout.write("-" * 60)
            for h in sorted(por_hora.keys()):
                ops_h = por_hora[h]
                gan_h = [op for op in ops_h if op.profit > 0]
                perd_h = [op for op in ops_h if op.profit < 0]
                profit_h = sum(op.profit for op in ops_h)
                wr_h = len(gan_h) * 100 / len(ops_h) if ops_h else 0
                self.stdout.write(
                    fmt_hora.format(
                        f"{h:02d}:00",
                        len(ops_h),
                        len(gan_h),
                        len(perd_h),
                        f"{profit_h:.2f}",
                        f"{wr_h:.1f}",
                    )
                )

        # ===== ANÁLISIS POR TIPO DE CONTRATO =====
        self.stdout.write(f"\n{'='*100}")
        self.stdout.write("ANÁLISIS POR TIPO DE CONTRATO")
        self.stdout.write(f"{'='*100}\n")

        por_tipo: dict[str, list] = {}
        for op in cerradas:
            tipo = op.contract_type or "UNKNOWN"
            if tipo not in por_tipo:
                por_tipo[tipo] = []
            por_tipo[tipo].append(op)

        if por_tipo:
            fmt_tipo = "{:<10} {:<8} {:<8} {:<10} {:<12} {:<10}"
            self.stdout.write(fmt_tipo.format("Tipo", "Total", "Ganadas", "Perdidas", "Profit Total", "Winrate %"))
            self.stdout.write("-" * 60)
            for tipo in sorted(por_tipo.keys()):
                ops_t = por_tipo[tipo]
                gan_t = [op for op in ops_t if op.profit > 0]
                perd_t = [op for op in ops_t if op.profit < 0]
                profit_t = sum(op.profit for op in ops_t)
                wr_t = len(gan_t) * 100 / len(ops_t) if ops_t else 0
                self.stdout.write(
                    fmt_tipo.format(
                        tipo,
                        len(ops_t),
                        len(gan_t),
                        len(perd_t),
                        f"{profit_t:.2f}",
                        f"{wr_t:.1f}",
                    )
                )

        # ===== ANÁLISIS DE SEÑALES =====
        if any(hasattr(op, "senal_valor") and op.senal_valor is not None for op in cerradas):
            self.stdout.write(f"\n{'='*100}")
            self.stdout.write("ANÁLISIS DE SEÑALES")
            self.stdout.write(f"{'='*100}\n")

            ops_con_senal = [op for op in cerradas if hasattr(op, "senal_valor") and op.senal_valor is not None]
            if ops_con_senal:
                senales_ganadas = [abs(op.senal_valor) for op in ops_con_senal if op.profit > 0]
                senales_perdidas = [abs(op.senal_valor) for op in ops_con_senal if op.profit < 0]

                if senales_ganadas:
                    self.stdout.write(f"Señal promedio (ganadas): {sum(senales_ganadas)/len(senales_ganadas):.4f}")
                    self.stdout.write(f"Señal mínima (ganadas): {min(senales_ganadas):.4f}")
                    self.stdout.write(f"Señal máxima (ganadas): {max(senales_ganadas):.4f}")

                if senales_perdidas:
                    self.stdout.write(f"Señal promedio (perdidas): {sum(senales_perdidas)/len(senales_perdidas):.4f}")
                    self.stdout.write(f"Señal mínima (perdidas): {min(senales_perdidas):.4f}")
                    self.stdout.write(f"Señal máxima (perdidas): {max(senales_perdidas):.4f}")

        # ===== RECOMENDACIONES =====
        self.stdout.write(f"\n{'='*100}")
        self.stdout.write("RECOMENDACIONES PRELIMINARES")
        self.stdout.write(f"{'='*100}\n")

        if por_hora:
            horas_buenas = [h for h, ops_h in por_hora.items() if len([op for op in ops_h if op.profit > 0]) * 100 / len(ops_h) >= 50]
            horas_malas = [h for h, ops_h in por_hora.items() if len([op for op in ops_h if op.profit > 0]) * 100 / len(ops_h) < 50 and sum(op.profit for op in ops_h) < 0]
            
            if horas_buenas:
                self.stdout.write(f"Horas con buen desempeño (winrate >= 50%): {sorted(horas_buenas)}")
            if horas_malas:
                self.stdout.write(f"Horas con mal desempeño (winrate < 50% y pérdidas): {sorted(horas_malas)}")
                self.stdout.write(f"  → Considerar bloquear estas horas con DERIV_BLOQUEO_HORAS_LOCAL")

        if por_tipo:
            tipos_malos = [tipo for tipo, ops_t in por_tipo.items() if sum(op.profit for op in ops_t) < 0 and len(ops_t) >= 3]
            if tipos_malos:
                self.stdout.write(f"Tipos de contrato con pérdidas consistentes: {tipos_malos}")
                self.stdout.write(f"  → Considerar filtrar con DERIV_CONTRACT_TYPES_PERMITIDOS")

        if winrate < 50:
            self.stdout.write(f"\n⚠️  Winrate bajo ({winrate:.1f}%). Considerar:")
            self.stdout.write(f"  - Revisar umbrales de entrada (posiblemente muy bajos)")
            self.stdout.write(f"  - Recalibrar pesos del modelo")
            self.stdout.write(f"  - Ajustar condiciones de mercado (horarios, tipos de contrato)")

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_riesgo.models import OperacionDeriv


class Command(BaseCommand):
    help = "Análisis detallado de pérdidas: identifica patrones y causas de operaciones perdedoras."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--dias", type=int, default=7, help="Días hacia atrás para analizar (default: 7)")
        parser.add_argument("--top", type=int, default=50, help="Máximo de operaciones a analizar (default: 50)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        dias = int(opts.get("dias") or 7)
        top = int(opts.get("top") or 50)

        tz = ZoneInfo("America/Bogota")
        desde_dt = timezone.now() - timedelta(days=dias)
        desde_epoch = int(desde_dt.timestamp())

        ops = list(
            OperacionDeriv.objects.filter(
                creada_por_bot=True,
                opened_epoch__gte=desde_epoch,
                estado="CERRADA"
            )
            .order_by("-opened_epoch")[:top]
        )

        if not ops:
            self.stdout.write(f"No hay operaciones cerradas en los últimos {dias} días.")
            return

        ganadas = [op for op in ops if op.profit and op.profit > 0]
        perdidas = [op for op in ops if op.profit and op.profit < 0]

        self.stdout.write("=" * 100)
        self.stdout.write("ANÁLISIS DE PÉRDIDAS")
        self.stdout.write("=" * 100)
        self.stdout.write(f"Período: últimos {dias} días")
        self.stdout.write(f"Total operaciones: {len(ops)}")
        self.stdout.write(f"Ganadas: {len(ganadas)} ({len(ganadas)*100/len(ops):.1f}%)")
        self.stdout.write(f"Perdidas: {len(perdidas)} ({len(perdidas)*100/len(ops):.1f}%)")
        self.stdout.write("")

        if not perdidas:
            self.stdout.write("✅ No hay operaciones perdedoras en este período.")
            return

        # ===== ANÁLISIS DE SEÑALES EN OPERACIONES PERDEDORAS =====
        self.stdout.write("─" * 100)
        self.stdout.write("1. ANÁLISIS DE SEÑALES EN OPERACIONES PERDEDORAS")
        self.stdout.write("─" * 100)

        perdidas_con_senal = [op for op in perdidas if hasattr(op, "senal_valor") and op.senal_valor is not None]
        ganadas_con_senal = [op for op in ganadas if hasattr(op, "senal_valor") and op.senal_valor is not None]

        if perdidas_con_senal:
            senales_perdidas = [abs(op.senal_valor) for op in perdidas_con_senal]
            umbrales_perdidas = [op.umbral_usado for op in perdidas_con_senal if hasattr(op, "umbral_usado") and op.umbral_usado]

            self.stdout.write(f"Operaciones perdedoras con señal: {len(perdidas_con_senal)}")
            self.stdout.write(f"  Señal promedio (abs): {sum(senales_perdidas)/len(senales_perdidas):.6f}")
            self.stdout.write(f"  Señal mínima: {min(senales_perdidas):.6f}")
            self.stdout.write(f"  Señal máxima: {max(senales_perdidas):.6f}")
            if umbrales_perdidas:
                self.stdout.write(f"  Umbral promedio usado: {sum(umbrales_perdidas)/len(umbrales_perdidas):.6f}")
                ratios = [abs(op.senal_valor) / op.umbral_usado for op in perdidas_con_senal if hasattr(op, "umbral_usado") and op.umbral_usado and op.umbral_usado > 0]
                if ratios:
                    self.stdout.write(f"  Ratio señal/umbral promedio: {sum(ratios)/len(ratios):.2f}x")

        if ganadas_con_senal:
            senales_ganadas = [abs(op.senal_valor) for op in ganadas_con_senal]
            umbrales_ganadas = [op.umbral_usado for op in ganadas_con_senal if hasattr(op, "umbral_usado") and op.umbral_usado]

            self.stdout.write(f"\nOperaciones ganadas con señal: {len(ganadas_con_senal)}")
            self.stdout.write(f"  Señal promedio (abs): {sum(senales_ganadas)/len(senales_ganadas):.6f}")
            self.stdout.write(f"  Señal mínima: {min(senales_ganadas):.6f}")
            self.stdout.write(f"  Señal máxima: {max(senales_ganadas):.6f}")
            if umbrales_ganadas:
                self.stdout.write(f"  Umbral promedio usado: {sum(umbrales_ganadas)/len(umbrales_ganadas):.6f}")
                ratios = [abs(op.senal_valor) / op.umbral_usado for op in ganadas_con_senal if hasattr(op, "umbral_usado") and op.umbral_usado and op.umbral_usado > 0]
                if ratios:
                    self.stdout.write(f"  Ratio señal/umbral promedio: {sum(ratios)/len(ratios):.2f}x")

        # Comparación
        if perdidas_con_senal and ganadas_con_senal:
            senal_prom_perdidas = sum([abs(op.senal_valor) for op in perdidas_con_senal]) / len(perdidas_con_senal)
            senal_prom_ganadas = sum([abs(op.senal_valor) for op in ganadas_con_senal]) / len(ganadas_con_senal)
            self.stdout.write(f"\n⚠️  COMPARACIÓN:")
            self.stdout.write(f"  Señal promedio (perdidas): {senal_prom_perdidas:.6f}")
            self.stdout.write(f"  Señal promedio (ganadas): {senal_prom_ganadas:.6f}")
            if senal_prom_perdidas < senal_prom_ganadas:
                self.stdout.write(f"  ⚠️  Las operaciones perdedoras tienen señales MÁS DÉBILES que las ganadas")
            elif senal_prom_perdidas > senal_prom_ganadas:
                self.stdout.write(f"  ⚠️  Las operaciones perdedoras tienen señales MÁS FUERTES que las ganadas (contraintuitivo)")

        self.stdout.write("")

        # ===== ANÁLISIS POR HORA =====
        self.stdout.write("─" * 100)
        self.stdout.write("2. ANÁLISIS POR HORA (OPERACIONES PERDEDORAS)")
        self.stdout.write("─" * 100)

        por_hora_perdidas: dict[int, list] = {}
        for op in perdidas:
            if op.opened_epoch:
                hora = datetime.fromtimestamp(op.opened_epoch, tz).hour
                if hora not in por_hora_perdidas:
                    por_hora_perdidas[hora] = []
                por_hora_perdidas[hora].append(op)

        if por_hora_perdidas:
            fmt = "{:<5} {:<8} {:<12} {:<12}"
            self.stdout.write(fmt.format("Hora", "Perdidas", "Profit Total", "Profit Prom"))
            self.stdout.write("-" * 40)
            for h in sorted(por_hora_perdidas.keys()):
                ops_h = por_hora_perdidas[h]
                profit_h = sum(op.profit for op in ops_h)
                profit_prom = profit_h / len(ops_h)
                self.stdout.write(
                    fmt.format(
                        f"{h:02d}:00",
                        len(ops_h),
                        f"{profit_h:.2f}",
                        f"{profit_prom:.2f}",
                    )
                )

        self.stdout.write("")

        # ===== ANÁLISIS POR UMBRAL =====
        self.stdout.write("─" * 100)
        self.stdout.write("3. ANÁLISIS POR UMBRAL USADO (OPERACIONES PERDEDORAS)")
        self.stdout.write("─" * 100)

        por_umbral_perdidas: dict[float, list] = {}
        for op in perdidas:
            if hasattr(op, "umbral_usado") and op.umbral_usado:
                umbral_redondeado = round(float(op.umbral_usado), 3)
                if umbral_redondeado not in por_umbral_perdidas:
                    por_umbral_perdidas[umbral_redondeado] = []
                por_umbral_perdidas[umbral_redondeado].append(op)

        if por_umbral_perdidas:
            fmt = "{:<12} {:<8} {:<12} {:<12}"
            self.stdout.write(fmt.format("Umbral", "Perdidas", "Profit Total", "Profit Prom"))
            self.stdout.write("-" * 45)
            for umb in sorted(por_umbral_perdidas.keys(), reverse=True):
                ops_u = por_umbral_perdidas[umb]
                profit_u = sum(op.profit for op in ops_u)
                profit_prom = profit_u / len(ops_u)
                self.stdout.write(
                    fmt.format(
                        f"{umb:.3f}",
                        len(ops_u),
                        f"{profit_u:.2f}",
                        f"{profit_prom:.2f}",
                    )
                )

        self.stdout.write("")

        # ===== ÚLTIMAS 10 OPERACIONES PERDEDORAS (DETALLE) =====
        self.stdout.write("─" * 100)
        self.stdout.write("4. ÚLTIMAS 10 OPERACIONES PERDEDORAS (DETALLE)")
        self.stdout.write("─" * 100)

        ultimas_perdidas = sorted(perdidas, key=lambda op: op.opened_epoch or 0, reverse=True)[:10]

        fmt = "{:<5} {:<19} {:<5} {:<10} {:<10} {:<10} {:<10}"
        self.stdout.write(fmt.format("ID", "Fecha", "Tipo", "Profit", "Señal", "Umbral", "Ratio"))
        self.stdout.write("-" * 80)
        for op in ultimas_perdidas:
            fecha_str = datetime.fromtimestamp(op.opened_epoch, tz).strftime("%Y-%m-%d %H:%M") if op.opened_epoch else "N/A"
            senal_str = f"{op.senal_valor:.4f}" if hasattr(op, "senal_valor") and op.senal_valor is not None else "N/A"
            umbral_str = f"{op.umbral_usado:.4f}" if hasattr(op, "umbral_usado") and op.umbral_usado else "N/A"
            ratio_str = "N/A"
            if hasattr(op, "senal_valor") and op.senal_valor is not None and hasattr(op, "umbral_usado") and op.umbral_usado and op.umbral_usado > 0:
                ratio_str = f"{abs(op.senal_valor) / op.umbral_usado:.2f}x"

            self.stdout.write(
                fmt.format(
                    op.id,
                    fecha_str,
                    op.contract_type or "-",
                    f"{op.profit:.2f}",
                    senal_str,
                    umbral_str,
                    ratio_str,
                )
            )

        self.stdout.write("")

        # ===== RECOMENDACIONES =====
        self.stdout.write("=" * 100)
        self.stdout.write("RECOMENDACIONES")
        self.stdout.write("=" * 100)

        winrate = len(ganadas) * 100 / len(ops) if ops else 0

        if winrate < 50:
            self.stdout.write(f"⚠️  Winrate bajo ({winrate:.1f}%). Posibles causas:")

            if perdidas_con_senal and ganadas_con_senal:
                senal_prom_perdidas = sum([abs(op.senal_valor) for op in perdidas_con_senal]) / len(perdidas_con_senal)
                senal_prom_ganadas = sum([abs(op.senal_valor) for op in ganadas_con_senal]) / len(ganadas_con_senal)
                
                if senal_prom_perdidas < senal_prom_ganadas:
                    self.stdout.write(f"  1. Las señales perdedoras son más débiles → Considerar AUMENTAR umbrales")
                elif abs(senal_prom_perdidas - senal_prom_ganadas) < 0.01:
                    self.stdout.write(f"  2. Las señales son similares entre ganadas/perdidas → El modelo no discrimina bien")
                    self.stdout.write(f"     → Considerar RECALIBRAR pesos del modelo")

            # Verificar si hay horas problemáticas
            if por_hora_perdidas:
                horas_mas_perdidas = sorted(por_hora_perdidas.items(), key=lambda x: len(x[1]), reverse=True)[:3]
                if horas_mas_perdidas:
                    self.stdout.write(f"  3. Horas con más pérdidas: {[f'{h:02d}:00 ({len(ops)} ops)' for h, ops in horas_mas_perdidas]}")
                    self.stdout.write(f"     → Considerar bloquear estas horas")

            # Verificar umbrales
            if por_umbral_perdidas:
                umbrales_mas_perdidas = sorted(por_umbral_perdidas.items(), key=lambda x: len(x[1]), reverse=True)[:2]
                if umbrales_mas_perdidas:
                    self.stdout.write(f"  4. Umbrales con más pérdidas: {[f'{u:.3f} ({len(ops)} ops)' for u, ops in umbrales_mas_perdidas]}")
                    self.stdout.write(f"     → Considerar ajustar estos umbrales")

        self.stdout.write("")

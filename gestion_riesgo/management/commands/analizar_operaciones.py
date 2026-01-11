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
        parser.add_argument("--dias", type=int, default=None, help="Días hacia atrás para analizar (sobrescribe --horas)")
        parser.add_argument("--top", type=int, default=50, help="Máximo de operaciones a mostrar (default: 50)")
        parser.add_argument("--consistencia", action="store_true", help="Analiza consistencia de patrones horarios por día")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        dias = opts.get("dias")
        horas = int(opts.get("horas") or 24)
        top = int(opts.get("top") or 50)
        analizar_consistencia = bool(opts.get("consistencia"))

        tz = ZoneInfo("America/Bogota")
        if dias:
            desde_dt = timezone.now() - timedelta(days=dias)
        else:
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

        # ===== ANÁLISIS DE CONSISTENCIA POR HORA Y DÍA =====
        if analizar_consistencia and cerradas:
            self.stdout.write(f"\n{'='*100}")
            self.stdout.write("ANÁLISIS DE CONSISTENCIA POR HORA Y DÍA")
            self.stdout.write(f"{'='*100}\n")
            self.stdout.write("(Para verificar si los patrones horarios se repiten consistentemente)\n")

            # Agrupar por hora Y día
            por_hora_dia: dict[tuple[int, str], list] = {}
            for op in cerradas:
                if op.opened_epoch:
                    dt = datetime.fromtimestamp(op.opened_epoch, tz=tz)
                    hora = dt.hour
                    dia = dt.strftime("%Y-%m-%d")
                    key = (hora, dia)
                    if key not in por_hora_dia:
                        por_hora_dia[key] = []
                    por_hora_dia[key].append(op)

            # Para cada hora, ver cuántos días tienen datos y cómo se comporta cada día
            horas_analizadas = sorted(set(h for h, _ in por_hora_dia.keys()))
            if horas_analizadas:
                fmt_cons = "{:<5} {:<8} {:<15} {:<15} {:<15} {:<15}"
                self.stdout.write(fmt_cons.format("Hora", "Días", "Días Ganadores", "Días Perdedores", "Días Neutros", "Consistencia"))
                self.stdout.write("-" * 75)

                for h in horas_analizadas:
                    dias_hora = [dia for hora, dia in por_hora_dia.keys() if hora == h]
                    dias_unicos = sorted(set(dias_hora))
                    
                    dias_ganadores = 0
                    dias_perdedores = 0
                    dias_neutros = 0
                    
                    for dia in dias_unicos:
                        ops_dia = por_hora_dia[(h, dia)]
                        profit_dia = sum(op.profit for op in ops_dia)
                        if profit_dia > 0:
                            dias_ganadores += 1
                        elif profit_dia < 0:
                            dias_perdedores += 1
                        else:
                            dias_neutros += 1

                    total_dias = len(dias_unicos)
                    if total_dias > 0:
                        # Consistencia: % de días que siguen el patrón dominante
                        if dias_ganadores >= dias_perdedores:
                            consistencia = (dias_ganadores / total_dias) * 100
                            patrón = "GANADORA"
                        else:
                            consistencia = (dias_perdedores / total_dias) * 100
                            patrón = "PERDEDORA"
                        
                        consistencia_str = f"{consistencia:.0f}% {patrón}"
                    else:
                        consistencia_str = "N/A"

                    self.stdout.write(
                        fmt_cons.format(
                            f"{h:02d}:00",
                            total_dias,
                            dias_ganadores,
                            dias_perdedores,
                            dias_neutros,
                            consistencia_str,
                        )
                    )

                # Resumen de confianza estadística
                horas_con_muchos_dias = []
                for h in horas_analizadas:
                    dias_para_hora = {dia for hora, dia in por_hora_dia.keys() if hora == h}
                    if len(dias_para_hora) >= 3:
                        horas_con_muchos_dias.append(h)
                self.stdout.write(f"\n⚠️  Confianza estadística:")
                self.stdout.write(f"  - Horas con ≥3 días de datos: {sorted(horas_con_muchos_dias)}")
                self.stdout.write(f"  - Horas con <3 días de datos: {sorted(set(horas_analizadas) - set(horas_con_muchos_dias))}")
                self.stdout.write(f"  - Recomendación: Analizar mínimo 5-7 días para tener confianza en los patrones")

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
            
            # Advertencia si hay pocos datos
            horas_con_pocos_datos = [h for h, ops_h in por_hora.items() if len(ops_h) < 3]
            if horas_con_pocos_datos and not dias:
                self.stdout.write(f"\n⚠️  Horas con pocos datos (<3 operaciones): {sorted(horas_con_pocos_datos)}")
                self.stdout.write(f"  → Usa --dias 7 o más para tener más confianza en los patrones")

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

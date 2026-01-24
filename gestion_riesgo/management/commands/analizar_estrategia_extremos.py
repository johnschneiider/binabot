from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_riesgo.models import Cuenta, OperacionDeriv


class Command(BaseCommand):
    help = "Análisis matemático profundo de la estrategia extremos para identificar mejoras."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--dias", type=int, default=30, help="Días hacia atrás para analizar (default: 30)")
        parser.add_argument("--min-operaciones", type=int, default=50, help="Mínimo de operaciones para análisis (default: 50)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        dias = int(opts.get("dias") or 30)
        min_ops = int(opts.get("min_operaciones") or 50)

        tz = ZoneInfo("America/Bogota")
        desde_dt = timezone.now() - timedelta(days=dias)
        desde_epoch = int(desde_dt.timestamp())

        simbolo_activo = getattr(settings, "DERIV_SYMBOL", "R_10")
        cuenta = Cuenta.objects.filter(simbolo=simbolo_activo).order_by("id").first()

        if not cuenta:
            self.stdout.write(self.style.ERROR("❌ No hay cuenta configurada."))
            return

        # Obtener operaciones
        ops = list(
            OperacionDeriv.objects.filter(
                cuenta=cuenta,
                creada_por_bot=True,
                opened_epoch__gte=desde_epoch,
                estado="CERRADA",
                profit__isnull=False
            ).order_by("-opened_epoch")
        )

        if len(ops) < min_ops:
            self.stdout.write(self.style.WARNING(f"⚠️  Solo hay {len(ops)} operaciones (mínimo recomendado: {min_ops})"))
            self.stdout.write("   El análisis puede no ser confiable con tan pocos datos.")

        cerradas = [op for op in ops if op.profit is not None]
        ganadas = [op for op in cerradas if op.profit > 0]
        perdidas = [op for op in cerradas if op.profit < 0]

        self.stdout.write("=" * 100)
        self.stdout.write(self.style.SUCCESS("ANÁLISIS MATEMÁTICO DE ESTRATEGIA EXTREMOS"))
        self.stdout.write("=" * 100)
        self.stdout.write(f"Período: últimos {dias} días")
        self.stdout.write(f"Total operaciones: {len(cerradas)}")
        self.stdout.write(f"Ganadas: {len(ganadas)} ({len(ganadas)*100/len(cerradas):.1f}%)")
        self.stdout.write(f"Perdidas: {len(perdidas)} ({len(perdidas)*100/len(cerradas):.1f}%)")
        self.stdout.write("")

        if len(cerradas) < 10:
            self.stdout.write(self.style.ERROR("❌ No hay suficientes operaciones para análisis."))
            return

        # ===== 1. ANÁLISIS DE PRECIOS Y MOVIMIENTOS =====
        self.stdout.write("─" * 100)
        self.stdout.write("1. ANÁLISIS DE PRECIOS Y MOVIMIENTOS")
        self.stdout.write("─" * 100)

        ops_con_spots = [op for op in cerradas if op.entry_spot and op.exit_spot]
        
        if not ops_con_spots:
            self.stdout.write("⚠️  No hay operaciones con entry_spot y exit_spot disponibles")
            self.stdout.write("   Esto limita el análisis. Verificar que el bot guarde estos campos.")
            self.stdout.write("")
        else:
            self.stdout.write(f"Operaciones con entry_spot y exit_spot: {len(ops_con_spots)}/{len(cerradas)}")
            self.stdout.write("")

            # Análisis de movimiento durante la operación
            movimientos_ganadas = []
            movimientos_perdidas = []
            
            for op in ops_con_spots:
                if op.contract_type == "PUT":
                    # Para PUT: ganamos si el precio BAJA desde entry
                    movimiento = op.entry_spot - op.exit_spot
                    movimiento_pct = (movimiento / op.entry_spot) * 100 if op.entry_spot > 0 else 0
                else:  # CALL
                    # Para CALL: ganamos si el precio SUBE desde entry
                    movimiento = op.exit_spot - op.entry_spot
                    movimiento_pct = (movimiento / op.entry_spot) * 100 if op.entry_spot > 0 else 0

                datos_mov = {
                    "movimiento": movimiento,
                    "movimiento_pct": movimiento_pct,
                    "profit": op.profit or 0.0,
                    "entry_spot": op.entry_spot,
                    "exit_spot": op.exit_spot
                }

                if op.profit > 0:
                    movimientos_ganadas.append(datos_mov)
                else:
                    movimientos_perdidas.append(datos_mov)

            if movimientos_ganadas and movimientos_perdidas:
                self.stdout.write("Movimiento de precio durante operación:")
                mov_gan_prom = statistics.mean([m['movimiento'] for m in movimientos_ganadas])
                mov_per_prom = statistics.mean([m['movimiento'] for m in movimientos_perdidas])
                mov_gan_med = statistics.median([m['movimiento'] for m in movimientos_ganadas])
                mov_per_med = statistics.median([m['movimiento'] for m in movimientos_perdidas])
                
                self.stdout.write(f"  Movimiento promedio (ganadas): {mov_gan_prom:.4f}")
                self.stdout.write(f"  Movimiento promedio (perdidas): {mov_per_prom:.4f}")
                self.stdout.write(f"  Movimiento mediano (ganadas): {mov_gan_med:.4f}")
                self.stdout.write(f"  Movimiento mediano (perdidas): {mov_per_med:.4f}")
                
                mov_pct_gan = statistics.mean([m['movimiento_pct'] for m in movimientos_ganadas])
                mov_pct_per = statistics.mean([m['movimiento_pct'] for m in movimientos_perdidas])
                self.stdout.write(f"  Movimiento % promedio (ganadas): {mov_pct_gan:.4f}%")
                self.stdout.write(f"  Movimiento % promedio (perdidas): {mov_pct_per:.4f}%")

        # ===== 2. ANÁLISIS POR HORA =====
        self.stdout.write("")
        self.stdout.write("─" * 100)
        self.stdout.write("2. ANÁLISIS POR HORA DEL DÍA")
        self.stdout.write("─" * 100)

        por_hora: dict[int, list] = defaultdict(list)
        for op in cerradas:
            if op.opened_epoch:
                hora = datetime.fromtimestamp(op.opened_epoch, tz).hour
                por_hora[hora].append(op)

        if por_hora:
            fmt = "{:<5} {:<8} {:<8} {:<12} {:<12} {:<10}"
            self.stdout.write(fmt.format("Hora", "Total", "Ganadas", "Perdidas", "Profit Total", "Winrate %"))
            self.stdout.write("-" * 65)
            
            horas_ordenadas = sorted(por_hora.keys())
            for h in horas_ordenadas:
                ops_h = por_hora[h]
                gan_h = [op for op in ops_h if op.profit > 0]
                perd_h = [op for op in ops_h if op.profit < 0]
                profit_h = sum(op.profit for op in ops_h)
                wr_h = len(gan_h) * 100 / len(ops_h) if ops_h else 0
                self.stdout.write(fmt.format(
                    f"{h:02d}:00",
                    len(ops_h),
                    len(gan_h),
                    len(perd_h),
                    f"{profit_h:.2f}",
                    f"{wr_h:.1f}"
                ))

        # ===== 3. ANÁLISIS DE PARÁMETROS ACTUALES =====
        self.stdout.write("")
        self.stdout.write("─" * 100)
        self.stdout.write("3. PARÁMETROS ACTUALES DE ESTRATEGIA")
        self.stdout.write("─" * 100)

        params = {
            "EXTREMOS_VENTANA_TICKS": getattr(settings, "EXTREMOS_VENTANA_TICKS", 100),
            "EXTREMOS_FRESCURA_TICKS": getattr(settings, "EXTREMOS_FRESCURA_TICKS", 5),
            "EXTREMOS_MIN_REVERSION_FRAC": getattr(settings, "EXTREMOS_MIN_REVERSION_FRAC", 0.05),
            "EXTREMOS_MIN_REVERSION_ABS": getattr(settings, "EXTREMOS_MIN_REVERSION_ABS", 0.0),
            "EXTREMOS_PROMEDIO_DELTA_TICKS": getattr(settings, "EXTREMOS_PROMEDIO_DELTA_TICKS", 20),
            "EXTREMOS_PROMEDIO_DELTA_FACTOR": getattr(settings, "EXTREMOS_PROMEDIO_DELTA_FACTOR", 1.0),
            "DERIV_DURACION_TICKS": getattr(settings, "DERIV_DURACION_TICKS", 5),
            "ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS": getattr(settings, "ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS", 25),
            "ESTRATEGIA_EXTREMOS_UMBRAL_RANGO": getattr(settings, "ESTRATEGIA_EXTREMOS_UMBRAL_RANGO", 0.5),
        }

        for param, valor in params.items():
            self.stdout.write(f"  {param}: {valor}")

        # ===== 4. ANÁLISIS DE PROFIT Y RIESGO =====
        self.stdout.write("")
        self.stdout.write("─" * 100)
        self.stdout.write("4. ANÁLISIS DE PROFIT Y RIESGO")
        self.stdout.write("─" * 100)

        profits = [op.profit for op in cerradas]
        profit_total = sum(profits)
        profit_prom = statistics.mean(profits)
        profit_med = statistics.median(profits)
        profit_std = statistics.stdev(profits) if len(profits) > 1 else 0

        self.stdout.write(f"Profit total: {profit_total:.2f} USD")
        self.stdout.write(f"Profit promedio: {profit_prom:.4f} USD")
        self.stdout.write(f"Profit mediano: {profit_med:.4f} USD")
        self.stdout.write(f"Desviación estándar: {profit_std:.4f} USD")

        # Ratio ganancia/pérdida promedio
        if movimientos_ganadas and movimientos_perdidas:
            profit_gan_prom = statistics.mean([op.profit for op in ganadas])
            profit_per_prom = abs(statistics.mean([op.profit for op in perdidas]))
            if profit_per_prom > 0:
                ratio = profit_gan_prom / profit_per_prom
                self.stdout.write(f"")
                self.stdout.write(f"Profit promedio (ganadas): {profit_gan_prom:.4f} USD")
                self.stdout.write(f"Pérdida promedio (perdidas): {profit_per_prom:.4f} USD")
                self.stdout.write(f"Ratio ganancia/pérdida: {ratio:.2f}")
                if ratio < 1.0:
                    self.stdout.write(self.style.WARNING("  ⚠️  Las pérdidas promedio son mayores que las ganancias promedio"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Ratio saludable (necesitas winrate > {100/(1+ratio)*100:.1f}% para ser rentable)"))

        # ===== 5. RECOMENDACIONES MATEMÁTICAS =====
        self.stdout.write("")
        self.stdout.write("=" * 100)
        self.stdout.write("RECOMENDACIONES MATEMÁTICAS")
        self.stdout.write("=" * 100)

        recomendaciones = []

        # Análisis de winrate
        winrate = len(ganadas) * 100 / len(cerradas) if cerradas else 0
        if winrate < 50:
            min_rev_frac_actual = getattr(settings, "EXTREMOS_MIN_REVERSION_FRAC", 0.05)
            delta_factor_actual = getattr(settings, "EXTREMOS_PROMEDIO_DELTA_FACTOR", 1.0)
            umbral_rango_actual = getattr(settings, "ESTRATEGIA_EXTREMOS_UMBRAL_RANGO", 0.5)
            
            recomendaciones.append({
                "prioridad": "ALTA",
                "problema": f"Winrate bajo ({winrate:.1f}%)",
                "recomendacion": "Aumentar filtros de entrada para mejorar calidad de señales",
                "acciones": [
                    f"Aumentar EXTREMOS_MIN_REVERSION_FRAC de {min_rev_frac_actual:.3f} a {min_rev_frac_actual * 1.5:.3f} (aumento 50%)",
                    f"Aumentar EXTREMOS_PROMEDIO_DELTA_FACTOR de {delta_factor_actual:.2f} a {delta_factor_actual * 1.3:.2f} (aumento 30%)",
                    f"Considerar aumentar ESTRATEGIA_EXTREMOS_UMBRAL_RANGO de {umbral_rango_actual:.2f} a {umbral_rango_actual * 1.2:.2f}",
                ]
            })

        # Análisis de horas problemáticas
        if por_hora:
            horas_malas = []
            for h, ops_h in por_hora.items():
                if len(ops_h) >= 5:  # Mínimo 5 operaciones para considerar
                    wr_h = len([op for op in ops_h if op.profit > 0]) * 100 / len(ops_h)
                    profit_h = sum(op.profit for op in ops_h)
                    if wr_h < 40 and profit_h < -1.0:  # Winrate bajo Y pérdidas significativas
                        horas_malas.append((h, wr_h, profit_h))
            
            if horas_malas:
                horas_malas.sort(key=lambda x: x[2])  # Ordenar por pérdida
                recomendaciones.append({
                    "prioridad": "MEDIA",
                    "problema": f"Horas problemáticas detectadas",
                    "recomendacion": "Considerar bloquear horas con winrate bajo y pérdidas consistentes",
                    "acciones": [
                        f"Horas problemáticas: {', '.join([f'{h:02d}:00 (WR={wr:.1f}%, Profit={p:.2f})' for h, wr, p in horas_malas[:5]])}",
                        f"Agregar a DERIV_BLOQUEO_HORAS_LOCAL: {','.join([str(h) for h, _, _ in horas_malas[:3]])}"
                    ]
                })

        # Análisis de ratio ganancia/pérdida
        if movimientos_ganadas and movimientos_perdidas:
            profit_gan_prom = statistics.mean([op.profit for op in ganadas])
            profit_per_prom = abs(statistics.mean([op.profit for op in perdidas]))
            if profit_per_prom > 0:
                ratio = profit_gan_prom / profit_per_prom
                if ratio < 0.9:
                    recomendaciones.append({
                        "prioridad": "ALTA",
                        "problema": f"Ratio ganancia/pérdida bajo ({ratio:.2f})",
                        "recomendacion": "Las pérdidas promedio son mayores que las ganancias. Necesitas winrate muy alto para ser rentable.",
                        "acciones": [
                            "Considerar aumentar DERIV_DURACION_TICKS para capturar más movimiento",
                            "O reducir stake para limitar pérdidas",
                        ]
                    })

        # Mostrar recomendaciones
        if recomendaciones:
            for i, rec in enumerate(recomendaciones, 1):
                self.stdout.write("")
                self.stdout.write(f"{i}. [{rec['prioridad']}] {rec['problema']}")
                self.stdout.write(f"   Recomendación: {rec['recomendacion']}")
                self.stdout.write("   Acciones:")
                for accion in rec['acciones']:
                    self.stdout.write(f"     - {accion}")
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("✅ No se detectaron problemas críticos en la estrategia."))
            self.stdout.write("   La estrategia parece estar funcionando razonablemente bien.")

        self.stdout.write("")
        self.stdout.write("=" * 100)

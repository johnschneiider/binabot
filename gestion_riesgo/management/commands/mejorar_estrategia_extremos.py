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
    help = "Análisis matemático profundo y propuesta de mejoras para la estrategia extremos."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--dias", type=int, default=30, help="Días hacia atrás para analizar (default: 30)")
        parser.add_argument("--aplicar", action="store_true", help="Aplicar automáticamente las mejoras sugeridas")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        dias = int(opts.get("dias") or 30)
        aplicar = bool(opts.get("aplicar"))

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

        cerradas = [op for op in ops if op.profit is not None]
        ganadas = [op for op in cerradas if op.profit > 0]
        perdidas = [op for op in cerradas if op.profit < 0]
        ops_con_spots = [op for op in cerradas if op.entry_spot and op.exit_spot]

        self.stdout.write("=" * 100)
        self.stdout.write(self.style.SUCCESS("INVESTIGACIÓN MATEMÁTICA: MEJORAS DE ESTRATEGIA"))
        self.stdout.write("=" * 100)
        self.stdout.write(f"Período: últimos {dias} días | Operaciones: {len(cerradas)}")
        self.stdout.write("")

        if len(cerradas) < 50:
            self.stdout.write(self.style.WARNING("⚠️  Pocos datos para análisis confiable. Mínimo recomendado: 50"))
            self.stdout.write("")

        # ===== ANÁLISIS 1: RATIO GANANCIA/PÉRDIDA =====
        self.stdout.write("─" * 100)
        self.stdout.write("ANÁLISIS 1: RATIO GANANCIA/PÉRDIDA Y WINRATE MÍNIMO")
        self.stdout.write("─" * 100)

        profit_gan_prom = statistics.mean([op.profit for op in ganadas]) if ganadas else 0
        profit_per_prom = abs(statistics.mean([op.profit for op in perdidas])) if perdidas else 0
        ratio = profit_gan_prom / profit_per_prom if profit_per_prom > 0 else 0

        self.stdout.write(f"Ganancia promedio: {profit_gan_prom:.4f} USD")
        self.stdout.write(f"Pérdida promedio: {profit_per_prom:.4f} USD")
        self.stdout.write(f"Ratio: {ratio:.3f}")
        self.stdout.write("")

        # Calcular winrate mínimo necesario para ser rentable
        # Profit esperado = WR * profit_gan - (1-WR) * profit_per
        # Para ser rentable: WR * profit_gan - (1-WR) * profit_per > 0
        # WR * profit_gan - profit_per + WR * profit_per > 0
        # WR * (profit_gan + profit_per) > profit_per
        # WR > profit_per / (profit_gan + profit_per)
        if profit_gan_prom > 0 and profit_per_prom > 0:
            wr_minimo = profit_per_prom / (profit_gan_prom + profit_per_prom)
            wr_actual = len(ganadas) / len(cerradas) if cerradas else 0
            
            self.stdout.write(f"Winrate mínimo necesario: {wr_minimo*100:.2f}%")
            self.stdout.write(f"Winrate actual: {wr_actual*100:.2f}%")
            self.stdout.write(f"Diferencia necesaria: {(wr_minimo - wr_actual)*100:.2f} puntos porcentuales")
            
            if wr_actual < wr_minimo:
                self.stdout.write(self.style.ERROR(f"  ❌ Winrate actual ({wr_actual*100:.2f}%) es INSUFICIENTE para ser rentable"))
                self.stdout.write(f"     Necesitas mejorar el winrate en al menos {(wr_minimo - wr_actual)*100:.2f} puntos porcentuales")
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✅ Winrate actual ({wr_actual*100:.2f}%) es suficiente para ser rentable"))
                self.stdout.write(f"     Pero el profit esperado es muy bajo: {wr_actual * profit_gan_prom - (1-wr_actual) * profit_per_prom:.4f} USD/trade")

        self.stdout.write("")

        # ===== ANÁLISIS 2: MOVIMIENTO DE PRECIO =====
        self.stdout.write("─" * 100)
        self.stdout.write("ANÁLISIS 2: MOVIMIENTO DE PRECIO Y DURACIÓN ÓPTIMA")
        self.stdout.write("─" * 100)

        if ops_con_spots:
            movimientos = []
            for op in ops_con_spots:
                if op.contract_type == "PUT":
                    movimiento = op.entry_spot - op.exit_spot
                else:
                    movimiento = op.exit_spot - op.entry_spot
                movimientos.append({
                    "op": op,
                    "movimiento": movimiento,
                    "movimiento_abs": abs(movimiento),
                    "profit": op.profit or 0.0
                })

            movimientos_ganadas = [m for m in movimientos if m["profit"] > 0]
            movimientos_perdidas = [m for m in movimientos if m["profit"] < 0]

            if movimientos_ganadas and movimientos_perdidas:
                mov_gan_med = statistics.median([m["movimiento_abs"] for m in movimientos_ganadas])
                mov_per_med = statistics.median([m["movimiento_abs"] for m in movimientos_perdidas])
                
                self.stdout.write(f"Movimiento mediano (ganadas): {mov_gan_med:.4f}")
                self.stdout.write(f"Movimiento mediano (perdidas): {mov_per_med:.4f}")
                self.stdout.write("")

                # Análisis de percentiles
                mov_gan_sorted = sorted([m["movimiento_abs"] for m in movimientos_ganadas])
                mov_per_sorted = sorted([m["movimiento_abs"] for m in movimientos_perdidas])
                
                p25_gan = mov_gan_sorted[len(mov_gan_sorted) // 4] if mov_gan_sorted else 0
                p75_gan = mov_gan_sorted[3 * len(mov_gan_sorted) // 4] if mov_gan_sorted else 0
                p25_per = mov_per_sorted[len(mov_per_sorted) // 4] if mov_per_sorted else 0
                p75_per = mov_per_sorted[3 * len(mov_per_sorted) // 4] if mov_per_sorted else 0

                self.stdout.write("Distribución de movimientos:")
                self.stdout.write(f"  Ganadas - P25: {p25_gan:.4f}, Mediana: {mov_gan_med:.4f}, P75: {p75_gan:.4f}")
                self.stdout.write(f"  Perdidas - P25: {p25_per:.4f}, Mediana: {mov_per_med:.4f}, P75: {p75_per:.4f}")
                
                # Si el movimiento mediano de ganadas es similar al de perdidas, 
                # significa que la estrategia no está capturando suficiente "edge"
                if mov_gan_med < mov_per_med * 1.2:
                    self.stdout.write(self.style.WARNING("  ⚠️  Los movimientos ganadores no son significativamente mayores que los perdedores"))
                    self.stdout.write("     Esto sugiere que la estrategia necesita más filtros para capturar movimientos más grandes")

        self.stdout.write("")

        # ===== ANÁLISIS 3: HORAS PROBLEMÁTICAS =====
        self.stdout.write("─" * 100)
        self.stdout.write("ANÁLISIS 3: HORAS PROBLEMÁTICAS (ANÁLISIS ESTADÍSTICO)")
        self.stdout.write("─" * 100)

        por_hora: dict[int, list] = defaultdict(list)
        for op in cerradas:
            if op.opened_epoch:
                hora = datetime.fromtimestamp(op.opened_epoch, tz).hour
                por_hora[hora].append(op)

        horas_problematicas = []
        horas_buenas = []
        
        for h in sorted(por_hora.keys()):
            ops_h = por_hora[h]
            if len(ops_h) >= 10:  # Mínimo 10 operaciones para análisis estadístico
                wr_h = len([op for op in ops_h if op.profit > 0]) / len(ops_h)
                profit_h = sum(op.profit for op in ops_h)
                profit_prom_h = profit_h / len(ops_h)
                
                # Criterio: winrate < 45% Y profit promedio < -0.1
                if wr_h < 0.45 and profit_prom_h < -0.1:
                    horas_problematicas.append((h, wr_h, profit_h, profit_prom_h, len(ops_h)))
                elif wr_h >= 0.55 and profit_prom_h > 0.05:
                    horas_buenas.append((h, wr_h, profit_h, profit_prom_h, len(ops_h)))

        if horas_problematicas:
            self.stdout.write("Horas problemáticas (WR < 45%, Profit promedio < -0.1):")
            fmt = "{:<5} {:<8} {:<10} {:<12} {:<12}"
            self.stdout.write(fmt.format("Hora", "Ops", "Winrate", "Profit Total", "Profit Prom"))
            self.stdout.write("-" * 50)
            for h, wr, profit, profit_prom, n in sorted(horas_problematicas, key=lambda x: x[3]):
                self.stdout.write(fmt.format(f"{h:02d}:00", n, f"{wr*100:.1f}%", f"{profit:.2f}", f"{profit_prom:.4f}"))

        if horas_buenas:
            self.stdout.write("")
            self.stdout.write("Horas buenas (WR >= 55%, Profit promedio > 0.05):")
            self.stdout.write(fmt.format("Hora", "Ops", "Winrate", "Profit Total", "Profit Prom"))
            self.stdout.write("-" * 50)
            for h, wr, profit, profit_prom, n in sorted(horas_buenas, key=lambda x: -x[3]):
                self.stdout.write(fmt.format(f"{h:02d}:00", n, f"{wr*100:.1f}%", f"{profit:.2f}", f"{profit_prom:.4f}"))

        self.stdout.write("")

        # ===== PROPUESTA DE MEJORAS =====
        self.stdout.write("=" * 100)
        self.stdout.write("PROPUESTA DE MEJORAS MATEMÁTICAS")
        self.stdout.write("=" * 100)

        mejoras = []

        # Mejora 1: Aumentar filtros de entrada
        min_rev_frac_actual = getattr(settings, "EXTREMOS_MIN_REVERSION_FRAC", 0.05)
        delta_factor_actual = getattr(settings, "EXTREMOS_PROMEDIO_DELTA_FACTOR", 1.0)
        umbral_rango_actual = getattr(settings, "ESTRATEGIA_EXTREMOS_UMBRAL_RANGO", 0.5)

        # Calcular incrementos sugeridos basados en el gap de winrate
        wr_actual = len(ganadas) / len(cerradas) if cerradas else 0
        if profit_per_prom > 0:
            wr_necesario = profit_per_prom / (profit_gan_prom + profit_per_prom)
            gap_wr = wr_necesario - wr_actual
            
            if gap_wr > 0:
                # Cálculo más práctico: basado en el gap de winrate necesario
                # Si necesitas mejorar 3.4pp, necesitas filtrar aproximadamente 5-7% más operaciones
                # Esto se traduce en incrementos más agresivos de los filtros
                
                # Factor de incremento basado en el gap absoluto (más intuitivo)
                # Gap de 3.4pp = incremento de ~30-50% en filtros
                factor_incremento_min_rev = 1.0 + (gap_wr * 10.0)  # ~34% para gap de 3.4pp
                factor_incremento_delta = 1.0 + (gap_wr * 8.0)  # ~27% para gap de 3.4pp
                
                # Aplicar incrementos con límites razonables
                min_rev_frac_nuevo = min(min_rev_frac_actual * factor_incremento_min_rev, 0.20)  # Máximo 20%
                delta_factor_nuevo = min(delta_factor_actual * factor_incremento_delta, 2.5)  # Máximo 2.5
                
                # Asegurar incrementos mínimos significativos
                incremento_min_rev = min_rev_frac_nuevo - min_rev_frac_actual
                incremento_delta = delta_factor_nuevo - delta_factor_actual
                
                if incremento_min_rev < 0.02:  # Mínimo 2% de incremento
                    min_rev_frac_nuevo = min_rev_frac_actual + 0.03
                if incremento_delta < 0.2:  # Mínimo 0.2 de incremento
                    delta_factor_nuevo = delta_factor_actual + 0.3
                
                mejoras.append({
                    "tipo": "FILTROS",
                    "descripcion": "Aumentar filtros de entrada para mejorar winrate",
                    "cambios": {
                        "EXTREMOS_MIN_REVERSION_FRAC": (min_rev_frac_actual, min_rev_frac_nuevo),
                        "EXTREMOS_PROMEDIO_DELTA_FACTOR": (delta_factor_actual, delta_factor_nuevo),
                    },
                    "razon": f"Winrate actual ({wr_actual*100:.1f}%) necesita mejorar {gap_wr*100:.1f}pp para ser rentable"
                })

        # Mejora 2: Bloquear horas problemáticas
        if horas_problematicas:
            # Verificar qué horas ya están bloqueadas
            bloqueo_actual = getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""
            horas_bloqueadas_actuales = self._parsear_horas_bloqueadas(bloqueo_actual)
            
            # Filtrar horas que ya están bloqueadas
            horas_a_bloquear = []
            for h, _, _, _, _ in horas_problematicas[:5]:  # Top 5 más problemáticas
                if h not in horas_bloqueadas_actuales:
                    horas_a_bloquear.append(h)
            
            if horas_a_bloquear:
                mejoras.append({
                    "tipo": "HORARIOS",
                    "descripcion": "Bloquear horas problemáticas",
                    "cambios": {
                        "DERIV_BLOQUEO_HORAS_LOCAL": ("actual", horas_a_bloquear),
                    },
                    "razon": f"{len(horas_a_bloquear)} horas problemáticas no bloqueadas (de {len(horas_problematicas)} detectadas)"
                })
            elif horas_problematicas:
                # Todas las horas problemáticas ya están bloqueadas
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS("✅ Todas las horas problemáticas ya están bloqueadas"))

        # Mejora 3: Aumentar duración si el movimiento es pequeño
        dur_actual = getattr(settings, "DERIV_DURACION_TICKS", 5)
        if ops_con_spots and movimientos_ganadas:
            mov_gan_med = statistics.median([abs(m["movimiento"]) for m in movimientos_ganadas])
            # Si el movimiento mediano es muy pequeño, aumentar duración podría ayudar
            if mov_gan_med < 0.3:  # Movimiento muy pequeño
                dur_sugerida = min(dur_actual + 2, 10)  # Aumentar 2 ticks, máximo 10
                mejoras.append({
                    "tipo": "DURACION",
                    "descripcion": "Aumentar duración de contratos",
                    "cambios": {
                        "DERIV_DURACION_TICKS": (dur_actual, dur_sugerida),
                    },
                    "razon": f"Movimiento mediano ({mov_gan_med:.4f}) es pequeño. Más tiempo podría capturar más movimiento"
                })

        # Mostrar mejoras
        for i, mejora in enumerate(mejoras, 1):
            self.stdout.write("")
            self.stdout.write(f"MEJORA {i}: {mejora['tipo']} - {mejora['descripcion']}")
            self.stdout.write(f"Razón: {mejora['razon']}")
            self.stdout.write("Cambios propuestos:")
            for param, (actual, nuevo) in mejora['cambios'].items():
                if isinstance(nuevo, list):
                    self.stdout.write(f"  {param}: Agregar horas {nuevo} a bloqueo actual")
                else:
                    self.stdout.write(f"  {param}: {actual} → {nuevo}")

        # Aplicar si se solicita
        if aplicar and mejoras:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("⚠️  Modo --aplicar activado. Las mejoras se guardarán en .env"))
            self.stdout.write("   (Esta funcionalidad requiere implementación manual)")
        elif mejoras:
            self.stdout.write("")
            self.stdout.write("💡 Para aplicar estas mejoras, edita manualmente el archivo .env")
            self.stdout.write("   O ejecuta con --aplicar (requiere implementación)")

        self.stdout.write("")
        self.stdout.write("=" * 100)

    def _parsear_horas_bloqueadas(self, bloqueo_horas: str) -> set[int]:
        """Parsea DERIV_BLOQUEO_HORAS_LOCAL y retorna set de horas bloqueadas."""
        horas = set()
        if not bloqueo_horas:
            return horas
        for part in bloqueo_horas.replace(" ", "").split(","):
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    for h in range(int(a), int(b) + 1):
                        if 0 <= h <= 23:
                            horas.add(h)
                except ValueError:
                    pass
            else:
                try:
                    h = int(part)
                    if 0 <= h <= 23:
                        horas.add(h)
                except ValueError:
                    pass
        return horas

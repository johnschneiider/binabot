from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_riesgo.models import OperacionDeriv


class Command(BaseCommand):
    help = "Analiza la importancia y efectividad de cada variable del vector para mejorar el modelo."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--dias", type=int, default=30, help="Días hacia atrás para analizar (default: 30)")
        parser.add_argument("--min-ops", type=int, default=50, help="Mínimo de operaciones requeridas (default: 50)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        dias = int(opts.get("dias") or 30)
        min_ops = int(opts.get("min_ops") or 50)

        tz = ZoneInfo("America/Bogota")
        desde_dt = timezone.now() - timedelta(days=dias)
        desde_epoch = int(desde_dt.timestamp())

        ops = list(
            OperacionDeriv.objects.filter(
                creada_por_bot=True,
                estado="CERRADA",
                opened_epoch__gte=desde_epoch,
            )
            .order_by("-opened_epoch")
        )

        if len(ops) < min_ops:
            self.stdout.write(f"⚠️  Solo hay {len(ops)} operaciones (mínimo: {min_ops})")
            self.stdout.write("   Considera reducir --min-ops o aumentar --dias")
            return

        self.stdout.write("=" * 80)
        self.stdout.write("ANÁLISIS DE VECTORES Y VARIABLES")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Período: {dias} días")
        self.stdout.write(f"Operaciones analizadas: {len(ops)}")
        self.stdout.write("")

        # ===== 1. IMPORTANCIA DE VARIABLES (CORRELACIÓN CON PROFIT) =====
        self.stdout.write("─" * 80)
        self.stdout.write("1. IMPORTANCIA DE VARIABLES (Correlación con Profit)")
        self.stdout.write("─" * 80)

        # Extraer datos de cada operación
        datos_ops = []
        for op in ops:
            if not op.pesos_usados_json or not op.senal_top_contribuciones_json:
                continue

            try:
                pesos = json.loads(op.pesos_usados_json) if isinstance(op.pesos_usados_json, str) else op.pesos_usados_json
                contribuciones = json.loads(op.senal_top_contribuciones_json) if isinstance(op.senal_top_contribuciones_json, str) else op.senal_top_contribuciones_json

                datos_ops.append({
                    "profit": float(op.profit or 0),
                    "ganadora": float(op.profit or 0) > 0,
                    "senal": float(op.senal_valor or 0),
                    "pesos": pesos,
                    "contribuciones": contribuciones,
                })
            except Exception:
                continue

        if len(datos_ops) < min_ops:
            self.stdout.write(f"⚠️  Solo {len(datos_ops)} operaciones tienen datos completos")
            return

        # Analizar cada variable
        variables = [
            "retorno_instantaneo",
            "ema_rapida",
            "ema_lenta",
            "rsi_ticks",
            "volatilidad_local",
            "skewness",
            "kurtosis",
            "tasa_ticks",
        ]

        stats_por_variable = {}
        for var in variables:
            valores_ganadoras = []
            valores_perdedoras = []
            contribuciones_ganadoras = []
            contribuciones_perdedoras = []
            pesos_list = []

            for dato in datos_ops:
                peso = dato["pesos"].get(var, 0)
                pesos_list.append(peso)

                # Buscar contribución de esta variable
                contrib = 0
                for contrib_item in dato["contribuciones"]:
                    if contrib_item.get("variable") == var:
                        contrib = contrib_item.get("contribucion", 0)
                        break

                if dato["ganadora"]:
                    valores_ganadoras.append(contrib)
                    contribuciones_ganadoras.append(contrib)
                else:
                    valores_perdedoras.append(contrib)
                    contribuciones_perdedoras.append(contrib)

            if valores_ganadoras and valores_perdedoras:
                media_ganadoras = statistics.mean(valores_ganadoras) if valores_ganadoras else 0
                media_perdedoras = statistics.mean(valores_perdedoras) if valores_perdedoras else 0
                diferencia = media_ganadoras - media_perdedoras

                # Calcular correlación simple (signo de diferencia)
                efectividad = "✅ BUENA" if diferencia > 0 else "❌ MALA" if diferencia < 0 else "➖ NEUTRA"

                stats_por_variable[var] = {
                    "peso_promedio": statistics.mean(pesos_list) if pesos_list else 0,
                    "contrib_ganadoras": media_ganadoras,
                    "contrib_perdedoras": media_perdedoras,
                    "diferencia": diferencia,
                    "efectividad": efectividad,
                    "count_ganadoras": len(valores_ganadoras),
                    "count_perdedoras": len(valores_perdedoras),
                }

        # Ordenar por diferencia (más efectivas primero)
        variables_ordenadas = sorted(
            stats_por_variable.items(),
            key=lambda x: x[1]["diferencia"],
            reverse=True,
        )

        self.stdout.write(f"{'Variable':<25} {'Peso':<10} {'Contrib G':<12} {'Contrib P':<12} {'Diferencia':<12} {'Efectividad':<15}")
        self.stdout.write("-" * 80)
        for var, stats in variables_ordenadas:
            self.stdout.write(
                f"{var:<25} "
                f"{stats['peso_promedio']:>9.4f} "
                f"{stats['contrib_ganadoras']:>11.4f} "
                f"{stats['contrib_perdedoras']:>11.4f} "
                f"{stats['diferencia']:>11.4f} "
                f"{stats['efectividad']:<15}"
            )

        self.stdout.write("")

        # ===== 2. ANÁLISIS DE SEÑALES =====
        self.stdout.write("─" * 80)
        self.stdout.write("2. ANÁLISIS DE SEÑALES")
        self.stdout.write("─" * 80)

        senales_ganadoras = [d["senal"] for d in datos_ops if d["ganadora"]]
        senales_perdedoras = [d["senal"] for d in datos_ops if not d["ganadora"]]

        if senales_ganadoras and senales_perdedoras:
            self.stdout.write(f"Señal promedio (ganadoras): {statistics.mean(senales_ganadoras):.6f}")
            self.stdout.write(f"Señal promedio (perdedoras): {statistics.mean(senales_perdedoras):.6f}")
            diferencia_senal = statistics.mean(senales_ganadoras) - statistics.mean(senales_perdedoras)
            self.stdout.write(f"Diferencia: {diferencia_senal:.6f}")

            if diferencia_senal > 0:
                self.stdout.write("  ✅ Las ganadoras tienen señales MÁS FUERTES (correcto)")
            else:
                self.stdout.write("  ❌ Las perdedoras tienen señales MÁS FUERTES (PROBLEMA)")
                self.stdout.write("     → El modelo no está discriminando correctamente")

        self.stdout.write("")

        # ===== 3. VARIABLES MÁS INFLUYENTES =====
        self.stdout.write("─" * 80)
        self.stdout.write("3. VARIABLES MÁS INFLUYENTES (Por contribución absoluta)")
        self.stdout.write("─" * 80)

        contrib_absoluta_por_var = defaultdict(list)
        for dato in datos_ops:
            for contrib_item in dato["contribuciones"]:
                var = contrib_item.get("variable")
                contrib_abs = abs(contrib_item.get("contribucion", 0))
                contrib_absoluta_por_var[var].append(contrib_abs)

        contrib_promedio = {
            var: statistics.mean(vals) if vals else 0
            for var, vals in contrib_absoluta_por_var.items()
        }

        contrib_ordenadas = sorted(contrib_promedio.items(), key=lambda x: x[1], reverse=True)

        self.stdout.write(f"{'Variable':<25} {'Contrib Abs Promedio':<20}")
        self.stdout.write("-" * 50)
        for var, contrib in contrib_ordenadas:
            self.stdout.write(f"{var:<25} {contrib:>19.6f}")

        self.stdout.write("")

        # ===== 4. RECOMENDACIONES =====
        self.stdout.write("─" * 80)
        self.stdout.write("4. RECOMENDACIONES")
        self.stdout.write("─" * 80)

        recomendaciones = []

        # Variables que perjudican
        variables_malas = [var for var, stats in stats_por_variable.items() if stats["diferencia"] < -0.001]
        if variables_malas:
            recomendaciones.append(f"❌ Considera reducir o eliminar estas variables: {', '.join(variables_malas)}")

        # Variables que ayudan
        variables_buenas = [var for var, stats in stats_por_variable.items() if stats["diferencia"] > 0.001]
        if variables_buenas:
            recomendaciones.append(f"✅ Estas variables son efectivas: {', '.join(variables_buenas)}")

        # Señal débil
        if senales_ganadoras and senales_perdedoras:
            if diferencia_senal <= 0:
                recomendaciones.append("⚠️  Recalibra los pesos: las señales no discriminan correctamente")
                recomendaciones.append("   → Ejecuta: python manage.py calibrar_pesos_walkforward --symbol R_10 --solo-put --ticks 10000")

        # Variables con peso bajo pero alta contribución
        for var, stats in stats_por_variable.items():
            peso_abs = abs(stats["peso_promedio"])
            contrib_abs = abs(stats["diferencia"])
            if peso_abs < 0.01 and contrib_abs > 0.01:
                recomendaciones.append(f"💡 Variable '{var}' tiene bajo peso pero alta diferencia - considera aumentar su peso")

        if recomendaciones:
            for i, rec in enumerate(recomendaciones, 1):
                self.stdout.write(f"{i}. {rec}")
        else:
            self.stdout.write("✅ No se encontraron problemas críticos")

        self.stdout.write("")

        # ===== 5. SUGERENCIAS DE NUEVAS VARIABLES =====
        self.stdout.write("─" * 80)
        self.stdout.write("5. SUGERENCIAS DE MEJORAS")
        self.stdout.write("─" * 80)

        sugerencias = [
            "📊 Considera agregar variables de momentum:",
            "   - MACD (diferencia entre EMAs)",
            "   - Momentum de N ticks",
            "",
            "📈 Considera agregar variables de volatilidad:",
            "   - ATR (Average True Range)",
            "   - Bollinger Bands distance",
            "",
            "🔄 Considera agregar variables de tiempo:",
            "   - Hora del día (puede tener patrones)",
            "   - Día de la semana",
            "",
            "📉 Considera agregar variables de volumen (si disponible):",
            "   - Volumen relativo",
            "   - Tick volume",
            "",
            "🎯 Considera interacciones entre variables:",
            "   - RSI * Volatilidad (regímenes de mercado)",
            "   - EMA_Rapida - EMA_Lenta (momentum)",
        ]

        for sug in sugerencias:
            self.stdout.write(sug)

        self.stdout.write("")

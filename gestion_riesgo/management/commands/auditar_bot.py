from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion_riesgo.models import BalanceDerivSnapshot, Cuenta, OperacionDeriv, TickDerivSnapshot


class Command(BaseCommand):
    help = "Auditoría completa del bot: estado, ticks, operaciones, winrate, errores y recomendaciones."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--dias", type=int, default=7, help="Días hacia atrás para análisis histórico (default: 7)")
        parser.add_argument("--completo", action="store_true", help="Análisis exhaustivo (más lento pero más detallado)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        dias = int(opts.get("dias") or 7)
        completo = bool(opts.get("completo"))

        tz = ZoneInfo("America/Bogota")
        ahora_epoch = int(time.time())
        ahora_dt = datetime.fromtimestamp(ahora_epoch, tz=tz)
        desde_dt = timezone.now() - timedelta(days=dias)
        desde_epoch = int(desde_dt.timestamp())

        # Obtener cuenta activa
        simbolo_activo = getattr(settings, "DERIV_SYMBOL", "R_10")
        cuenta = Cuenta.objects.filter(simbolo=simbolo_activo).order_by("id").first()

        if not cuenta:
            self.stdout.write(self.style.ERROR("❌ No hay cuenta configurada en la base de datos."))
            return

        problemas_detectados = []
        advertencias = []

        self.stdout.write("=" * 100)
        self.stdout.write(self.style.SUCCESS("AUDITORÍA COMPLETA DEL BOT"))
        self.stdout.write("=" * 100)
        self.stdout.write(f"Fecha/Hora: {ahora_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        self.stdout.write(f"Cuenta ID: {cuenta.id} | Símbolo: {cuenta.simbolo}")
        self.stdout.write(f"Período de análisis: últimos {dias} días")
        self.stdout.write("")

        # ===== 1. ESTADO Y CONFIGURACIÓN =====
        self.stdout.write("─" * 100)
        self.stdout.write("1. ESTADO Y CONFIGURACIÓN")
        self.stdout.write("─" * 100)

        # Estado de bloqueo
        bloqueado = getattr(cuenta, "bloqueado", False)
        riesgo_motivo = getattr(cuenta, "riesgo_motivo", "") or "N/A"
        if bloqueado:
            self.stdout.write(self.style.ERROR(f"🔴 BLOQUEADO: Sí - Motivo: {riesgo_motivo}"))
            problemas_detectados.append(f"Bot bloqueado: {riesgo_motivo}")
        else:
            self.stdout.write(self.style.SUCCESS(f"🟢 BLOQUEADO: No"))

        # Pausa de ciclo
        ciclo_pausa_hasta = getattr(cuenta, "ciclo_pausa_hasta_epoch", None)
        if ciclo_pausa_hasta:
            resta_seg = ciclo_pausa_hasta - ahora_epoch
            if resta_seg > 0:
                resta_min = resta_seg / 60
                self.stdout.write(f"   ⚠️  Pausa de ciclo activa: {resta_min:.1f} minutos restantes")
                advertencias.append(f"Pausa de ciclo activa ({resta_min:.1f} min restantes)")
            else:
                self.stdout.write(f"   ✅ Pausa de ciclo expirada (debería estar desbloqueado)")

        # Configuración clave
        self.stdout.write("")
        self.stdout.write("Configuración:")
        self.stdout.write(f"  DERIV_SYMBOL: {simbolo_activo}")
        self.stdout.write(f"  DERIV_MODO_REAL: {getattr(settings, 'DERIV_MODO_REAL', False)}")
        self.stdout.write(f"  DERIV_DURACION_TICKS: {getattr(settings, 'DERIV_DURACION_TICKS', 5)}")
        self.stdout.write(f"  DERIV_CONTRACT_TYPES_PERMITIDOS: {getattr(settings, 'DERIV_CONTRACT_TYPES_PERMITIDOS', ['PUT', 'CALL'])}")
        bloqueo_horas = getattr(settings, "DERIV_BLOQUEO_HORAS_LOCAL", "") or ""
        self.stdout.write(f"  DERIV_BLOQUEO_HORAS_LOCAL: {bloqueo_horas or 'Ninguna'}")
        hora_actual = ahora_dt.hour
        horas_bloqueadas_set = self._parsear_horas_bloqueadas(bloqueo_horas)
        if hora_actual in horas_bloqueadas_set:
            self.stdout.write(self.style.WARNING(f"  ⚠️  Hora actual ({hora_actual:02d}:00) está bloqueada"))
            advertencias.append(f"Hora actual bloqueada ({hora_actual:02d}:00)")

        self.stdout.write("")

        # ===== 2. ANÁLISIS DE TICKS =====
        self.stdout.write("─" * 100)
        self.stdout.write("2. ANÁLISIS DE TICKS")
        self.stdout.write("─" * 100)

        ticks = list(TickDerivSnapshot.objects.filter(cuenta=cuenta).order_by("-epoch")[:200])
        ticks_recientes = [t for t in ticks if t.epoch >= desde_epoch]

        if not ticks:
            self.stdout.write(self.style.ERROR("❌ No hay ticks en la base de datos"))
            problemas_detectados.append("No hay ticks registrados - posible problema de conexión WebSocket")
        else:
            ultimo_tick = ticks[0]
            seg_desde_tick = ahora_epoch - ultimo_tick.epoch
            tick_dt = datetime.fromtimestamp(ultimo_tick.epoch, tz=tz)

            self.stdout.write(f"Total ticks en BD: {len(ticks)}")
            self.stdout.write(f"Último tick: {tick_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} (hace {seg_desde_tick}s)")
            self.stdout.write(f"Precio último tick: {ultimo_tick.precio:.5f}")

            if seg_desde_tick > 300:
                self.stdout.write(self.style.ERROR(f"  ⚠️  ADVERTENCIA: No hay ticks desde hace {seg_desde_tick/60:.1f} minutos"))
                problemas_detectados.append(f"Ticks detenidos hace {seg_desde_tick/60:.1f} minutos")
            elif seg_desde_tick > 60:
                self.stdout.write(self.style.WARNING(f"  ⚠️  Último tick hace {seg_desde_tick:.0f} segundos"))
                advertencias.append(f"Último tick hace {seg_desde_tick:.0f}s")
            else:
                self.stdout.write(self.style.SUCCESS("  ✅ Ticks llegando normalmente"))

            # Análisis de calidad de ticks
            if len(ticks) >= 2:
                self.stdout.write("")
                self.stdout.write("Calidad de ticks:")

                # Gaps temporales
                gaps_grandes = []
                ticks_ordenados = sorted(ticks, key=lambda t: t.epoch)
                for i in range(1, min(100, len(ticks_ordenados))):
                    gap = ticks_ordenados[i].epoch - ticks_ordenados[i-1].epoch
                    if gap > 120:  # Más de 2 minutos
                        gaps_grandes.append((ticks_ordenados[i-1].epoch, gap))

                if gaps_grandes:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  Gaps temporales detectados: {len(gaps_grandes)}"))
                    advertencias.append(f"{len(gaps_grandes)} gaps temporales en ticks")
                    if completo:
                        for epoch_ant, gap in gaps_grandes[:5]:
                            dt_gap = datetime.fromtimestamp(epoch_ant, tz=tz)
                            self.stdout.write(f"    Gap de {gap}s en {dt_gap.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    self.stdout.write(self.style.SUCCESS("  ✅ Sin gaps temporales significativos"))

                # Duplicados
                epochs_vistos = {}
                duplicados = 0
                for tick in ticks_ordenados:
                    if tick.epoch in epochs_vistos:
                        duplicados += 1
                    else:
                        epochs_vistos[tick.epoch] = tick

                if duplicados > 0:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  Ticks duplicados detectados: {duplicados}"))
                    advertencias.append(f"{duplicados} ticks duplicados")
                else:
                    self.stdout.write(self.style.SUCCESS("  ✅ Sin ticks duplicados"))

                # Frecuencia promedio
                if len(ticks_ordenados) >= 2:
                    tiempo_total = ticks_ordenados[-1].epoch - ticks_ordenados[0].epoch
                    if tiempo_total > 0:
                        freq_prom = len(ticks_ordenados) / tiempo_total
                        self.stdout.write(f"  Frecuencia promedio: {freq_prom:.3f} ticks/segundo")

            # Ticks en período de análisis
            if ticks_recientes:
                self.stdout.write(f"")
                self.stdout.write(f"Ticks en últimos {dias} días: {len(ticks_recientes)}")
                if len(ticks_recientes) < 10:
                    advertencias.append(f"Pocos ticks en período de análisis ({len(ticks_recientes)})")

        self.stdout.write("")

        # ===== 3. ANÁLISIS DE OPERACIONES =====
        self.stdout.write("─" * 100)
        self.stdout.write("3. ANÁLISIS DE OPERACIONES")
        self.stdout.write("─" * 100)

        ops_all = list(
            OperacionDeriv.objects.filter(
                cuenta=cuenta,
                creada_por_bot=True,
                opened_epoch__gte=desde_epoch
            ).order_by("-opened_epoch")
        )

        if not ops_all:
            self.stdout.write(f"⚠️  No hay operaciones en los últimos {dias} días")
            advertencias.append(f"No hay operaciones en últimos {dias} días")
        else:
            cerradas = [op for op in ops_all if op.estado == "CERRADA" and op.profit is not None]
            abiertas = [op for op in ops_all if op.estado == "ABIERTA"]
            ganadas = [op for op in cerradas if op.profit > 0]
            perdidas = [op for op in cerradas if op.profit < 0]

            self.stdout.write(f"Total operaciones: {len(ops_all)}")
            self.stdout.write(f"  Cerradas: {len(cerradas)}")
            self.stdout.write(f"  Abiertas: {len(abiertas)}")
            if abiertas:
                self.stdout.write(self.style.WARNING(f"  ⚠️  {len(abiertas)} operación(es) abierta(s)"))
                advertencias.append(f"{len(abiertas)} operación(es) abierta(s)")

            if cerradas:
                total_profit = sum(op.profit for op in cerradas)
                winrate = len(ganadas) * 100 / len(cerradas) if cerradas else 0
                profit_prom = total_profit / len(cerradas) if cerradas else 0

                self.stdout.write("")
                self.stdout.write("Estadísticas:")
                self.stdout.write(f"  Ganadas: {len(ganadas)} ({winrate:.1f}%)")
                self.stdout.write(f"  Perdidas: {len(perdidas)} ({100-winrate:.1f}%)")
                self.stdout.write(f"  Profit total: {total_profit:.2f} USD")
                self.stdout.write(f"  Profit promedio: {profit_prom:.2f} USD")

                if winrate < 50:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  Winrate bajo ({winrate:.1f}%)"))
                    problemas_detectados.append(f"Winrate bajo: {winrate:.1f}%")
                elif winrate >= 60:
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Winrate bueno ({winrate:.1f}%)"))

                # Análisis por hora
                if completo:
                    self.stdout.write("")
                    self.stdout.write("Análisis por hora (últimas 24h):")
                    por_hora = defaultdict(list)
                    ops_24h = [op for op in cerradas if op.opened_epoch and (ahora_epoch - op.opened_epoch) <= 86400]
                    for op in ops_24h:
                        hora = datetime.fromtimestamp(op.opened_epoch, tz).hour
                        por_hora[hora].append(op)

                    if por_hora:
                        fmt = "{:<5} {:<8} {:<10} {:<12}"
                        self.stdout.write(fmt.format("Hora", "Total", "Winrate %", "Profit Total"))
                        self.stdout.write("-" * 40)
                        for h in sorted(por_hora.keys()):
                            ops_h = por_hora[h]
                            gan_h = [op for op in ops_h if op.profit > 0]
                            wr_h = len(gan_h) * 100 / len(ops_h) if ops_h else 0
                            profit_h = sum(op.profit for op in ops_h)
                            self.stdout.write(fmt.format(f"{h:02d}:00", len(ops_h), f"{wr_h:.1f}", f"{profit_h:.2f}"))

                # Análisis por tipo de contrato
                por_tipo = defaultdict(list)
                for op in cerradas:
                    tipo = op.contract_type or "UNKNOWN"
                    por_tipo[tipo].append(op)

                if len(por_tipo) > 1:
                    self.stdout.write("")
                    self.stdout.write("Análisis por tipo de contrato:")
                    fmt = "{:<10} {:<8} {:<10} {:<12}"
                    self.stdout.write(fmt.format("Tipo", "Total", "Winrate %", "Profit Total"))
                    self.stdout.write("-" * 40)
                    for tipo in sorted(por_tipo.keys()):
                        ops_t = por_tipo[tipo]
                        gan_t = [op for op in ops_t if op.profit > 0]
                        wr_t = len(gan_t) * 100 / len(ops_t) if ops_t else 0
                        profit_t = sum(op.profit for op in ops_t)
                        self.stdout.write(fmt.format(tipo, len(ops_t), f"{wr_t:.1f}", f"{profit_t:.2f}"))

                # Detección de inconsistencias en datos
                self.stdout.write("")
                self.stdout.write("Verificación de integridad de datos:")
                ops_sin_entry_spot = [op for op in cerradas if op.entry_spot is None]
                ops_sin_exit_spot = [op for op in cerradas if op.exit_spot is None]
                ops_sin_profit = [op for op in cerradas if op.profit is None]

                if ops_sin_entry_spot:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  {len(ops_sin_entry_spot)} operaciones sin entry_spot"))
                    advertencias.append(f"{len(ops_sin_entry_spot)} operaciones sin entry_spot")
                else:
                    self.stdout.write(self.style.SUCCESS("  ✅ Todas las operaciones tienen entry_spot"))

                if ops_sin_exit_spot:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  {len(ops_sin_exit_spot)} operaciones sin exit_spot"))
                    advertencias.append(f"{len(ops_sin_exit_spot)} operaciones sin exit_spot")
                else:
                    self.stdout.write(self.style.SUCCESS("  ✅ Todas las operaciones tienen exit_spot"))

                if ops_sin_profit:
                    self.stdout.write(self.style.ERROR(f"  ❌ {len(ops_sin_profit)} operaciones sin profit"))
                    problemas_detectados.append(f"{len(ops_sin_profit)} operaciones sin profit")
                else:
                    self.stdout.write(self.style.SUCCESS("  ✅ Todas las operaciones tienen profit"))

        self.stdout.write("")

        # ===== 4. ANÁLISIS DE BALANCE =====
        self.stdout.write("─" * 100)
        self.stdout.write("4. ANÁLISIS DE BALANCE")
        self.stdout.write("─" * 100)

        balance_actual = cuenta.balance_deriv
        balance_max = cuenta.max_balance_deriv_historico
        moneda = cuenta.moneda_deriv or "USD"

        if balance_actual is None:
            self.stdout.write(self.style.ERROR("❌ Balance actual no disponible"))
            problemas_detectados.append("Balance actual no disponible")
        else:
            self.stdout.write(f"Balance actual: {balance_actual:.2f} {moneda}")
            if balance_max:
                self.stdout.write(f"Balance máximo histórico: {balance_max:.2f} {moneda}")
                if balance_max > balance_actual:
                    drawdown = ((balance_max - balance_actual) / balance_max) * 100
                    self.stdout.write(f"Drawdown: {drawdown:.2f}%")
                    if drawdown > 20:
                        self.stdout.write(self.style.ERROR(f"  ⚠️  Drawdown alto ({drawdown:.2f}%)"))
                        problemas_detectados.append(f"Drawdown alto: {drawdown:.2f}%")
                else:
                    self.stdout.write(self.style.SUCCESS("  ✅ Balance en máximo histórico"))

            # Snapshots recientes
            snapshots = BalanceDerivSnapshot.objects.filter(
                cuenta=cuenta,
                created_at__gte=desde_dt
            ).order_by("-created_at")[:100]

            if snapshots:
                balances = [s.balance for s in snapshots]
                balance_min = min(balances)
                balance_max_periodo = max(balances)
                balance_prom = sum(balances) / len(balances)
                variacion = balance_max_periodo - balance_min

                self.stdout.write("")
                self.stdout.write(f"Balance en período ({dias} días):")
                self.stdout.write(f"  Mínimo: {balance_min:.2f} {moneda}")
                self.stdout.write(f"  Máximo: {balance_max_periodo:.2f} {moneda}")
                self.stdout.write(f"  Promedio: {balance_prom:.2f} {moneda}")
                self.stdout.write(f"  Variación: {variacion:.2f} {moneda} ({variacion/balance_min*100 if balance_min > 0 else 0:.2f}%)")

                # Verificar consistencia con operaciones
                if cerradas:
                    profit_ops = sum(op.profit for op in cerradas)
                    variacion_balance = balance_actual - (snapshots[-1].balance if snapshots else balance_actual)
                    if abs(profit_ops - variacion_balance) > 10:  # Tolerancia de 10 USD
                        self.stdout.write(self.style.WARNING(
                            f"  ⚠️  Inconsistencia: Profit operaciones ({profit_ops:.2f}) vs variación balance ({variacion_balance:.2f})"
                        ))
                        advertencias.append("Inconsistencia entre profit operaciones y variación de balance")

        self.stdout.write("")

        # ===== 5. DETECCIÓN DE ERRORES =====
        self.stdout.write("─" * 100)
        self.stdout.write("5. DETECCIÓN DE ERRORES Y PROBLEMAS")
        self.stdout.write("─" * 100)

        # Verificar operaciones con estados anómalos
        ops_abiertas_antiguas = [
            op for op in abiertas
            if op.opened_epoch and (ahora_epoch - op.opened_epoch) > 3600
        ]
        if ops_abiertas_antiguas:
            self.stdout.write(self.style.ERROR(f"  ❌ {len(ops_abiertas_antiguas)} operación(es) abierta(s) por más de 1 hora"))
            problemas_detectados.append(f"{len(ops_abiertas_antiguas)} operación(es) abierta(s) por más de 1 hora")

        # Verificar última operación
        ultima_op = OperacionDeriv.objects.filter(
            cuenta=cuenta,
            creada_por_bot=True
        ).order_by("-created_at").first()

        if ultima_op:
            seg_desde_op = (ahora_epoch - int(ultima_op.opened_epoch)) if ultima_op.opened_epoch else None
            if seg_desde_op and seg_desde_op > 86400:  # Más de 24 horas
                self.stdout.write(self.style.WARNING(f"  ⚠️  Última operación hace {seg_desde_op/3600:.1f} horas"))
                advertencias.append(f"Última operación hace {seg_desde_op/3600:.1f} horas")

        # Verificar señales
        senal_valor = getattr(cuenta, "senal_valor", None)
        if senal_valor is None:
            self.stdout.write(self.style.WARNING("  ⚠️  No hay señal registrada"))
            advertencias.append("No hay señal registrada")
        else:
            self.stdout.write(f"  ✅ Señal actual: {senal_valor:.6f} (decisión: {getattr(cuenta, 'senal_decision', 'N/A')})")

        # Verificar última actualización de cuenta
        if cuenta.updated_at:
            seg_desde_update = (timezone.now() - cuenta.updated_at).total_seconds()
            if seg_desde_update > 300:
                self.stdout.write(self.style.WARNING(f"  ⚠️  Cuenta no actualizada desde hace {seg_desde_update/60:.1f} minutos"))
                advertencias.append(f"Cuenta no actualizada desde hace {seg_desde_update/60:.1f} min")

        self.stdout.write("")

        # ===== 6. RESUMEN Y RECOMENDACIONES =====
        self.stdout.write("=" * 100)
        self.stdout.write("RESUMEN Y RECOMENDACIONES")
        self.stdout.write("=" * 100)

        if problemas_detectados:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("🔴 PROBLEMAS DETECTADOS:"))
            for i, problema in enumerate(problemas_detectados, 1):
                self.stdout.write(self.style.ERROR(f"  {i}. {problema}"))

        if advertencias:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("⚠️  ADVERTENCIAS:"))
            for i, advertencia in enumerate(advertencias, 1):
                self.stdout.write(self.style.WARNING(f"  {i}. {advertencia}"))

        if not problemas_detectados and not advertencias:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("✅ No se detectaron problemas críticos"))

        # Recomendaciones específicas
        self.stdout.write("")
        self.stdout.write("RECOMENDACIONES:")

        if bloqueado:
            self.stdout.write("  → Revisar motivo de bloqueo y condiciones de riesgo")
        if seg_desde_tick > 300:
            self.stdout.write("  → Verificar conexión WebSocket y logs del bot")
        if winrate < 50 and cerradas:
            self.stdout.write("  → Considerar ajustar estrategia o bloquear horas problemáticas")
        if ops_abiertas_antiguas:
            self.stdout.write("  → Revisar operaciones abiertas antiguas (posible problema de cierre)")
        if not ops_all:
            self.stdout.write("  → Verificar que el bot esté operando (revisar señales y umbrales)")

        self.stdout.write("")
        self.stdout.write("=" * 100)
        self.stdout.write("Auditoría completada")
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

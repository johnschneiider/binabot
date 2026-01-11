from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from gestion_riesgo.models import BalanceDerivSnapshot, Cuenta
from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS


class Command(BaseCommand):
    help = "Diagnóstico y reparación de la gráfica de balance: verifica snapshots y los crea si faltan."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--forzar", action="store_true", help="Fuerza creación de snapshots aunque sean recientes")
        parser.add_argument("--limpiar-viejos", action="store_true", help="Elimina snapshots muy antiguos (>30 días)")

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        forzar = bool(opts.get("forzar"))
        limpiar_viejos = bool(opts.get("limpiar_viejos"))

        tz = ZoneInfo("America/Bogota")
        ahora_epoch = int(time.time())
        ahora_dt = datetime.fromtimestamp(ahora_epoch, tz=tz)

        cuenta = Cuenta.objects.first()
        if not cuenta:
            self.stdout.write("❌ No hay cuenta configurada.")
            return

        self.stdout.write("=" * 80)
        self.stdout.write("DIAGNÓSTICO Y REPARACIÓN DE GRÁFICA")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Hora actual: {ahora_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        self.stdout.write("")

        # ===== 1. VERIFICAR CONFIGURACIÓN =====
        self.stdout.write("─" * 80)
        self.stdout.write("1. CONFIGURACIÓN")
        self.stdout.write("─" * 80)
        snapshot_cada_seg = int(getattr(settings, "BALANCE_SNAPSHOT_CADA_SEG", 60))
        balance_poll_cada_seg = float(getattr(settings, "DERIV_BALANCE_POLL_CADA_SEG", 60.0))
        self.stdout.write(f"BALANCE_SNAPSHOT_CADA_SEG: {snapshot_cada_seg} segundos")
        self.stdout.write(f"DERIV_BALANCE_POLL_CADA_SEG: {balance_poll_cada_seg} segundos")
        self.stdout.write("")

        # ===== 2. VERIFICAR SNAPSHOTS EXISTENTES =====
        self.stdout.write("─" * 80)
        self.stdout.write("2. SNAPSHOTS EXISTENTES")
        self.stdout.write("─" * 80)

        snapshots = BalanceDerivSnapshot.objects.filter(cuenta=cuenta).order_by("-created_at")
        total_snapshots = snapshots.count()

        self.stdout.write(f"Total snapshots en BD: {total_snapshots}")

        if total_snapshots > 0:
            ultimo_snapshot = snapshots.first()
            ultimo_dt = ultimo_snapshot.created_at.astimezone(tz)
            seg_desde_ultimo = (ahora_epoch - int(ultimo_snapshot.epoch)) if ultimo_snapshot.epoch else None
            if not seg_desde_ultimo:
                seg_desde_ultimo = int((timezone.now() - ultimo_snapshot.created_at).total_seconds())

            self.stdout.write(f"Último snapshot: {ultimo_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            self.stdout.write(f"Balance último snapshot: {ultimo_snapshot.balance:.2f} {ultimo_snapshot.moneda}")
            self.stdout.write(f"Segundos desde último snapshot: {seg_desde_ultimo}")

            if seg_desde_ultimo > snapshot_cada_seg * 3:
                self.stdout.write(f"  ⚠️  ADVERTENCIA: No hay snapshots recientes (debería haber uno cada {snapshot_cada_seg}s)")
            else:
                self.stdout.write(f"  ✅ Snapshots recientes")

            # Snapshots en las últimas 24 horas
            desde_24h = timezone.now() - timedelta(hours=24)
            snapshots_24h = snapshots.filter(created_at__gte=desde_24h).count()
            self.stdout.write(f"Snapshots en últimas 24h: {snapshots_24h}")
            esperados_24h = int((24 * 3600) / snapshot_cada_seg)
            self.stdout.write(f"Esperados en 24h: ~{esperados_24h}")

            if snapshots_24h < esperados_24h * 0.5:
                self.stdout.write(f"  ⚠️  ADVERTENCIA: Faltan snapshots (solo {snapshots_24h} de ~{esperados_24h} esperados)")
        else:
            self.stdout.write("  ⚠️  No hay snapshots en la base de datos")
            ultimo_snapshot = None

        self.stdout.write("")

        # ===== 3. VERIFICAR BALANCE ACTUAL =====
        self.stdout.write("─" * 80)
        self.stdout.write("3. BALANCE ACTUAL")
        self.stdout.write("─" * 80)

        balance_bd = getattr(cuenta, "balance_deriv", None)
        self.stdout.write(f"Balance en BD: {balance_bd:.2f} {getattr(cuenta, 'moneda_deriv', 'USD')}" if balance_bd else "Balance en BD: N/A")

        # Intentar obtener balance desde Deriv API
        token = getattr(settings, "DERIV_API_TOKEN", "")
        if token:
            self.stdout.write("Obteniendo balance actual desde Deriv API...")
            try:
                import asyncio

                async def obtener_balance() -> tuple[float, str] | None:
                    try:
                        async with ClienteDerivWS(token=token) as cliente:
                            await cliente.enviar({"balance": 1})
                            respuesta = await cliente.recibir(timeout_segundos=10)
                            if respuesta.get("error"):
                                return None
                            balance_info = respuesta.get("balance", {})
                            if not balance_info:
                                return None
                            return (float(balance_info.get("balance", 0)), str(balance_info.get("currency", "USD")))
                    except Exception:
                        return None

                resultado = asyncio.run(obtener_balance())
                if resultado:
                    balance_api, currency_api = resultado
                    self.stdout.write(f"Balance desde API: {balance_api:.2f} {currency_api}")

                    # Actualizar BD si es diferente
                    if balance_bd is None or abs(float(balance_bd) - balance_api) > 0.01:
                        cuenta.balance_deriv = balance_api
                        cuenta.moneda_deriv = currency_api
                        cuenta.save()
                        self.stdout.write(f"  ✅ Balance actualizado en BD")
                        balance_bd = balance_api
                    else:
                        self.stdout.write(f"  ✅ Balance coincide con BD")
                else:
                    self.stdout.write("  ⚠️  No se pudo obtener balance desde API")
                    balance_bd = balance_bd or 0.0
            except Exception as e:
                self.stdout.write(f"  ⚠️  Error al obtener balance: {e}")
                balance_bd = balance_bd or 0.0
        else:
            self.stdout.write("  ⚠️  No hay DERIV_API_TOKEN configurado")
            balance_bd = balance_bd or 0.0

        self.stdout.write("")

        # ===== 4. CREAR SNAPSHOTS FALTANTES =====
        self.stdout.write("─" * 80)
        self.stdout.write("4. REPARACIÓN")
        self.stdout.write("─" * 80)

        if balance_bd and balance_bd > 0:
            # Verificar si necesitamos crear snapshots
            necesita_crear = False
            if total_snapshots == 0:
                necesita_crear = True
                self.stdout.write("  → No hay snapshots, creando uno inicial...")
            elif ultimo_snapshot:
                seg_desde_ultimo = int((timezone.now() - ultimo_snapshot.created_at).total_seconds())
                if seg_desde_ultimo > snapshot_cada_seg * 2 or forzar:
                    necesita_crear = True
                    self.stdout.write(f"  → Último snapshot hace {seg_desde_ultimo}s, creando nuevo...")

            if necesita_crear or forzar:
                try:
                    nuevo_snapshot = BalanceDerivSnapshot.objects.create(
                        cuenta=cuenta,
                        balance=float(balance_bd),
                        moneda=str(getattr(cuenta, "moneda_deriv", "USD")),
                        epoch=ahora_epoch,
                    )
                    self.stdout.write(f"  ✅ Snapshot creado: ID {nuevo_snapshot.id}, balance {nuevo_snapshot.balance:.2f}")
                except Exception as e:
                    self.stderr.write(f"  ❌ Error al crear snapshot: {e}")
            else:
                self.stdout.write("  ✅ Snapshots están actualizados")

            # Crear snapshots históricos si faltan muchos
            if total_snapshots > 0 and ultimo_snapshot:
                desde_ultimo = ultimo_snapshot.created_at
                hasta_ahora = timezone.now()
                diferencia_seg = int((hasta_ahora - desde_ultimo).total_seconds())
                snapshots_faltantes = int(diferencia_seg / snapshot_cada_seg)

                if snapshots_faltantes > 10 and not forzar:
                    self.stdout.write(f"  ⚠️  Faltan aproximadamente {snapshots_faltantes} snapshots")
                    self.stdout.write(f"     Ejecuta con --forzar para crear snapshots intermedios")
                elif forzar and snapshots_faltantes > 1:
                    # Crear snapshots intermedios (máximo 100 para no saturar)
                    crear = min(snapshots_faltantes, 100)
                    self.stdout.write(f"  → Creando {crear} snapshots intermedios...")
                    creados = 0
                    for i in range(1, crear + 1):
                        tiempo_intermedio = desde_ultimo + timedelta(seconds=int(snapshot_cada_seg * i))
                        if tiempo_intermedio >= hasta_ahora:
                            break
                        try:
                            BalanceDerivSnapshot.objects.create(
                                cuenta=cuenta,
                                balance=float(balance_bd),  # Usar balance actual como aproximación
                                moneda=str(getattr(cuenta, "moneda_deriv", "USD")),
                                epoch=int(tiempo_intermedio.timestamp()),
                            )
                            creados += 1
                        except Exception:
                            pass
                    self.stdout.write(f"  ✅ Creados {creados} snapshots intermedios")
        else:
            self.stdout.write("  ⚠️  No se puede crear snapshot: balance no disponible")

        self.stdout.write("")

        # ===== 5. LIMPIEZA DE SNAPSHOTS ANTIGUOS =====
        if limpiar_viejos:
            self.stdout.write("─" * 80)
            self.stdout.write("5. LIMPIEZA DE SNAPSHOTS ANTIGUOS")
            self.stdout.write("─" * 80)

            desde_30dias = timezone.now() - timedelta(days=30)
            snapshots_viejos = BalanceDerivSnapshot.objects.filter(
                cuenta=cuenta,
                created_at__lt=desde_30dias
            )

            cantidad_viejos = snapshots_viejos.count()
            if cantidad_viejos > 0:
                self.stdout.write(f"Snapshots antiguos (>30 días): {cantidad_viejos}")
                snapshots_viejos.delete()
                self.stdout.write(f"  ✅ Eliminados {cantidad_viejos} snapshots antiguos")
            else:
                self.stdout.write("  ✅ No hay snapshots antiguos para eliminar")

            self.stdout.write("")

        # ===== 6. RESUMEN FINAL =====
        self.stdout.write("=" * 80)
        self.stdout.write("RESUMEN")
        self.stdout.write("=" * 80)

        snapshots_final = BalanceDerivSnapshot.objects.filter(cuenta=cuenta).order_by("-created_at")
        total_final = snapshots_final.count()

        if total_final > 0:
            ultimo_final = snapshots_final.first()
            seg_desde_ultimo_final = int((timezone.now() - ultimo_final.created_at).total_seconds())
            self.stdout.write(f"Total snapshots: {total_final}")
            self.stdout.write(f"Último snapshot: {ultimo_final.created_at.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S %Z')}")
            self.stdout.write(f"Segundos desde último: {seg_desde_ultimo_final}")

            if seg_desde_ultimo_final <= snapshot_cada_seg * 2:
                self.stdout.write("  ✅ Gráfica debería actualizarse correctamente")
            else:
                self.stdout.write(f"  ⚠️  Último snapshot hace {seg_desde_ultimo_final}s")
                self.stdout.write(f"     Verifica que el bot esté recibiendo eventos de balance")
        else:
            self.stdout.write("  ⚠️  No hay snapshots. La gráfica estará vacía.")

        self.stdout.write("")

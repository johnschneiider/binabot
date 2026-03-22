from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

from django.conf import settings
from django.core.management.base import BaseCommand

from gestion_riesgo.estrategia_eurusd import (
    IndicadorEMA35,
    ConstructorVelasM5,
    evaluar_senal_eurusd,
)
from gestion_riesgo.models import Cuenta, TickDerivHistorico
from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS


class Command(BaseCommand):
    help = "Ejecuta el bot EURUSD con estrategia EMA 35 M5"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-ticks",
            type=int,
            default=5000,
            help="Máximo de ticks a procesar (default: 5000)",
        )
        parser.add_argument(
            "--max-segundos",
            type=int,
            default=0,
            help="Máximo de segundos a ejecutar (0 = infinito)",
        )
        parser.add_argument(
            "--symbol",
            type=str,
            default="EURUSD",
            help="Símbolo a tradear (default: EURUSD)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Modo paper trading (no ejecuta operaciones reales)",
        )
        parser.add_argument(
            "--stake",
            type=float,
            default=1.0,
            help="Monto por operación (default: 1.0)",
        )

    def handle(self, *args, **options):
        max_ticks = int(options["max_ticks"])
        max_segundos = int(options["max_segundos"])
        symbol = str(options["symbol"])
        dry_run = bool(options["dry_run"])
        stake = float(options["stake"])

        self.stdout.write(
            self.style.SUCCESS(f"Iniciando bot EURUSD en modo {'PAPER' if dry_run else 'REAL'}")
        )
        self.stdout.write(f"Símbolo: {symbol}")
        self.stdout.write(f"Stake: {stake}")
        self.stdout.write(f"EMA: 35 períodos, M5")
        
        asyncio.run(self._ejecutar(max_ticks, max_segundos, symbol, dry_run, stake))

    async def _ejecutar(
        self,
        max_ticks: int,
        max_segundos: int,
        symbol: str,
        dry_run: bool,
        stake: float,
    ):
        from gestion_riesgo.gestor_riesgo import GestorRiesgo
        
        # Inicializar componentes
        ema35 = IndicadorEMA35(periodo=35)
        constructor_velas = ConstructorVelasM5()
        gestor_riesgo = None
        
        if not dry_run:
            cuenta, _ = Cuenta.objects.get_or_create(
                simbolo=symbol,
                defaults={
                    "capital_inicial": 100.0,
                    "capital_actual": 100.0,
                }
            )
            gestor_riesgo = GestorRiesgo(cuenta)
        
        ticks_procesados = 0
        inicio_epoch = int(time.time())
        ultima_señal = None
        
        # Por ahora, no usamos base de datos para evitar errores async
        cuenta = None
        
        self.stdout.write(f"[{self._hora_actual()}] Conectando a {symbol}...")
        
        async with ClienteDerivWS() as ws:
            self.stdout.write(self.style.SUCCESS(f"[*] Conectado a Deriv WebSocket"))
            
            async for tick in ws.stream_ticks(symbol):
                ticks_procesados += 1
                
                # Procesar tick
                vela_completada = constructor_velas.agregar_tick(tick.precio, tick.epoch)
                
                # Actualizar EMA si hay vela
                if vela_completada:
                    ema35.actualizar(vela_completada["close"], vela_completada["epoch_fin"])
                    
                    # Evaluar señal si EMA lista
                    if ema35.listo:
                        # Construir lista de velas para evaluación
                        # Usar las últimas 50 velas
                        ultima_vela = vela_completada
                        
                        # Obtener últimas 50 velas del constructor (simulado)
                        # En producción, esto vendría de la DB
                        velas_simuladas = self._construir_historial_velas(
                            constructor_velas, ema35
                        )
                        
                        if len(velas_simuladas) >= 40:
                            senal = evaluar_senal_eurusd(
                                velas_simuladas,
                                ema35,
                                pullback_min=1,
                                pullback_max=3,
                            )
                            
                            if senal.decision != "NO_OPERAR":
                                ultima_señal = senal
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"[{self._hora_actual()}] SEÑAL: {senal.decision} - {senal.razon}"
                                    )
                                )
                                
                                # Ejecutar operación si no es dry-run
                                if not dry_run and gestor_riesgo:
                                    await self._ejecutar_operacion(
                                        gestor_riesgo,
                                        senal,
                                        tick.precio,
                                        stake,
                                    )
                            else:
                                self.stdout.write(
                                    f"[{self._hora_actual()}] {senal.razon}"
                                )
                
                # Logging cada 100 ticks
                if ticks_procesados % 100 == 0:
                    tendencia = ema35.obtener_tendencia()
                    tendencia_str = tendencia.direccion if tendencia else "N/A"
                    self.stdout.write(
                        f"[{self._hora_actual()}] Ticks: {ticks_procesados} | "
                        f"Precio: {tick.precio:.5f} | EMA35: {ema35.valor:.5f if ema35.valor else 'N/A'} | "
                        f"Tendencia: {tendencia_str}"
                    )
                
                # Verificar límites
                if max_ticks > 0 and ticks_procesados >= max_ticks:
                    self.stdout.write(self.style.WARNING(f"Límite de ticks alcanzado: {max_ticks}"))
                    break
                
                if max_segundos > 0:
                    elapsed = int(time.time()) - inicio_epoch
                    if elapsed >= max_segundos:
                        self.stdout.write(self.style.WARNING(f"Límite de tiempo alcanzado: {max_segundos}s"))
                        break
        
        self.stdout.write(self.style.SUCCESS(f"Bot detenido. Total ticks: {ticks_procesados}"))
        
        if ultima_señal:
            self.stdout.write(f"Última señal: {ultima_señal.decision} - {ultima_señal.razon}")

    def _hora_actual(self) -> str:
        return datetime.now().strftime("%H:%M:%S")
    
    def _construir_historial_velas(
        self,
        constructor: ConstructorVelasM5,
        ema: IndicadorEMA35,
    ) -> list[dict]:
        """
        Construye historial de velas para evaluación.
        En una implementación real, esto vendría de la base de datos.
        """
        # Por ahora, simulamos las últimas velas basándonos en el constructor
        # Esto es un placeholder - en producción guardamos velas en DB
        vela_actual = constructor.vela_actual
        if vela_actual is None:
            return []
        
        # Generar velas "históricas" basadas en el precio actual y la EMA
        # Esto es una aproximación para que funcione el backtest en tiempo real
        historial = []
        ema_val = ema.valor
        
        if ema_val is None:
            return [vela_actual]
        
        # Crear algunas velas históricas simuladas para tener contexto
        import random
        random.seed(int(time.time() // 60))  # Semilla por minuto
        
        for i in range(35, -1, -1):
            if i == 0:
                historial.append(vela_actual)
            else:
                # Simular vela histórica
                ruido = random.uniform(-0.0005, 0.0005)
                precio_base = ema_val + ruido * (35 - i) / 35
                
                open_p = precio_base + random.uniform(-0.0002, 0.0002)
                close_p = precio_base + random.uniform(-0.0002, 0.0002)
                high_p = max(open_p, close_p) + random.uniform(0, 0.0003)
                low_p = min(open_p, close_p) - random.uniform(0, 0.0003)
                
                historial.append({
                    "epoch_inicio": vela_actual["epoch_inicio"] - i * 300,
                    "epoch_fin": vela_actual["epoch_inicio"] - (i - 1) * 300,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "volume": random.randint(10, 100),
                })
        
        return historial

    async def _ejecutar_operacion(
        self,
        gestor: "GestorRiesgo",
        senal,
        precio_actual: float,
        stake: float,
    ):
        """Ejecuta una operación real o papier."""
        self.stdout.write(
            self.style.SUCCESS(f"==> EJECUTANDO {senal.decision} @ {precio_actual:.5f}")
        )
        
        # TODO: Implementar ejecución real con Deriv API
        # Por ahora, solo registramos la intención
        self.stdout.write(
            self.style.WARNING("Ejecución real no implementada - modo paper")
        )

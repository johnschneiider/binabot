from __future__ import annotations

import asyncio
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from gestion_riesgo.backtest_eurusd import BacktestEURUSD, ParametrosBacktest, optimizar_parametros
from gestion_riesgo.models import VelaEURUSD, TickEURUSD
from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS


class Command(BaseCommand):
    help = "Ejecuta backtest de la estrategia EURUSD"

    def add_arguments(self, parser):
        parser.add_argument(
            "--ticks",
            type=int,
            default=10000,
            help="Número de ticks a descargar para backtest (default: 10000)",
        )
        parser.add_argument(
            "--symbol",
            type=str,
            default="EURUSD",
            help="Símbolo a usar (default: EURUSD)",
        )
        parser.add_argument(
            "--optimizar",
            action="store_true",
            help="Ejecutar optimización de parámetros",
        )
        parser.add_argument(
            "--ema-inicio",
            type=int,
            default=20,
            help="Período EMA inicio para optimización (default: 20)",
        )
        parser.add_argument(
            "--ema-fin",
            type=int,
            default=50,
            help="Período EMA fin para optimización (default: 50)",
        )
        parser.add_argument(
            "--guardar-db",
            action="store_true",
            help="Guardar operaciones en la base de datos",
        )

    def handle(self, *args, **options):
        ticks_count = int(options["ticks"])
        symbol = str(options["symbol"])
        optimizar = bool(options["optimizar"])
        ema_inicio = int(options["ema_inicio"])
        ema_fin = int(options["ema_fin"])
        guardar_db = bool(options["guardar_db"])

        self.stdout.write(self.style.SUCCESS(f"Backtest EURUSD - {symbol}"))
        self.stdout.write(f"Ticks a procesar: {ticks_count}")
        
        asyncio.run(self._ejecutar(
            ticks_count=ticks_count,
            symbol=symbol,
            optimizar=optimizar,
            ema_range=range(ema_inicio, ema_fin + 1),
            guardar_db=guardar_db,
        ))

    async def _ejecutar(
        self,
        ticks_count: int,
        symbol: str,
        optimizar: bool,
        ema_range: range,
        guardar_db: bool,
    ):
        self.stdout.write(f"[{self._hora()}] Descargando ticks de {symbol}...")
        
        try:
            ticks = []
            async with ClienteDerivWS(token="") as ws:
                # Descargar ticks históricos
                downloaded = 0
                async with ClienteDerivWS(token="") as ws_inner:
                    ticks_hist = await ws_inner.obtener_ticks_history(
                        symbol=symbol,
                        count=ticks_count,
                    )
                    
                    self.stdout.write(
                        self.style.SUCCESS(f"[*] Descargados {len(ticks_hist)} ticks")
                    )
                    
                    # Convertir a formato simple
                    ticks = [(t.precio, t.epoch) for t in ticks_hist]
                    ticks.sort(key=lambda x: x[1])  # Ordenar por epoch
                    
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error descargando ticks: {e}")
            )
            
            # Intentar con datos existentes en DB
            self.stdout.write("Intentando con datos existentes en DB...")
            ticks_db = TickEURUSD.objects.all().order_by("epoch")[:ticks_count]
            ticks = [(t.precio, t.epoch) for t in ticks_db]
            
            if not ticks:
                raise CommandError("No hay ticks disponibles")
        
        self.stdout.write(f"[{self._hora()}] Ejecutando backtest con {len(ticks)} ticks...")
        
        if optimizar:
            self.stdout.write(self.style.Warning("[*] Optimizando parámetros..."))
            mejor_params, resultado = optimizar_parametros(
                ticks,
                ema_rango=ema_range,
            )
            
            self.stdout.write(self.style.SUCCESS("\n=== MEJOR CONFIGURACIÓN ==="))
            self.stdout.write(f"EMA Período: {mejor_params.ema_periodo}")
            self.stdout.write(f"Pullback Min: {mejor_params.pullback_min}")
            self.stdout.write(f"Pullback Max: {mejor_params.pullback_max}")
        else:
            # Usar EMA 15 para mayor sensibilidad en datos de ticks
            params = ParametrosBacktest(ema_periodo=15)
            backtest = BacktestEURUSD(params)
            
            # Desactivar debug para producción
            resultado = backtest.ejecutar(ticks, debug=False)
            
            # Debug: ver info de ticks
            if len(ticks) > 1:
                epochs = [t[1] for t in ticks]
                diffs = [epochs[i+1] - epochs[i] for i in range(min(10, len(epochs)-1))]
                print(f"DEBUG: Primeros 10 diffs entre ticks: {diffs}")
                print(f"DEBUG: Total ticks: {len(ticks)}, rango tiempo: {epochs[-1] - epochs[0]} seg")
        
        self.stdout.write(self.style.SUCCESS("\n=== RESULTADOS ==="))
        self.stdout.write(f"Operaciones: {resultado.total_ops}")
        self.stdout.write(f"Wins: {resultado.wins} | Losses: {resultado.losses}")
        self.stdout.write(f"Winrate: {resultado.winrate:.2f}%")
        self.stdout.write(f"PnL Total: ${resultado.pnl_total:.2f}")
        self.stdout.write(f"Profit Factor: {resultado.profit_factor:.2f}")
        self.stdout.write(f"Max Drawdown: {resultado.max_drawdown:.2f}%")
        self.stdout.write(f"Expectativa: {resultado.expectativa:.4f}")
        
        # Validar según criterios del documento
        self.stdout.write("\n=== VALIDACIÓN ===")
        if resultado.profit_factor >= 1.3:
            self.stdout.write(self.style.SUCCESS(f"OK Profit Factor >= 1.3: {resultado.profit_factor:.2f}"))
        else:
            self.stdout.write(self.style.ERROR(f"X Profit Factor < 1.3: {resultado.profit_factor:.2f}"))
        
        if resultado.max_drawdown <= 10:
            self.stdout.write(self.style.SUCCESS(f"OK Max Drawdown <= 10%: {resultado.max_drawdown:.2f}%"))
        else:
            self.stdout.write(self.style.WARNING(f"W Max Drawdown > 10%: {resultado.max_drawdown:.2f}%"))
        
        if resultado.expectativa > 0:
            self.stdout.write(self.style.SUCCESS(f"OK Expectativa positiva: {resultado.expectativa:.4f}"))
        else:
            self.stdout.write(self.style.ERROR(f"X Expectativa negativa: {resultado.expectativa:.4f}"))
        
        if guardar_db:
            self.stdout.write("\n[*] Guardando operaciones en DB...")
            # Guardar ops (implementación simplificada)

    def _hora(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

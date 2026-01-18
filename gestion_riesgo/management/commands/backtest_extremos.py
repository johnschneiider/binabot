from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand

from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS, TickDeriv
from vector_pesos.senal_extremos import evaluar_senal_extremos
from vector_variables.constructor_vector_extremos import ConstructorVectorExtremos, Tick as TickExtremos


@dataclass
class TradeSim:
    decision: str  # "VENTA" | "COMPRA"
    entry_i: int
    entry_epoch: int
    entry_price: float
    exit_i: int
    exit_epoch: int
    exit_price: float
    win: bool
    pnl_stake_units: float


def _hora_local(epoch: int) -> int:
    tz = getattr(settings, "TIME_ZONE", "UTC") or "UTC"
    return datetime.fromtimestamp(int(epoch), tz=ZoneInfo(tz)).hour


def _win_for_direction(*, decision: str, entry: float, exit: float) -> bool:
    # Para Rise/Fall:
    # - PUT (VENTA): gana si el precio baja
    # - CALL (COMPRA): gana si el precio sube
    if decision == "VENTA":
        return float(exit) < float(entry)
    if decision == "COMPRA":
        return float(exit) > float(entry)
    return False


def _pnl_units(*, win: bool) -> float:
    """
    PnL en unidades de stake=1 (como el calibrador):
    - win => +payout_win - costo
    - loss => -1 - costo
    """
    payout_win = float(getattr(settings, "CALIBRADOR_PAYOUT_WIN", 0.95))
    costo = float(getattr(settings, "CALIBRADOR_COSTO_POR_TRADE", 0.0))
    return (float(payout_win) if win else -1.0) - float(costo)


def _resumen(trades: list[TradeSim]) -> dict[str, Any]:
    n = len(trades)
    if n <= 0:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "winrate": None,
            "avg_pnl": None,
            "sum_pnl": 0.0,
            "ev_per_trade": None,
        }
    wins = sum(1 for t in trades if t.win)
    losses = n - wins
    sum_pnl = float(sum(float(t.pnl_stake_units) for t in trades))
    avg_pnl = sum_pnl / float(n)
    winrate = (wins / float(n)) * 100.0
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "avg_pnl": avg_pnl,
        "sum_pnl": sum_pnl,
        "ev_per_trade": avg_pnl,
    }


def _simular(ticks: list[TickDeriv]) -> tuple[list[TradeSim], dict[str, Any]]:
    ventana = int(getattr(settings, "EXTREMOS_VENTANA_TICKS", 100) or 100)
    if ventana < 10:
        ventana = 10
    dur = int(getattr(settings, "DERIV_DURACION_TICKS", 5) or 5)
    cooldown = int(getattr(settings, "ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS", 25) or 25)
    umbral_rango_minimo = float(
        getattr(settings, "EXTREMOS_UMBRAL_RANGO_MINIMO", getattr(settings, "ESTRATEGIA_EXTREMOS_UMBRAL_RANGO", 0.5))
    )

    contract_types_permitidos = {str(x).strip().upper() for x in getattr(settings, "DERIV_CONTRACT_TYPES_PERMITIDOS", []) if str(x).strip()}
    if not contract_types_permitidos:
        contract_types_permitidos = {"PUT", "CALL"}
    permitir_put = "PUT" in contract_types_permitidos
    permitir_call = "CALL" in contract_types_permitidos

    constructor = ConstructorVectorExtremos(ventana_ticks=ventana)

    trades: list[TradeSim] = []

    # Estado de trade abierto
    abierto: dict[str, Any] | None = None

    for i, t in enumerate(ticks):
        tick_n = i + 1
        vector = constructor.actualizar_con_tick(TickExtremos(precio=float(t.precio), epoch=int(t.epoch)))
        estado = constructor.obtener_estado()

        # Si hay trade abierto, cerrar cuando se cumpla la duración.
        if abierto is not None:
            if tick_n >= int(abierto["tick_entrada"]) + dur:
                decision = str(abierto["decision"])
                entry_price = float(abierto["entry_price"])
                entry_epoch = int(abierto["entry_epoch"])
                exit_price = float(t.precio)
                exit_epoch = int(t.epoch)
                win = _win_for_direction(decision=decision, entry=entry_price, exit=exit_price)
                pnl = _pnl_units(win=win)
                trades.append(
                    TradeSim(
                        decision=decision,
                        entry_i=int(abierto["entry_i"]),
                        entry_epoch=entry_epoch,
                        entry_price=entry_price,
                        exit_i=int(i),
                        exit_epoch=exit_epoch,
                        exit_price=exit_price,
                        win=bool(win),
                        pnl_stake_units=float(pnl),
                    )
                )
                constructor.actualizar_estado("COOLDOWN", ticks_cooldown_restantes=int(cooldown))
                abierto = None
                estado = constructor.obtener_estado()

        # Decrementar cooldown (igual que el bot)
        if estado.estado == "COOLDOWN":
            constructor.decrementar_cooldown()
            estado = constructor.obtener_estado()

        # Mientras está abierta una operación, no buscamos entradas (igual que el bot).
        if abierto is not None:
            continue

        # Evaluar señal
        res = evaluar_senal_extremos(
            vector_extremos=vector,
            estado_actual=estado.estado,
            tick_actual=tick_n,
            tick_entrada=estado.tick_entrada,
            ref_extremo_tick=estado.ref_extremo_tick,
            ref_extremo_precio=estado.ref_extremo_precio,
            umbral_rango_minimo=float(umbral_rango_minimo),
            permitir_put=bool(permitir_put),
            permitir_call=bool(permitir_call),
        )

        if res.decision in {"VENTA", "COMPRA"}:
            # Abrir trade simulado
            constructor.actualizar_estado(
                "EN_OPERACION",
                ultimo_extremo_operado="MAX" if res.decision == "VENTA" else "MIN",
                precio_entrada=float(t.precio),
                tick_entrada=int(tick_n),
                tipo_operacion=str(res.decision),
            )
            abierto = {
                "decision": str(res.decision),
                "entry_i": int(i),
                "entry_epoch": int(t.epoch),
                "entry_price": float(t.precio),
                "tick_entrada": int(tick_n),
            }
            continue

    resumen = _resumen(trades)
    return trades, resumen


class Command(BaseCommand):
    help = "Backtest de la estrategia de 'extremos' usando ticks históricos de Deriv (ticks_history)."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--symbol", type=str, default=None, help="Símbolo (ej: R_100).")
        parser.add_argument("--hours", type=int, default=6, help="Horas hacia atrás (aprox; asume ~1 tick/seg).")
        parser.add_argument("--count", type=int, default=None, help="Cantidad de ticks a descargar (override).")
        parser.add_argument(
            "--sin-token",
            action="store_true",
            help="Forzar conexión sin token (recomendado para ticks_history; evita authorize).",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN001
        symbol = (options.get("symbol") or getattr(settings, "DERIV_SYMBOL", "R_100")).strip()
        hours = int(options.get("hours") or 0)
        count_opt = options.get("count")
        sin_token = bool(options.get("sin-token"))

        if count_opt is None:
            # Aproximación conservadora: 1 tick/segundo.
            count = max(500, int(max(1, hours) * 3600))
        else:
            count = max(1, int(count_opt))

        self.stdout.write(
            f"[BACKTEST] symbol={symbol} count={count} "
            f"ventana={int(getattr(settings,'EXTREMOS_VENTANA_TICKS',100) or 100)} "
            f"dur={int(getattr(settings,'DERIV_DURACION_TICKS',5) or 5)} "
            f"cooldown={int(getattr(settings,'ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS',25) or 25)} "
            f"ct_permitidos={getattr(settings,'DERIV_CONTRACT_TYPES_PERMITIDOS', [])}"
        )

        token = "" if sin_token else None

        async def _run() -> list[TickDeriv]:
            async with ClienteDerivWS(token=token) as c:
                return await c.obtener_ticks_history(symbol=symbol, count=count)

        ticks = asyncio.run(_run())
        if not ticks:
            self.stdout.write("[BACKTEST] No se obtuvieron ticks (¿rate limit / símbolo inválido?).")
            return

        trades, resumen = _simular(ticks)

        first_epoch = int(ticks[0].epoch)
        last_epoch = int(ticks[-1].epoch)
        self.stdout.write(
            f"[BACKTEST] ticks={len(ticks)} "
            f"desde={datetime.fromtimestamp(first_epoch).isoformat()} "
            f"hasta={datetime.fromtimestamp(last_epoch).isoformat()}"
        )

        winrate_str = "-" if resumen["winrate"] is None else f"{float(resumen['winrate']):.2f}%"
        ev_str = "-" if resumen["ev_per_trade"] is None else f"{float(resumen['ev_per_trade']):+.4f}"

        self.stdout.write(
            f"[RESULT] trades={resumen['n']} wins={resumen['wins']} losses={resumen['losses']} "
            f"winrate={winrate_str} "
            f"ev/trade={ev_str} "
            f"sum_pnl={resumen['sum_pnl']:+.4f} (stake=1 units)"
        )

        # Breakdown por hora local (útil para validar bloqueo horario vs performance real).
        por_hora: dict[int, list[TradeSim]] = {h: [] for h in range(24)}
        for tr in trades:
            h = _hora_local(int(tr.entry_epoch))
            por_hora[int(h)].append(tr)

        self.stdout.write("[HORA_LOCAL] trades winrate ev/trade sum_pnl")
        for h in range(24):
            r = _resumen(por_hora[h])
            if r["n"] <= 0:
                continue
            self.stdout.write(
                f"  {h:02d}:00  n={r['n']:<4d} "
                f"wr={r['winrate']:.1f}% "
                f"ev={r['ev_per_trade']:+.4f} "
                f"sum={r['sum_pnl']:+.4f}"
            )


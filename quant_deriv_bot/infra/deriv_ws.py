from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import websockets
from django.conf import settings


@dataclass(frozen=True)
class TickDeriv:
    """
    TICK NORMALIZADO DESDE DERIV.
    """

    symbol: str
    precio: float
    epoch: int


@dataclass(frozen=True)
class BalanceDeriv:
    """
    BALANCE REAL DESDE DERIV (MENSAJE `balance`).
    """

    balance: float
    currency: str


def _ws_url() -> str:
    """
    CONSTRUYE LA URL DE WEBSOCKET DE DERIV USANDO APP_ID.
    """
    app_id = getattr(settings, "DERIV_APP_ID", "1089")
    return f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"


class ClienteDerivWS:
    """
    CLIENTE WEBSOCKET MINIMALISTA PARA DERIV.

    RESTRICCIÓN:
    - UNA SOLA CONEXIÓN, UN SOLO PROCESO, UN SOLO LOOP.
    """

    def __init__(self, token: Optional[str] = None) -> None:
        # Importante:
        # - token=None => usar settings.DERIV_API_TOKEN (modo "normal" del bot)
        # - token=""   => forzar "sin token" (útil para research/calibración; evita authorize y fugas de credenciales)
        if token is None:
            self.token = getattr(settings, "DERIV_API_TOKEN", "") or ""
        else:
            self.token = token
        self._ws: Any | None = None

    async def __aenter__(self) -> "ClienteDerivWS":
        # TIMEOUTS PARA EVITAR BLOQUEOS SILENCIOSOS.
        self._ws = await websockets.connect(
            _ws_url(),
            ping_interval=20,
            ping_timeout=20,
            open_timeout=20,
            close_timeout=10,
        )
        if self.token:
            await self.enviar({"authorize": self.token})
            msg = await self.recibir(timeout_segundos=20)
            if msg.get("error"):
                raise RuntimeError(f"Fallo authorize: {msg['error']}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self._ws is not None:
            await self._ws.close()

    async def enviar(self, payload: dict[str, Any]) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(payload))

    async def recibir(self, timeout_segundos: float | None = None) -> dict[str, Any]:
        assert self._ws is not None
        if timeout_segundos is None:
            raw = await self._ws.recv()
        else:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=float(timeout_segundos))
        return json.loads(raw)

    async def stream_ticks(self, symbol: str) -> AsyncIterator[TickDeriv]:
        """
        PRODUCE UN STREAM ASÍNCRONO DE TICKS PARA UN SÍMBOLO.
        """
        await self.enviar({"ticks": symbol, "subscribe": 1})

        while True:
            msg = await self.recibir(timeout_segundos=60)
            if msg.get("error"):
                raise RuntimeError(msg["error"])

            tick = msg.get("tick")
            if not tick:
                # MENSAJES NO-TICK (p. ej. RESPUESTAS A AUTH) SE IGNORAN.
                continue

            yield TickDeriv(
                symbol=str(tick.get("symbol", symbol)),
                precio=float(tick["quote"]),
                epoch=int(tick["epoch"]),
            )

    async def obtener_ticks_history(self, *, symbol: str, count: int = 5000) -> list[TickDeriv]:
        """
        DESCARGA TICKS HISTÓRICOS USANDO `ticks_history` (DERIV WS).

        POR QUÉ:
        - SIRVE PARA INVESTIGACIÓN/CALIBRACIÓN (WALK-FORWARD) SIN DEPENDER DE ARCHIVOS EXTERNOS.
        - NO REQUIERE TOKEN PARA MERCADOS DISPONIBLES PÚBLICAMENTE (AUNQUE DEPENDE DEL SÍMBOLO).

        IMPORTANTE (DERIV):
        - En la práctica, Deriv suele limitar `count` a ~5000 por request. Para counts mayores,
          hacemos paginación hacia atrás usando `end=<epoch>` y concatenamos sin duplicados.
        """
        objetivo = max(0, int(count))
        if objetivo <= 0:
            return []

        # Límite práctico por request en Deriv WS (aun si pides más).
        chunk_max = 5000
        out: list[TickDeriv] = []
        vistos_epoch: set[int] = set()

        end: int | str = "latest"
        # Safety: evita loops infinitos si el backend no entrega más datos.
        max_paginas = (objetivo // chunk_max) + 3

        for _ in range(max_paginas):
            restante = objetivo - len(out)
            if restante <= 0:
                break

            pedir = min(chunk_max, restante)

            payload = {
                "ticks_history": str(symbol),
                "adjust_start_time": 1,
                "count": int(pedir),
                "end": end,
                "style": "ticks",
            }

            # Deriv a veces responde "WrongResponse" de forma intermitente. Reintentamos con backoff.
            ultimo_error: dict[str, Any] | None = None
            msg: dict[str, Any] | None = None
            for intento in range(1, 6):
                await self.enviar(payload)
                msg = await self.recibir(timeout_segundos=30)
                if not msg.get("error"):
                    ultimo_error = None
                    break
                ultimo_error = msg.get("error")
                code = str((ultimo_error or {}).get("code") or "")
                if code not in {"WrongResponse", "RateLimit"}:
                    raise RuntimeError(ultimo_error)
                # backoff suave: 0.4,0.8,1.6,3.2,6.4
                await asyncio.sleep(0.4 * (2 ** (intento - 1)))

            if ultimo_error is not None:
                raise RuntimeError(ultimo_error)
            assert msg is not None

            hist = msg.get("history") or {}
            precios = hist.get("prices") or []
            tiempos = hist.get("times") or []
            if not precios or not tiempos:
                break

            # Deriv entrega arrays en orden cronológico (normalmente viejo->nuevo).
            # Hacemos de-dup por epoch.
            batch: list[TickDeriv] = []
            for p, t in zip(precios, tiempos):
                try:
                    epoch = int(t)
                    if epoch in vistos_epoch:
                        continue
                    vistos_epoch.add(epoch)
                    batch.append(TickDeriv(symbol=str(symbol), precio=float(p), epoch=epoch))
                except Exception:
                    continue

            if not batch:
                break

            out.extend(batch)

            # Preparar la siguiente página hacia atrás: pedir “antes del tick más viejo”.
            oldest_epoch = min(td.epoch for td in batch)
            end = max(0, int(oldest_epoch) - 1)

            # Pequeño respiro para evitar rate limiting/keepalive issues.
            await asyncio.sleep(0.15)

        # Queremos devolver los más recientes `objetivo` ticks en orden cronológico.
        out.sort(key=lambda td: int(td.epoch))
        if len(out) > objetivo:
            out = out[-objetivo:]
        return out


    async def stream_eventos(self, symbol: str, incluir_balance: bool) -> AsyncIterator[dict[str, Any]]:
        """
        PRODUCE EVENTOS MULTIPLEXADOS (TICK + BALANCE) EN UNA MISMA CONEXIÓN.

        POR QUÉ:
        - DERIV ENVÍA DIFERENTES TIPOS DE MENSAJE POR EL MISMO WS.
        - SE NECESITA UNA SOLA `recv()` CENTRAL PARA NO CORROMPER EL PROTOCOLO.
        """
        await self.enviar({"ticks": symbol, "subscribe": 1})
        if incluir_balance:
            if not self.token:
                raise RuntimeError("Se solicitó balance pero no hay DERIV_API_TOKEN (authorize requerido).")
            await self.enviar({"balance": 1, "subscribe": 1})

        while True:
            msg = await self.recibir(timeout_segundos=60)
            if msg.get("error"):
                raise RuntimeError(msg["error"])

            if msg.get("tick"):
                t = msg["tick"]
                # Validar que el tick tenga los campos necesarios antes de crear TickDeriv
                if not t or "quote" not in t or "epoch" not in t:
                    continue
                try:
                    yield {
                        "tipo": "tick",
                        "tick": TickDeriv(
                            symbol=str(t.get("symbol", symbol)),
                            precio=float(t["quote"]),
                            epoch=int(t["epoch"]),
                        ),
                    }
                except (ValueError, KeyError, TypeError):
                    # Si falta algún campo o hay error de conversión, ignorar este tick
                    continue
                continue

            if msg.get("balance"):
                b = msg["balance"]
                yield {
                    "tipo": "balance",
                    "balance": BalanceDeriv(
                        balance=float(b.get("balance", 0.0)),
                        currency=str(b.get("currency", "")),
                    ),
                }
                continue

            # RESPUESTAS/STREAMS ÚTILES PARA TRADING REAL.
            if msg.get("proposal"):
                yield {"tipo": "proposal", "raw": msg}
                continue
            if msg.get("buy"):
                yield {"tipo": "buy", "raw": msg}
                continue
            if msg.get("proposal_open_contract"):
                yield {"tipo": "proposal_open_contract", "raw": msg}
                continue
            if msg.get("profit_table"):
                yield {"tipo": "profit_table", "raw": msg}
                continue
            if msg.get("statement"):
                yield {"tipo": "statement", "raw": msg}
                continue

            # OTROS MENSAJES (p.ej. authorize, ping, etc.) SE IGNORAN.


async def dormir_segundos(segundos: float) -> None:
    """
    SLEEP AISLADO PARA FACILITAR TESTING/MOCK FUTURO.
    """
    await asyncio.sleep(segundos)



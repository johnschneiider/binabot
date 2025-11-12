import asyncio
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from django.db.utils import OperationalError

from historial.models import Tick

from .client import DerivWebsocketClient


@dataclass
class ResultadoTicker:
    total_ticks: int
    ticks_por_activo: Dict[str, int]



def _registrar_tick_threadsafe(tick: dict) -> Tick:
    close_old_connections()
    return Tick.registrar_desde_payload(tick)


class TickStreamRecorder:
    def __init__(
        self,
        activos: Iterable[str],
        duracion: Optional[int] = None,
        max_ticks: Optional[int] = None,
    ):
        self.activos: List[str] = list(dict.fromkeys(activos))
        self.duracion = duracion
        self.max_ticks = max_ticks
        self._client = DerivWebsocketClient()
        self._contador_total = 0
        self._contadores_por_activo: Dict[str, int] = {activo: 0 for activo in self.activos}

    async def _guardar_tick(self, tick: dict) -> None:
        intentos = 0
        while True:
            try:
                instancia = await sync_to_async(
                    _registrar_tick_threadsafe, thread_sensitive=True
                )(tick)
                print(
                    f"[{instancia.epoch:%Y-%m-%d %H:%M:%S}] "
                    f"Activo {instancia.activo} | Precio {instancia.precio}"
                )
                break
            except OperationalError as exc:  # pragma: no cover - interacción con SQLite
                if "database is locked" in str(exc).lower() and intentos < 5:
                    intentos += 1
                    await asyncio.sleep(0.2 * intentos)
                    continue
                raise

    async def ejecutar(self) -> ResultadoTicker:
        if not self.activos:
            raise ValueError("Se requiere al menos un activo para recolectar ticks.")

        for activo in self.activos:
            await self._client.suscribir_ticks(activo)

        inicio = asyncio.get_event_loop().time()

        try:
            while True:
                mensaje = await self._client._receive()
                if mensaje.get("msg_type") == "tick":
                    tick = mensaje.get("tick", {})
                    simbolo = tick.get("symbol")
                    if simbolo in self._contadores_por_activo:
                        await self._guardar_tick(tick)
                        self._contadores_por_activo[simbolo] += 1
                        self._contador_total += 1

                if self.max_ticks and self._contador_total >= self.max_ticks:
                    break

                if self.duracion:
                    transcurrido = asyncio.get_event_loop().time() - inicio
                    if transcurrido >= self.duracion:
                        break
        finally:
            try:
                await self._client.olvidar_todos("ticks")
            except Exception:
                pass
            await self._client.cerrar()

        return ResultadoTicker(
            total_ticks=self._contador_total,
            ticks_por_activo=self._contadores_por_activo,
        )


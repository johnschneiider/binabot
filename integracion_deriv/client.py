import asyncio
import json
from typing import Any, Dict, Optional

import websockets
from django.conf import settings


class DerivWebsocketClient:
    """
    Cliente WebSocket básico para interactuar con la API de Deriv.
    Gestiona reconexión automática y autorización.
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        app_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> None:
        self.api_token = api_token or settings.DERIV_API_TOKEN
        self.app_id = app_id or settings.DERIV_APP_ID
        self.account_id = account_id or settings.DERIV_ACCOUNT_ID
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._url = f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}"
        self._lock = asyncio.Lock()

    async def _ensure_connection(self) -> None:
        if self._ws and not self._ws.closed:
            return
        async with self._lock:
            if self._ws and not self._ws.closed:
                return
            self._ws = await websockets.connect(self._url)
            await self._authorize()

    async def _authorize(self) -> None:
        if not self.api_token:
            raise ValueError("No se ha configurado el token de la API de Deriv.")
        payload = {"authorize": self.api_token}
        await self._send(payload)
        await self._receive()  # respuesta de autorización

    async def _send(self, payload: Dict[str, Any]) -> None:
        await self._ensure_connection()
        assert self._ws is not None
        await self._ws.send(json.dumps(payload))

    async def _receive(self) -> Dict[str, Any]:
        assert self._ws is not None
        respuesta = await self._ws.recv()
        return json.loads(respuesta)

    async def ping(self) -> Dict[str, Any]:
        await self._send({"ping": 1})
        return await self._receive()

    async def suscribir_ticks(self, symbol: str) -> None:
        await self._send({"ticks": symbol, "subscribe": 1})

    async def olvidar_todos(self, tipo: str = "ticks") -> Dict[str, Any]:
        await self._send({"forget_all": tipo})
        return await self._receive()

    async def cerrar(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def comprar_contrato(
        self,
        symbol: str,
        amount: float,
        duration: int,
        duration_unit: str,
        contract_type: str,
        barrier: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "buy": 1,
            "price": round(amount, 2),
            "parameters": {
                "amount": round(amount, 2),
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": duration,
                "duration_unit": duration_unit,
                "symbol": symbol,
            },
        }
        if barrier:
            payload["parameters"]["barrier"] = barrier

        await self._send(payload)
        return await self._receive()

    async def obtener_detalle_contrato(self, contract_id: str) -> Dict[str, Any]:
        await self._send({"proposal_open_contract": 1, "contract_id": contract_id})
        return await self._receive()

    async def esperar_resultado(self, contract_id: str, timeout: int = 120) -> Dict[str, Any]:
        """
        Espera hasta que el contrato tenga resultado (win/loss).
        """
        tiempo_limite = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < tiempo_limite:
            detalle = await self.obtener_detalle_contrato(contract_id)
            open_contract = detalle.get("proposal_open_contract", {})
            status = open_contract.get("status")
            if status in {"won", "lost"}:
                return detalle
            await asyncio.sleep(5)
        raise TimeoutError("No se recibió resultado del contrato en el tiempo esperado.")

    async def obtener_ticks_history(self, symbol: str, count: int = 10) -> Dict[str, Any]:
        payload = {
            "ticks_history": symbol,
            "end": "latest",
            "count": count,
            "style": "ticks",
        }
        await self._send(payload)
        return await self._receive()

    async def obtener_balance(self) -> Dict[str, Any]:
        await self._send({"balance": 1})
        return await self._receive()

    async def obtener_simbolos_activos(
        self, producto_tipo: Optional[str] = None, formato: str = "full"
    ) -> Dict[str, Any]:
        """
        Obtiene todos los símbolos activos disponibles en Deriv.
        
        Args:
            producto_tipo: Tipo de producto ('basic', 'multi_barrier', etc.)
                          Si es None, devuelve todos los tipos.
            formato: Formato de respuesta ('brief' o 'full'). 'full' incluye más detalles.
        """
        # La API de Deriv requiere: {"active_symbols": "brief"} o {"active_symbols": "full"}
        payload = {"active_symbols": formato}
        if producto_tipo:
            payload["product_type"] = producto_tipo
        await self._send(payload)
        return await self._receive()


def operar_contrato_sync(**kwargs) -> Dict[str, Any]:
    """
    Helper sincrónico para ejecutar la compra y esperar resultado
    desde un contexto síncrono (por ejemplo, dentro de una tarea Celery).
    """

    async def _run():
        client = DerivWebsocketClient()
        try:
            compra = await client.comprar_contrato(**kwargs)
            contract_id = compra.get("buy", {}).get("contract_id")
            if not contract_id:
                return compra
            return await client.esperar_resultado(str(contract_id))
        finally:
            await client.cerrar()

    return asyncio.run(_run())


def obtener_ticks_history_sync(symbol: str, count: int = 10) -> Dict[str, Any]:
    async def _run():
        client = DerivWebsocketClient()
        try:
            respuesta = await client.obtener_ticks_history(symbol, count=count)
            return respuesta
        finally:
            await client.cerrar()

    return asyncio.run(_run())


def obtener_balance_sync() -> Dict[str, Any]:
    async def _run():
        client = DerivWebsocketClient()
        try:
            respuesta = await client.obtener_balance()
            return respuesta
        finally:
            await client.cerrar()

    return asyncio.run(_run())


def obtener_simbolos_activos_sync(
    producto_tipo: Optional[str] = None, formato: str = "full"
) -> Dict[str, Any]:
    """
    Helper sincrónico para obtener símbolos activos desde un contexto síncrono.
    """
    async def _run():
        client = DerivWebsocketClient()
        try:
            respuesta = await client.obtener_simbolos_activos(
                producto_tipo=producto_tipo, formato=formato
            )
            return respuesta
        finally:
            await client.cerrar()

    return asyncio.run(_run())


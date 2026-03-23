#!/usr/bin/env python
"""Prueba rápida de conexión WebSocket a Deriv."""
import asyncio
import json
import websockets
import traceback

async def main():
    app_id = "1089"
    url = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
    
    print(f"Conectando a {url}...")
    
    try:
        async with websockets.connect(url, open_timeout=20) as ws:
            print("Conectado. Suscribiendo a ticks R_100...")
            
            await ws.send(json.dumps({"ticks": "R_100", "subscribe": 1}))
            
            print("Esperando ticks (timeout 30s)...")
            for i in range(10):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(msg)
                    print(f"Mensaje #{i+1}: {data}")
                    
                    if data.get("tick"):
                        print(f"*** TICK RECIBIDO: {data['tick']}")
                        return
                except asyncio.TimeoutError:
                    print("Timeout esperando ticks")
                    return
                    
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
"""Test WebSocket Deriv - copia este archivo a otra PC y ejecútalo."""
import asyncio
import json
import sys

async def test():
    import websockets
    
    url = "wss://api.derivws.com/trading/v1/options/ws/public"
    print(f"Conectando a {url}...")
    
    try:
        ws = await asyncio.wait_for(websockets.connect(url, open_timeout=15), timeout=20)
        print("CONECTADO!")
        
        # Ping de prueba
        await ws.send(json.dumps({"ping": 1}))
        print("Enviado ping")
        
        msg = await asyncio.wait_for(ws.recv(), timeout=30)
        print(f"Recibido: {msg}")
        
        # Suscribirse a ticks
        await ws.send(json.dumps({"ticks": "1HZ100V", "subscribe": 1}))
        print("Suscrito a ticks")
        
        # Esperar ticks
        for i in range(3):
            msg = await asyncio.wait_for(ws.recv(), timeout=30)
            print(f"Tick {i+1}: {msg}")
        
        await ws.close()
        print("OK - Conexion exitosa")
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test())
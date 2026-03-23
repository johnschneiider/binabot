#!/usr/bin/env python
"""Test conexión WebSocket a Deriv."""
import asyncio
import json
import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from django.conf import settings

async def test_ws():
    import websockets
    
    app_id = getattr(settings, 'DERIV_APP_ID', '1089')
    token = getattr(settings, 'DERIV_API_TOKEN', '') or ''
    
    url = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
    print(f"URL: {url}")
    print(f"Token presente: {bool(token)}")
    
    try:
        ws = await asyncio.wait_for(
            websockets.connect(url, open_timeout=15),
            timeout=20
        )
        print("✓ Conectado al WebSocket")
        
        if token:
            await ws.send(json.dumps({"authorize": token}))
            resp = await asyncio.wait_for(ws.recv(), timeout=15)
            print(f"Authorize response: {resp}")
            if resp.get('error'):
                print(f"✗ Error en authorize: {resp['error']}")
                return
        
        # Suscribirse a ticks
        await ws.send(json.dumps({"ticks": "R_100", "subscribe": 1}))
        print("✓ Suscrito a ticks R_100")
        
        # Esperar ticks
        for i in range(5):
            msg = await asyncio.wait_for(ws.recv(), timeout=30)
            print(f"Mensaje {i+1}: {msg.keys()}")
            if msg.get('tick'):
                tick = msg['tick']
                print(f"*** TICK: {tick.get('quote')} @ {tick.get('epoch')}")
                break
        else:
            print("✗ No se recibieron ticks")
        
        await ws.close()
        
    except Exception as e:
        print(f"✗ Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ws())
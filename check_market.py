import os, django, json, time, statistics
from datetime import datetime, timezone
import websockets, asyncio

def ema_calc(precio, prev, periodo):
    if prev is None: return precio
    a = 2.0 / (periodo + 1.0)
    return a * precio + (1.0 - a) * prev

def adx(precios, n=14):
    if len(precios) < n + 2: return 0.0
    dm_up, dm_dn, tr_list = [], [], []
    for i in range(-n, 0):
        h = max(precios[i], precios[i-1])
        l = min(precios[i], precios[i-1])
        pc = precios[i-1]
        up = h - precios[i-1]; dn = precios[i-1] - l
        dm_up.append(up if up > dn and up > 0 else 0)
        dm_dn.append(dn if dn > up and dn > 0 else 0)
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(tr_list) / n or 1
    dip = sum(dm_up) / n / atr * 100
    dim = sum(dm_dn) / n / atr * 100
    if dip + dim == 0: return 0.0
    return abs(dip - dim) / (dip + dim) * 100

async def check():
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    streams = "/".join(f"{s.lower()}usdt@trade" for s in simbolos)
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"
    precios = {s: [] for s in simbolos}
    
    async with websockets.connect(url) as ws:
        print("Esperando 100 ticks para cada activo...")
        count = 0
        while any(len(v) < 100 for v in precios.values()):
            msg = await ws.recv()
            data = json.loads(msg)["data"]
            sym = data["s"].replace("USDT", "")
            precios[sym].append(float(data["p"]))
            count += 1
            if count % 100 == 0:
                print(f"Ticks procesados: {count}")
                
        print("\n── ESTADO ACTUAL MERCADO ──")
        for s in simbolos:
            p = precios[s]
            adx_val = adx(p)
            e5, e21, e55 = None, None, None
            for pr in p:
                e5 = ema_calc(pr, e5, 5)
                e21 = ema_calc(pr, e21, 21)
                e55 = ema_calc(pr, e55, 55)
            gap = abs(e5 - e55) / e55 * 100
            print(f"  {s}: Precio:{p[-1]:.4f} | ADX:{adx_val:.1f} | Gap:{gap:.3f}%")

if __name__ == "__main__":
    asyncio.run(check())

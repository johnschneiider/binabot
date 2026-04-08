"""
DESCARGA DE DATOS HISTÓRICOS — Binance Klines
Descarga OHLCV + num_trades + taker_buy para ETH, BTC, SOL.
Usa paginación startTime para superar el límite de 1000 velas por request.
"""

import json
import time
import os
import urllib.request
from datetime import datetime, timezone

BASE_URL  = "https://api.binance.com/api/v3/klines"
DATA_DIR  = os.path.join(os.path.dirname(__file__), "..", "data")
COLS      = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]

SIMBOLOS  = ["ETHUSDT", "BTCUSDT", "SOLUSDT"]
INTERVALOS = ["1m", "5m", "15m"]
DIAS      = 180


def descargar_historico(simbolo: str, intervalo: str, dias: int, output_csv: str):
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - dias * 86_400_000
    current  = start_ms
    all_rows = []

    print(f"  [{simbolo} {intervalo}] descargando {dias} días desde "
          f"{datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')}...")

    while current < end_ms:
        url = (f"{BASE_URL}?symbol={simbolo}&interval={intervalo}"
               f"&startTime={current}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            if not data:
                break
            all_rows.extend(data)
            current = data[-1][0] + 1
            time.sleep(0.12)          # respeta rate-limit Binance
        except Exception as exc:
            print(f"    Error: {exc} — reintentando en 10s")
            time.sleep(10)

    # escribir CSV
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    with open(output_csv, "w", encoding="utf-8") as f:
        f.write(",".join(COLS) + "\n")
        for row in all_rows:
            f.write(",".join(str(x) for x in row) + "\n")

    print(f"    -> {len(all_rows):,} velas  =>  {output_csv}")
    return len(all_rows)


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    total = 0
    for sym in SIMBOLOS:
        for iv in INTERVALOS:
            out = os.path.join(DATA_DIR, f"{sym}_{iv}.csv")
            n   = descargar_historico(sym, iv, DIAS, out)
            total += n
    print(f"\nTotal descargado: {total:,} filas")

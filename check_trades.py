#!/usr/bin/env python
import os
import sys
import django
import time

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
sys.path.insert(0, r'E:\Binary-bot')
django.setup()

from gestion_riesgo.models import OperacionDeriv

print("=== Checking Open Trades ===")
open_trades = OperacionDeriv.objects.filter(estado='ABIERTA')
print(f"Count: {open_trades.count()}")

for trade in open_trades:
    print(f"\nTrade ID: {trade.id}")
    print(f"Type: {trade.contract_type}")
    print(f"Buy Price: ${trade.buy_price:.2f}")
    print(f"Profit: {trade.profit}")
    print(f"Opened: {trade.opened_epoch}")
    print(f"Closed: {trade.closed_epoch}")
    
    if trade.opened_epoch:
        now = int(time.time())
        elapsed = now - trade.opened_epoch
        print(f"Elapsed: {elapsed}s")
        
        if elapsed > 300:  # 5 minutes
            print("STALE TRADE - Should be closed")
            trade.estado = 'CERRADA'
            trade.closed_epoch = trade.opened_epoch + 60
            if trade.profit is None:
                trade.profit = -1.0
            trade.save()
            print("Fixed!")

print("\n=== Recent Closed Trades ===")
closed_trades = OperacionDeriv.objects.filter(estado='CERRADA', creada_por_bot=True).order_by('-id')[:5]
for trade in closed_trades:
    print(f"ID: {trade.id}, Type: {trade.contract_type}, Profit: ${trade.profit:.2f}")

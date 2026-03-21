@echo off
chcp 65001 >nul
title Estado Bot Deriv
color 0B

:LOOP
cls
echo.
echo ========================================================
echo       ESTADO ACTUAL DEL BOT - %date% %time%
echo ========================================================
echo.

cd /d E:\Binary-bot

python -c "
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
sys.path.insert(0, r'E:\Binary-bot')
django.setup()

from gestion_riesgo.models import Cuenta, OperacionDeriv
from django.utils import timezone

cuenta = Cuenta.objects.filter(simbolo='R_100').first()
if cuenta:
    balance = cuenta.balance_deriv or 0
    target = balance * 1.10
    necesita = target - balance
    
    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    trades = OperacionDeriv.objects.filter(cuenta=cuenta, creada_por_bot=True, updated_at__gte=today)
    
    wins = trades.filter(profit__gt=0).count()
    losses = trades.filter(profit__lt=0).count()
    total = trades.count()
    winrate = (wins/total*100) if total > 0 else 0
    profit = sum(t.profit for t in trades if t.profit)
    
    print(f'BALANCE:        \${balance:.2f}')
    print(f'TARGET 10%:     \${target:.2f}')
    print(f'NECESITA:       \${necesita:.2f}')
    print(f'ESTADO:         {\"BLOQUEADO\" if cuenta.bloqueado else \"ACTIVO\"}')
    print(f'MOTIVO:         {cuenta.riesgo_motivo}')
    print(f'--- HOY ---')
    print(f'TRADES:         {total}')
    print(f'WINS/LOSSES:    {wins}/{losses}')
    print(f'WINRATE:        {winrate:.1f}%')
    print(f'PROFIT:         \${profit:.2f}')
else:
    print('Cuenta no encontrada')
"

echo.
echo --- ULTIMOS LOGS ---
echo.
powershell -Command "Get-Content logs/runtime.log -Tail 20"

echo.
echo ========================================================
echo Actualizando en 30 segundos... (Ctrl+C para salir)
echo ========================================================
timeout /t 30 /nobreak >nul
goto LOOP

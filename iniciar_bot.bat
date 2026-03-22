@echo off
chcp 65001 >nul
title Bot Deriv R_100 - Trading Optimizado
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║           BOT DERIV R_100 - TRADING OPTIMIZADO              ║
echo ║           Solo opera 20:00-21:00 UTC (70%+ winrate)        ║
echo ║           Target: 10%% ganancia diaria                      ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

cd /d E:\Binary-bot

:loop
echo [%date% %time%] Iniciando bot...
echo.

python bot_simple.py --real

echo.
echo [%date% %time%] Bot detenido. Reiniciando en 10 segundos...
timeout /t 10 /nobreak >nul
goto loop

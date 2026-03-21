@echo off
chcp 65001 >nul
title BOT DERIV R_100 - TRADING OPTIMIZADO
color 0A
cls

echo.
echo ========================================================
echo       BOT DERIV R_100 - TRADING OPTIMIZADO
echo ========================================================
echo   Solo opera: 20:00-21:00 UTC (15:00-16:00 Colombia)
echo   Target: 10% ganancia diaria
echo   Modo: REAL
echo ========================================================
echo.

cd /d E:\Binary-bot

:LOOP
echo [%time%] Iniciando bot...
echo.

python manage.py bot_con_panel --real --sin-migrar --ilimitado

echo.
echo [%time%] Bot detenido.
echo Reiniciando en 15 segundos...
timeout /t 15 /nobreak >nul
echo.
goto LOOP

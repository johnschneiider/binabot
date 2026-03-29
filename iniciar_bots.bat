@echo off
echo ========================================
echo  INICIANDO SERVIDOR Y BOT DE TRADING
echo ========================================
echo.

echo [1] Iniciando servidor Django...
start "Django Server" cmd /k "cd /d E:\Binary-bot && python manage.py runserver"

echo.
echo [2] Esperando 5 segundos...
timeout /t 5 /nobreak >nul

echo [3] Iniciando bot de Binance...
start "Binance Bot" cmd /k "cd /d E:\Binary-bot && python binance_bot_django.py"

echo.
echo ========================================
echo  Ambos servicios iniciados
echo  - Django: http://127.0.0.1:8000
echo  - Bot: ventana separada
echo ========================================
echo.
pause

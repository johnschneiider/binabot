@echo off
echo ========================================
echo  INICIANDO SISTEMA - QUANT DERIV (BINANCE)
echo ========================================
echo.
echo [1] Ejecutando auditoria de seguridad...
python audit_seguridad.py
echo.
echo [2] Iniciando Django Server...
start "Django Server" cmd /k "cd /d E:\Binary-bot && python manage.py runserver"

echo.
echo [3] Esperando 3 segundos...
timeout /t 3 /nobreak >nul

echo [4] Iniciando Bot Binance...
start "Binance Bot" cmd /k "cd /d E:\Binary-bot && python binance_bot_django.py"

echo.
echo ========================================
echo  SISTEMA INICIADO
echo ========================================
echo  - Django: http://127.0.0.1:8000
echo  - Dashboard: http://127.0.0.1:8000/panel/binance/
echo  - Auditoria: ejecutada
echo ========================================
echo.
echo Presiona cualquier tecla para salir...
pause >nul

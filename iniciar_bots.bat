@echo off
echo ========================================
echo  INICIANDO SISTEMA - SNIPER PULLBACK ML v2
echo ========================================
echo.
echo [1] Ejecutando auditoria de seguridad...
"E:\Binary-bot\.venv\Scripts\python.exe" audit_seguridad.py
echo.
echo [2] Iniciando Django Server...
start "Django Server" cmd /k "cd /d E:\Binary-bot && E:\Binary-bot\.venv\Scripts\python.exe manage.py runserver"

echo.
echo [3] Esperando 3 segundos...
timeout /t 3 /nobreak >nul

echo [4] Iniciando Bot Binance (Sniper Pullback ML v2 - DINERO REAL)...
start "Binance Bot ML" cmd /k "cd /d E:\Binary-bot && E:\Binary-bot\.venv\Scripts\python.exe binance_bot_django.py"

echo.
echo [5] Iniciando Chat Bot (OpenCode respuestas automaticas)...
start "Chat Bot" cmd /k "cd /d E:\Binary-bot && E:\Binary-bot\.venv\Scripts\python.exe gestion_riesgo\management\commands\chat_bot.py"

echo.
echo ========================================
echo  SISTEMA INICIADO
echo ========================================
echo  - Django: http://127.0.0.1:8000
echo  - Dashboard: http://127.0.0.1:8000/panel/binance/
echo  - ML Gate: ETHUSDT CALL/PUT + BTCUSDT CALL (si balance>$20)
echo  - WR esperado: ETH CALL 69%%  BTC CALL 72.5%%
echo ========================================
echo.
echo Presiona cualquier tecla para salir...
pause >nul

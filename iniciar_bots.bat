@echo off
echo ========================================
echo  INICIANDO SISTEMA - MICRO SNIPER ML v3
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

echo [4] Iniciando Bot Binance (Micro Sniper ML v3 - DINERO REAL)...
start "Binance Bot ML" cmd /k "cd /d E:\Binary-bot && E:\Binary-bot\.venv\Scripts\python.exe binance_bot_django.py"

echo.
echo [5] Iniciando Chat Bot (OpenCode respuestas automaticas)...
start "Chat Bot" cmd /k "cd /d E:\Binary-bot && E:\Binary-bot\.venv\Scripts\python.exe gestion_riesgo\management\commands\chat_bot.py"

echo.
echo ========================================
echo  SISTEMA INICIADO - MICRO SNIPER v3
echo ========================================
echo  - Django: http://127.0.0.1:8000
echo  - Dashboard: http://127.0.0.1:8000/panel/binance/
echo  - ML Gate: ETHUSDT CALL/PUT + BTCUSDT CALL + SOLUSDT CALL
echo  - TP: +0.15%% | SL: -0.12%% | Trail: 0.08%%/0.06%%
echo  - Scalp 3min | 80%%+ WR target | 5%%+ retorno diario
echo  - Sizing dinamico: crece con el capital
echo ========================================
echo.
echo Presiona cualquier tecla para salir...
pause >nul

@echo off
echo ========================================
echo  MENU DE BOTS - QUANT.DERIV
echo ========================================
echo.
echo [1] Iniciar Django Server
echo [2] Iniciar Bot Binance
echo [3] Iniciar Bot Forex (AllTick)
echo [4] Iniciar AMBOS Bots
echo [5] Detener todos los bots
echo.
echo ========================================
echo.

set /p opcion="Selecciona una opcion (1-5): "

if "%opcion%"=="1" goto django
if "%opcion%"=="2" goto binance
if "%opcion%"=="3" goto forex
if "%opcion%"=="4" goto ambos
if "%opcion%"=="5" goto stop
goto inicio

:django
echo.
echo [1] Iniciando servidor Django...
start "Django Server" cmd /k "cd /d E:\Binary-bot && python manage.py runserver"
echo.
echo Servidor Django iniciado en http://127.0.0.1:8000
echo.
pause
goto fin

:binance
echo.
echo [2] Iniciando bot de Binance...
start "Binance Bot" cmd /k "cd /d E:\Binary-bot && python binance_bot_django.py"
echo.
echo Bot Binance iniciado
echo.
pause
goto fin

:forex
echo.
echo [3] Iniciando bot de Forex (AllTick)...
start "Forex Bot" cmd /k "cd /d E:\Binary-bot && python trading_bot.py"
echo.
echo Bot Forex iniciado
echo.
pause
goto fin

:ambos
echo.
echo [1] Iniciando servidor Django...
start "Django Server" cmd /k "cd /d E:\Binary-bot && python manage.py runserver"

echo.
echo [2] Esperando 3 segundos...
timeout /t 3 /nobreak >nul

echo [3] Iniciando bot de Binance...
start "Binance Bot" cmd /k "cd /d E:\Binary-bot && python binance_bot_django.py"

echo [4] Iniciando bot de Forex...
start "Forex Bot" cmd /k "cd /d E:\Binary-bot && python trading_bot.py"

echo.
echo ========================================
echo  TODOS LOS SERVICIOS INICIADOS
echo ========================================
echo  - Django: http://127.0.0.1:8000
echo  - Dashboard Binance: http://127.0.0.1:8000/panel/binance/
echo  - Dashboard Forex: http://127.0.0.1:8000/panel/trading/
echo ========================================
echo.
pause
goto fin

:stop
echo.
echo [X] Deteniendo todos los procesos Python...
taskkill /F /IM python.exe 2>nul
echo.
echo Todos los bots detenidos.
echo.
pause
goto fin

:fin

@echo off
echo ========================================
echo  DETENIENDO BOTS
echo ========================================
echo.

echo [1] Deteniendo procesos Python...
taskkill /F /IM python.exe 2>nul

echo.
echo [2] Deteniendo servidor Django...
taskkill /F /F /IM python.exe /FI "WINDOWTITLE eq Django Server*" 2>nul
taskkill /F /F /IM python.exe /FI "WINDOWTITLE eq Binance Bot*" 2>nul

echo.
echo ========================================
echo  Bots detenidos
echo ========================================
echo.
pause

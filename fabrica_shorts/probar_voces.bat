@echo off
rem ============================================================
rem  ESCUCHAR VOCES PARA ELEGIR LA DE CADA PERSONAJE
rem  Doble clic. Crea MP3 de ejemplo en salida\muestras_voces
rem ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Primero haz doble clic en instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" probar_voces.py
if exist "salida\muestras_voces" start "" "salida\muestras_voces"
pause

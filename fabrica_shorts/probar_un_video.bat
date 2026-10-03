@echo off
rem ============================================================
rem  CREAR SOLO EL VIDEO 01 (para probar como queda)
rem  Doble clic. El video aparece en la carpeta "salida".
rem ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Primero haz doble clic en instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" crear_videos.py 01 --forzar
if exist "salida" start "" "salida"
pause

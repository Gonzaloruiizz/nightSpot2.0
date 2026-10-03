@echo off
rem ============================================================
rem  CREAR LOS VIDEOS. Doble clic en este archivo.
rem  Los videos terminados aparecen en la carpeta "salida".
rem ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Primero haz doble clic en instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" crear_videos.py %*
echo.
echo Los videos estan en la carpeta "salida".
if exist "salida" start "" "salida"
pause

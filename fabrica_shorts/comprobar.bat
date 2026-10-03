@echo off
rem Comprueba que todo esta bien instalado. Doble clic en este archivo.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Primero haz doble clic en instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" comprobar.py
echo.
pause

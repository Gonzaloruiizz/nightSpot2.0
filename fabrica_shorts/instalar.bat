@echo off
rem ============================================================
rem  INSTALAR LA FABRICA DE SHORTS (solo hace falta una vez)
rem  Doble clic en este archivo.
rem ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

echo.
echo === Instalando la fabrica de shorts ===
echo.

set "PY=python"
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"

%PY% --version >nul 2>nul
if errorlevel 1 goto sin_python

if not exist ".venv\Scripts\python.exe" (
    echo Creando la carpeta .venv con las librerias...
    %PY% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" goto sin_python

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] No se pudieron instalar las librerias. Revisa tu conexion a internet.
    pause
    exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

".venv\Scripts\python.exe" comprobar.py
echo.
pause
exit /b 0

:sin_python
echo [ERROR] No encuentro Python.
echo Instalalo desde https://www.python.org/downloads/
echo y MARCA la casilla "Add python.exe to PATH" al instalar.
pause
exit /b 1

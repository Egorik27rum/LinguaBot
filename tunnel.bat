@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
) else (
    set "PY=python"
)
set "PYTHONIOENCODING=utf-8"
"%PY%" setup_tunnel.py %*
echo.
pause

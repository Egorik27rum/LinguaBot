@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Окружение не найдено. Запустите install.bat.
    pause
    exit /b 1
)
if exist "%~dp0tools\ffmpeg\bin" set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
set "PYTHONIOENCODING=utf-8"
"%VENV_PY%" main.py
echo.
echo Бот остановлен.
pause

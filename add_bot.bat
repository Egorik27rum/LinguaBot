@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Окружение не найдено. Сначала запустите install.bat.
    pause
    exit /b 1
)
set "PYTHONIOENCODING=utf-8"
"%VENV_PY%" setup_installer.py add-bot
if errorlevel 1 (
    echo.
    echo Не удалось добавить бота. Подробности в logs\install.log
)
pause

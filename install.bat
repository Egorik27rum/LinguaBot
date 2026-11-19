@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден. Установите Python 3.12 или 3.13 с python.org и отметьте "Add python.exe to PATH".
    pause
    exit /b 1
)
python setup_installer.py %*
if errorlevel 1 (
    echo.
    echo Установка не завершена. Подробности в logs\install.log
    pause
    exit /b 1
)
echo.
echo Готово. Запустите run.bat
pause

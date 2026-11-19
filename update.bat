@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Окружение не найдено. Запустите install.bat.
    pause
    exit /b 1
)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "BACKUP=backups\%STAMP%"
mkdir "%BACKUP%" >nul 2>nul
if exist lingua_data.db copy /y lingua_data.db "%BACKUP%\" >nul
if exist .env copy /y .env "%BACKUP%\" >nul
if exist configs xcopy /e /i /y configs "%BACKUP%\configs" >nul
echo Бэкап создан: %BACKUP%
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Обновление зависимостей не удалось.
    pause
    exit /b 1
)
echo Обновление завершено. Запустите run.bat
pause

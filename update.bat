@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "REPO_URL=https://github.com/Egorik27rum/LinguaBot"
set "REPO_BRANCH=main"
if not exist ".venv\Scripts\python.exe" (
    echo Окружение не найдено. Запустите install.bat.
    pause
    exit /b 1
)

rem Бэкапится только база данных: .env содержит секреты, SETTINGS_KEY хранится отдельно
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "BACKUP=backups\%STAMP%"
mkdir "%BACKUP%" >nul 2>nul
if exist lingua_data.db (
    copy /y lingua_data.db "%BACKUP%\" >nul
    echo Бэкап создан: %BACKUP%
) else (
    echo Файл lingua_data.db не найден, бэкап базы пропущен.
    rmdir "%BACKUP%" 2>nul
)

rem Оставляем 5 самых новых папок бэкапа
powershell -NoProfile -Command "Get-ChildItem -LiteralPath 'backups' -Directory | Where-Object { $_.Name -match '^\d{8}_\d{6}$' } | Sort-Object -Property Name -Descending | Select-Object -Skip 5 | Remove-Item -Recurse -Force"

echo.
echo ВНИМАНИЕ: Бэкап содержит персональные данные учеников. Не храните его в облачных папках и репозиториях.
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo Git не найден. Установите Git for Windows: https://git-scm.com/download/win
    pause
    exit /b 1
)
echo Получение обновлений из репозитория...
if not exist ".git" (
    rem Первое подключение: игнорируемые файлы (.env, *.db, configs/, backups/) сохраняются
    git remote add origin %REPO_URL%
    git fetch origin %REPO_BRANCH%
    if errorlevel 1 goto :git_failed
    git checkout -f -B %REPO_BRANCH% origin/%REPO_BRANCH%
) else (
    git remote set-url origin %REPO_URL%
    git pull --ff-only origin %REPO_BRANCH%
)
if errorlevel 1 goto :git_failed

".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Обновление зависимостей не удалось.
    pause
    

@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "REPO_URL=https://github.com/Egorik27rum/LinguaBot"
set "REPO_BRANCH=main"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Окружение не найдено. Запустите install.bat.
    pause
    exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git не найден. Установите Git for Windows: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo Перед обновлением остановите run.bat, если он запущен в другом окне.
echo Копия базы, снятая во время работы бота, может оказаться неполной.
pause

rem Бэкапится только база данных: .env содержит секреты, SETTINGS_KEY хранится отдельно
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "BACKUP=backups\%STAMP%"
if exist lingua_data.db (
    mkdir "%BACKUP%" >nul 2>nul
    copy /y lingua_data.db "%BACKUP%\" >nul
    if errorlevel 1 (
        echo Не удалось создать бэкап базы. Обновление остановлено, файлы не изменены.
        pause
        exit /b 1
    )
    echo Бэкап создан: %BACKUP%
) else (
    echo Файл lingua_data.db не найден, бэкап базы пропущен.
)

rem Оставляем 5 самых новых папок бэкапа
powershell -NoProfile -Command "Get-ChildItem -LiteralPath 'backups' -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^\d{8}_\d{6}$' } | Sort-Object -Property Name -Descending | Select-Object -Skip 5 | Remove-Item -Recurse -Force"

echo.
echo ВНИМАНИЕ: бэкап содержит персональные данные учеников. Не храните его в облачных папках и репозиториях.
echo.

echo Получение обновлений из репозитория...
if not exist ".git" (
    rem Первое подключение: создаём репозиторий. Файлы из .gitignore (.env, *.db, configs/, backups/) не затрагиваются
    git init -q
    if errorlevel 1 goto :git_failed
    git remote add origin %REPO_URL%
    if errorlevel 1 goto :git_failed
    git fetch -q origin %REPO_BRANCH%
    if errorlevel 1 goto :git_failed
    git checkout -f -B %REPO_BRANCH% origin/%REPO_BRANCH%
    if errorlevel 1 goto :git_failed
) else (
    git remote set-url origin %REPO_URL%
    if errorlevel 1 goto :git_failed
    git fetch -q origin %REPO_BRANCH%
    if errorlevel 1 goto :git_failed
    git pull --ff-only -q origin %REPO_BRANCH%
    if errorlevel 1 goto :git_failed
)

echo.
echo Обновление зависимостей...
"%VENV_PY%" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Обновление зависимостей не удалось. Код уже обновлён, повторите установку через install.bat.
    pause
    exit /b 1
)

echo.
echo Обновление завершено.
echo Запустите run.bat: таблицы базы при старте обновятся автоматически, данные сохранятся.
echo WEBAPP_URL в .env этим обновлением не меняется. Новый публичный адрес дает tunnel.bat.
echo.
pause
exit /b 0

:git_failed
echo.
echo Не удалось получить обновления из GitHub. Проверьте интернет, прокси и доступ к репозиторию.
echo Файлы .env, configs/ и база данных не изменены. Бэкап базы, если он создан, лежит в папке backups.
pause
exit /b 1

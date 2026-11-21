'''Публичный HTTPS-адрес для Mini App через Cloudflare Quick Tunnel.

Скрипт запускает cloudflared, получает адрес вида https://xxxx.trycloudflare.com,
записывает его в WEBAPP_URL в .env и проверяет /api/health через этот адрес.
Бот читает WEBAPP_URL при старте, поэтому после запуска туннеля перезапустите run.bat.

  python setup_tunnel.py              поднять туннель, порт берётся из WEBAPP_PORT в .env
  python setup_tunnel.py --port 8088  указать порт вручную

Только стандартная библиотека: работает до установки зависимостей проекта.
'''
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / 'tools' / 'cloudflared'
ENV_FILE = ROOT / '.env'
LOG_FILE = ROOT / 'logs' / 'tunnel.log'

DEFAULT_PORT = 8088
URL_WAIT_SECONDS = 90
HEALTH_ATTEMPTS = 6
HEALTH_DELAY_SECONDS = 5

# Официальные сборки cloudflared. На macOS скрипт предлагает установку через Homebrew
DOWNLOADS = {
    'nt': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe',
    'posix': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64',
}
TRY_URL_RE = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')


def write_log(message: str) -> None:
    '''Только в файл: строки cloudflared не нужны на экране целиком.'''
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(f'{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n')


def log(message: str) -> None:
    print(message, flush=True)
    write_log(message)


def fail(message: str) -> None:
    log(f'ОШИБКА: {message}')
    sys.exit(1)


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding='utf-8-sig').splitlines():
        stripped = line.strip()
        if '=' in stripped and not stripped.startswith('#'):
            key, _, value = stripped.partition('=')
            values[key.strip()] = value.strip()
    return values


def write_webapp_url(url: str) -> None:
    '''Меняет только строку WEBAPP_URL, остальные строки .env сохраняются как есть.'''
    lines = ENV_FILE.read_text(encoding='utf-8-sig').splitlines()
    result: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith('WEBAPP_URL='):
            result.append(f'WEBAPP_URL={url}')
            replaced = True
        else:
            result.append(line)
    if not replaced:
        result.append(f'WEBAPP_URL={url}')
    # Запись на месте, а не через временный файл: так сохраняются права доступа к .env
    ENV_FILE.write_text('\n'.join(result) + '\n', encoding='utf-8')


def resolve_port(cli_port: int | None) -> int:
    if cli_port is not None:
        port = cli_port
    else:
        raw = read_env().get('WEBAPP_PORT', '').strip()
        if not raw:
            port = DEFAULT_PORT
        elif raw.isdigit():
            port = int(raw)
        else:
            fail('WEBAPP_PORT в .env должен быть числом, например 8088')
    if port == 0:
        fail('WEBAPP_PORT=0 отключает Mini App. Укажите порт, например 8088, или передайте --port')
    if not 1 <= port <= 65535:
        fail('порт должен быть в диапазоне 1–65535')
    return port


def binary_name() -> str:
    return 'cloudflared.exe' if os.name == 'nt' else 'cloudflared'


def find_cloudflared() -> str | None:
    local = TOOLS_DIR / binary_name()
    if local.exists():
        return str(local)
    return shutil.which('cloudflared')


def download_cloudflared() -> str:
    if sys.platform == 'darwin':
        fail('cloudflared не найден. Установите его командой: brew install cloudflared')
    url = DOWNLOADS['nt' if os.name == 'nt' else 'posix']
    target = TOOLS_DIR / binary_name()
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    log(f'Загрузка cloudflared: {url}')
    try:
        urllib.request.urlretrieve(url, target)
    except OSError as exc:
        target.unlink(missing_ok=True)
        fail(f'не удалось скачать cloudflared ({type(exc).__name__}). '
             'Проверьте интернет или прокси и запустите снова.')
    if os.name != 'nt':
        target.chmod(0o755)
    return str(target)


def start_tunnel(binary: str, port: int) -> tuple[subprocess.Popen, str]:
    '''Запускает туннель и ждёт адрес в выводе cloudflared.'''
    # Quick Tunnel не требует учётной записи Cloudflare; --no-autoupdate отключает самообновление
    cmd = [binary, 'tunnel', '--no-autoupdate', '--protocol', 'http2',
        '--url', f'http://127.0.0.1:{port}']
    log('Запуск туннеля: cloudflared tunnel --url http://127.0.0.1:' + str(port))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        cwd=ROOT,
    )
    found: dict[str, str] = {}
    found_event = threading.Event()

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            write_log(f'cloudflared: {line}')
            if 'url' not in found:
                match = TRY_URL_RE.search(line)
                if match:
                    found['url'] = match.group(0)
                    found_event.set()

    threading.Thread(target=reader, daemon=True).start()

    deadline = time.monotonic() + URL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if found_event.wait(1):
            return proc, found['url']
        if proc.poll() is not None:
            fail(f'cloudflared завершился с кодом {proc.returncode}. Подробности в logs/tunnel.log')
    proc.terminate()
    fail(f'cloudflared не выдал адрес за {URL_WAIT_SECONDS} секунд. Подробности в logs/tunnel.log')
    raise SystemExit(1)  # недостижимо, нужно для статического анализатора


def wait_health(url: str) -> bool:
    '''Проверяет /api/health через публичный адрес. Работает, только если бот уже запущен.'''
    for _ in range(HEALTH_ATTEMPTS):
        try:
            with urllib.request.urlopen(url + '/api/health', timeout=10) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(HEALTH_DELAY_SECONDS)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description='Публичный адрес Mini App через Cloudflare')
    parser.add_argument('--port', type=int, default=None, help='порт локального сервера Mini App')
    args = parser.parse_args()

    if not ENV_FILE.exists():
        fail('файл .env не найден. Сначала запустите install.bat')
    port = resolve_port(args.port)

    binary = find_cloudflared() or download_cloudflared()
    log(f'cloudflared: {binary}')

    proc, url = start_tunnel(binary, port)
    write_webapp_url(url)
    log(f'WEBAPP_URL записан в .env: {url}')

    if wait_health(url):
        log('Проверка пройдена: адрес отвечает, сервер Mini App доступен.')
    else:
        log('Внимание: адрес пока не отвечает. Запустите run.bat в другом окне и откройте адрес в браузере.')

    log('Туннель работает. Перезапустите run.bat, чтобы бот взял новый WEBAPP_URL.')
    log('Остановка: Ctrl+C.')
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        log('Туннель остановлен.')
        return
    if proc.returncode:
        fail(f'туннель остановлен с кодом {proc.returncode}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

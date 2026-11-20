'''
LinguaBot: мастер установки. Только стандартная библиотека, поэтому работает до установки пакетов.
  python setup_installer.py          полная установка (install.bat)
  python setup_installer.py add-bot  добавить доп. бота (add_bot.bat)
Повторный запуск безопасен: готовые шаги пропускаются.
'''
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / '.venv'
TOOLS_DIR = ROOT / 'tools' / 'ffmpeg'
TOOLS_BIN = TOOLS_DIR / 'bin'
ENV_FILE = ROOT / '.env'
DB_FILE = ROOT / 'lingua_data.db'
CONFIG_DIR = ROOT / 'configs'
BOTS_FILE = CONFIG_DIR / 'bots.json'
REQUIREMENTS = ROOT / 'requirements.txt'
LOG_FILE = ROOT / 'logs' / 'install.log'

MIN_PYTHON = (3, 11)
MAX_PYTHON_EXCLUSIVE = (3, 14)  # 3.13 допустим: audioop-lts даёт модуль audioop

FFMPEG_REQUIRED = True
FFMPEG_URL = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
FFMPEG_SHA256 = '2711e98a2a053574be81047d37af2cc4dcec069fc3f690cd9386f93212fd6d54'

POLZA_BASE_URL = 'https://api.polza.ai/v1'
POLZA_CHECK_PATH = '/models'  # уточните в документации Polza.ai

TG_PROXY = 'http://127.0.0.1:12334'

TOKEN_RE = re.compile(r'^\d{6,}:[A-Za-z0-9_-]{30,}$')
GROUP_ID_RE = re.compile(r'^-100\d{5,}$')
YES = {'y', 'yes', 'д', 'да'}


def log(message: str) -> None:
    # В лог и на экран попадают только служебные сообщения, значения секретов сюда не передаются
    print(message)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(message + '\n')


def fail(message: str) -> None:
    log(f'\nОШИБКА УСТАНОВКИ: {message}')
    sys.exit(1)


def run(cmd: list[str]) -> None:
    log('  $ ' + ' '.join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def venv_python() -> Path:
    return VENV_DIR / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def venv_works() -> bool:
    '''Проверяет, что python.exe из .venv реально запускается.'''
    py = venv_python()
    if not py.exists():
        return False
    try:
        subprocess.run(
            [str(py), '-c', 'import sys'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=60,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_ids(raw: str) -> list[int] | None:
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return [int(p) for p in parts]


def ask(prompt: str, is_valid, error: str) -> str:
    while True:
        value = input(prompt).strip()
        if is_valid(value):
            return value
        print(f'  {error}')


def read_env_value(key: str) -> str | None:
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text(encoding='utf-8-sig').splitlines():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return None


def generate_settings_key() -> str:
    '''Ключ Fernet: 32 случайных байта в urlsafe base64 (44 символа). Только stdlib.'''
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')


def ensure_settings_key() -> None:
    '''Добавляет SETTINGS_KEY в .env, если его нет. Существующий ключ не меняется:
    иначе уже зашифрованные секреты станут нечитаемыми. Значение ключа в лог не выводится.
    '''
    lines = ENV_FILE.read_text(encoding='utf-8-sig').splitlines()
    if any(line.startswith('SETTINGS_KEY=') and line.partition('=')[2].strip() for line in lines):
        return
    key = generate_settings_key()
    lines = [line for line in lines if not line.startswith('SETTINGS_KEY=')]
    lines.append(f'SETTINGS_KEY={key}')
    ENV_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    log('  SETTINGS_KEY создан в .env. Сохраните его копию отдельно: без ключа зашифрованные данные не открыть')


def restrict_permissions() -> None:
    '''Оставляет доступ к .env и БД только текущему пользователю Windows. На других ОС пропускается.'''
    if os.name != 'nt':
        return
    user = os.environ.get('USERNAME') or getpass.getuser()
    for path in (ENV_FILE, DB_FILE):
        if not path.exists():
            continue
        try:
            result = subprocess.run(
                ['icacls', str(path), '/inheritance:r', '/grant:r', f'{user}:F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as exc:
            log(f'  WARNING: icacls недоступен ({type(exc).__name__}), права на {path.name} не ограничены')
            return
        if result.returncode == 0:
            log(f'  права ограничены: {path.name}')
        else:
            log(f'  WARNING: не удалось ограничить права на {path.name} (код {result.returncode})')


def _telegram_get_me(token: str, use_proxy: bool) -> tuple[str, str | None]:
    proxies = {'http': TG_PROXY, 'https': TG_PROXY} if use_proxy else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    try:
        with opener.open(f'https://api.telegram.org/bot{token}/getMe', timeout=10) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        return 'ok', payload.get('result', {}).get('username')
    except urllib.error.HTTPError as exc:  # HTTPError раньше URLError: это его подкласс
        return ('invalid', None) if exc.code in (401, 404) else ('unknown', None)
    except (urllib.error.URLError, OSError, ValueError):
        return 'unknown', None


def check_telegram_token(token: str) -> tuple[str, str | None]:
    '''Пробует напрямую, затем через прокси. Возвращает (статус, username).'''
    for use_proxy in (False, True):
        status, username = _telegram_get_me(token, use_proxy)
        if status != 'unknown':
            return status, username
    return 'unknown', None


def check_polza(api_key: str) -> str:
    req = urllib.request.Request(
        POLZA_BASE_URL + POLZA_CHECK_PATH,
        headers={'Authorization': f'Bearer {api_key}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 'ok' if resp.status == 200 else 'unknown'
    except urllib.error.HTTPError as exc:
        return 'invalid' if exc.code in (401, 403) else 'unknown'
    except (urllib.error.URLError, OSError):
        return 'unknown'


def ask_token(label: str, taken: set[str]) -> tuple[str, str | None]:
    while True:
        token = ask(
            f'  {label}: ',
            lambda s: bool(TOKEN_RE.match(s)),
            'Токен выглядит неверно. Формат: 123456789:AAE-xxxxxxxx...',
        )
        if token in taken:
            print('  Этот токен уже используется другим ботом.')
            continue
        status, username = check_telegram_token(token)
        if status == 'invalid':
            print('  Telegram не принял токен. Проверьте его в @BotFather.')
            continue
        if status == 'ok':
            log(f'  токен подтверждён: @{username}')
        else:
            log('  WARNING: токен не удалось проверить онлайн, продолжаем')
        return token, username


def ask_polza_key() -> str:
    while True:
        key = ask(
            '  Ключ Polza.ai: ',
            lambda s: len(s) >= 10,
            'Ключ слишком короткий. Скопируйте его из личного кабинета Polza.ai.',
        )
        status = check_polza(key)
        if status == 'invalid':
            print('  Polza.ai отклонил ключ. Проверьте его и попробуйте снова.')
            continue
        log('  ключ Polza.ai принят' if status == 'ok' else '  WARNING: ключ не удалось проверить онлайн')
        return key


def ask_group_id() -> int:
    print('  Добавьте бота в группу администратором с включёнными темами.')
    print('  ID группы начинается с -100 (узнать можно через @userinfobot).')
    raw = ask(
        '  ID группы: ',
        lambda s: bool(GROUP_ID_RE.match(s)),
        'ID группы выглядит как -1001234567890',
    )
    return int(raw)


def _move_broken_bots_file(reason: str) -> dict:
    backup = BOTS_FILE.with_name(f'bots.broken-{datetime.now():%Y%m%d_%H%M%S}.json')
    BOTS_FILE.replace(backup)
    log(f'  WARNING: configs/bots.json некорректен ({reason}).')
    log(f'  Старый файл сохранён как configs/{backup.name}, создан новый список ботов.')
    return {'helpers': []}


def load_bots() -> dict:
    '''Пустой файл означает отсутствие доп. ботов. Повреждённый файл сохраняется в бэкап и сбрасывается.'''
    empty = {'helpers': []}
    if not BOTS_FILE.exists():
        return empty
    raw = BOTS_FILE.read_text(encoding='utf-8-sig').strip()  # utf-8-sig убирает BOM от Блокнота
    if not raw:
        log('  configs/bots.json пуст, используем пустой список доп. ботов')
        return empty
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _move_broken_bots_file(f'ошибка JSON: {exc}')
    if not isinstance(data, dict) or not isinstance(data.get('helpers', []), list):
        return _move_broken_bots_file('ожидался объект с полем "helpers" типа список')
    data.setdefault('helpers', [])
    return data


def save_bots(data: dict) -> None:
    '''Атомарная запись через временный файл. Токены пишутся открыто: установщик работает без cryptography.
    Шифрование выполняет main.py через migrate_bots_file() при первом запуске бота.
    '''
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BOTS_FILE.with_name(BOTS_FILE.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(BOTS_FILE)


def add_extra_bots_loop() -> None:
    data = load_bots()
    taken = {read_env_value('BOT_TOKEN')} | {b.get('token') for b in data['helpers']}
    taken.discard(None)

    while True:
        answer = input('  Добавить дополнительного бота? (да/нет): ').strip().lower()
        if answer not in YES:
            break
        token, username = ask_token('Токен дополнительного бота', taken)
        name = username or f'helper_{len(data["helpers"]) + 1}'
        data['helpers'].append({'name': name, 'token': token, 'enabled': True})
        taken.add(token)
        save_bots(data)
        log(f'  бот @{name} добавлен в configs/bots.json')


def check_python() -> None:
    version = sys.version_info[:2]
    if not (MIN_PYTHON <= version < MAX_PYTHON_EXCLUSIVE):
        fail(f'Python {version[0]}.{version[1]} не поддерживается. Используйте 3.11, 3.12 или 3.13.')


def create_venv() -> None:
    log('[1/6] Создание изолированного окружения (.venv)')
    if venv_works():
        log('  окружение исправно, пропускаем')
        return
    if VENV_DIR.exists():
        log('  найдено нерабочее окружение, пересоздаём')
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        if VENV_DIR.exists():
            fail('не удалось удалить старое .venv. Закройте программы, которые его используют, и запустите снова.')
    run([sys.executable, '-m', 'venv', str(VENV_DIR)])
    if not venv_works():
        fail('окружение создано, но python.exe из него не запускается. Проверьте, что Python установлен полностью.')


def install_packages() -> None:
    log('[2/6] Установка Python-пакетов')
    py = str(venv_python())
    run([py, '-m', 'pip', 'install', '--upgrade', 'pip'])
    run([py, '-m', 'pip', 'install', '-r', str(REQUIREMENTS)])


def find_ffmpeg() -> str | None:
    local = TOOLS_BIN / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    if local.exists():
        return str(local)
    return shutil.which('ffmpeg')


def download_ffmpeg() -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    archive = TOOLS_DIR / 'ffmpeg.zip'
    log(f'  загрузка {FFMPEG_URL}')
    try:
        urllib.request.urlretrieve(FFMPEG_URL, archive)
    except OSError as exc:
        fail(f'не удалось скачать ffmpeg ({exc}). Проверьте интернет и запустите снова.')

    if FFMPEG_SHA256 and sha256_of(archive) != FFMPEG_SHA256:
        archive.unlink()
        fail('хеш архива ffmpeg не совпал. Файл повреждён или подменён.')
    log('  SHA-256 проверен' if FFMPEG_SHA256 else '  WARNING: SHA-256 не задан, архив не проверен')

    TOOLS_BIN.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            if member.endswith(('/bin/ffmpeg.exe', '/bin/ffprobe.exe')):
                target = TOOLS_BIN / Path(member).name
                with zf.open(member) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
    archive.unlink()


def ensure_ffmpeg() -> None:
    log('[3/6] Проверка ffmpeg (нужен для голосовых сообщений)')
    if find_ffmpeg():
        log(f'  найден: {find_ffmpeg()}')
        return
    if os.name != 'nt':
        fail('ffmpeg не найден. Установите его (sudo apt install ffmpeg / brew install ffmpeg) и запустите снова.')
    log('  не найден, скачиваем portable-сборку (около 100 МБ)')
    download_ffmpeg()
    if not find_ffmpeg():
        fail('ffmpeg скачан, но ffmpeg.exe не распакован.')
    log(f'  установлен: {find_ffmpeg()}')


def configure_env() -> None:
    log('[4/6] Настройка .env (главный бот)')
    if ENV_FILE.exists():
        log('  .env уже есть, оставляем. Удалите файл, чтобы настроить заново.')
        if read_env_value('GROUP_ID') is None:
            group_id = ask_group_id()
            with ENV_FILE.open('a', encoding='utf-8') as f:
                f.write(f'\nGROUP_ID={group_id}\n')
        ensure_settings_key()
        restrict_permissions()
        return

    print('  Токен главного бота получите у @BotFather.')
    token, _ = ask_token('Токен главного бота', taken=set())
    raw_ids = ask(
        '  ID преподавателя(ей) через запятую (узнать в @userinfobot): ',
        lambda s: parse_ids(s) is not None,
        'Только цифры через запятую. Пример: 123456789, 987654321',
    )
    group_id = ask_group_id()
    polza_key = ask_polza_key()

    # pydantic-settings разбирает List[int] из JSON
    ENV_FILE.write_text(
        f'BOT_TOKEN={token}\n'
        f'ADMIN_IDS={json.dumps(parse_ids(raw_ids))}\n'
        f'GROUP_ID={group_id}\n'
        f'POLZA_API_KEY={polza_key}\n'
        f'SETTINGS_KEY={generate_settings_key()}\n',
        encoding='utf-8',
    )
    log('  .env записан (содержит секреты, не передавайте его)')
    log('  SETTINGS_KEY создан в .env. Сохраните его копию отдельно: без ключа зашифрованные данные не открыть')
    restrict_permissions()


def configure_extra_bots() -> None:
    log('[5/6] Дополнительные боты')
    data = load_bots()
    save_bots(data)
    log('  configs/bots.json готов')
    print('  Дополнительных ботов можно добавить сейчас или позже через add_bot.bat.')
    add_extra_bots_loop()


def health_check() -> None:
    log('[6/6] Проверка работоспособности')
    py = str(venv_python())

    run([
        py, '-c',
        'import aiogram, sqlalchemy, aiosqlite, httpx, pydub, pydantic_settings, cryptography; '
        'import core.config, database.engine, database.models, services.polza_client; '
        'import services.crypto, services.retention; '
        'import core.bot_manager, core.plugin_loader; '
        'from core.plugin_loader import load_plugins, build_router; '
        '[build_router(p) for p in load_plugins()]',
    ])
    log('  импорты, конфиг и плагины OK')

    load_bots()
    log('  configs/bots.json читается')

    key = read_env_value('POLZA_API_KEY')
    if key:
        status = check_polza(key)
        if status == 'invalid':
            fail('Polza.ai отклонил ключ из .env. Удалите .env и запустите install.bat заново.')
        log('  Polza.ai доступен' if status == 'ok' else '  WARNING: Polza.ai не удалось проверить')

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        if FFMPEG_REQUIRED:
            fail('ffmpeg не найден. Голосовые сообщения не будут обрабатываться.')
        return
    try:
        subprocess.run([ffmpeg, '-version'], stdout=subprocess.DEVNULL, check=True)
        log('  ffmpeg OK')
    except (subprocess.CalledProcessError, OSError):
        fail('ffmpeg найден, но не запускается.')


def add_bot_only() -> None:
    if not ENV_FILE.exists():
        fail('Сначала запустите install.bat, чтобы настроить главного бота.')
    add_extra_bots_loop()
    log('\nГотово. Перезапустите run.bat, чтобы новые боты подключились.')


def full_setup() -> None:
    check_python()
    if not REQUIREMENTS.exists():
        fail('requirements.txt не найден рядом с setup_installer.py.')
    create_venv()
    install_packages()
    ensure_ffmpeg()
    configure_env()
    configure_extra_bots()
    health_check()
    log('\nУстановка завершена. Запустите run.bat.')


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == 'add-bot':
        add_bot_only()
    else:
        full_setup()


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        fail(f'команда завершилась с кодом {exc.returncode}. Подробности в logs/install.log')
    except KeyboardInterrupt:
        fail('отменено пользователем.')
    except Exception as exc:
        fail(f'непредвиденная ошибка: {type(exc).__name__}. Подробности в logs/install.log')

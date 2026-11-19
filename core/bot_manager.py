import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot, Dispatcher

from core.bot_status import (
    STATE_ERROR,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    make_session,
    set_status,
)
from core.config import config
from core.plugin_loader import Plugin, build_router

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
BOTS_FILE = ROOT / 'configs' / 'bots.json'


@dataclass(frozen=True)
class BotSpec:
    name: str
    token: str
    role: str  # 'main', 'helper' или 'student'


def read_bots_data() -> dict:
    '''Возвращает содержимое bots.json. Битый файл вызывает ValueError, чтобы его не затереть.'''
    if not BOTS_FILE.exists():
        return {'helpers': []}
    raw = BOTS_FILE.read_text(encoding='utf-8-sig').strip()
    if not raw:
        return {'helpers': []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'configs/bots.json повреждён: {exc}') from exc
    if not isinstance(data, dict) or not isinstance(data.get('helpers', []), list):
        raise ValueError('configs/bots.json: поле "helpers" должно быть списком')
    data.setdefault('helpers', [])
    return data


def write_bots_data(data: dict) -> None:
    '''Атомарная запись: сбой не оставит битый JSON.'''
    BOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BOTS_FILE.with_name(BOTS_FILE.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(BOTS_FILE)


def read_extra_bots() -> list[BotSpec]:
    '''Включённые доп. боты. Пустой или повреждённый файл не останавливает главного бота.'''
    try:
        data = read_bots_data()
    except ValueError as exc:
        logger.error('%s. Дополнительные боты не запущены', exc)
        return []

    specs: list[BotSpec] = []
    for item in data['helpers']:
        if not isinstance(item, dict) or not item.get('enabled', True):
            continue
        token = item.get('token')
        if not isinstance(token, str) or not token.strip():
            logger.warning('Запись без токена в bots.json пропущена: %r', item.get('name'))
            continue
        specs.append(BotSpec(name=str(item.get('name', 'helper')), token=token.strip(), role='helper'))
    return specs


def known_tokens() -> set[str]:
    '''Все токены, уже использованные в проекте (главный, ученический и доп. боты, включая выключенные).'''
    tokens = {config.BOT_TOKEN}
    if config.STUDENT_BOT_TOKEN:
        tokens.add(config.STUDENT_BOT_TOKEN.strip())
    try:
        data = read_bots_data()
    except ValueError:
        return tokens
    for item in data['helpers']:
        if isinstance(item, dict) and item.get('token'):
            tokens.add(str(item['token']).strip())
    return tokens


def add_extra_bot(name_hint: str, token: str) -> str:
    '''Добавляет бота в bots.json и возвращает уникальное имя. Запуск — после перезапуска.'''
    data = read_bots_data()
    taken = {item.get('name') for item in data['helpers'] if isinstance(item, dict)}
    base = name_hint or 'helper'
    name, counter = base, 2
    while name in taken:
        name = f'{base}_{counter}'
        counter += 1
    data['helpers'].append({'name': name, 'token': token, 'enabled': True})
    write_bots_data(data)
    return name


def build_specs() -> list[BotSpec]:
    '''Главный бот всегда первый: от него зависит создание топика преподавателя.
    Ученический бот берётся из STUDENT_BOT_TOKEN. Один токен не запускается дважды.'''
    specs = [BotSpec(name='main', token=config.BOT_TOKEN, role='main')]

    student_token = (config.STUDENT_BOT_TOKEN or '').strip()
    if student_token:
        specs.append(BotSpec(name='student', token=student_token, role='student'))

    seen = {spec.token for spec in specs}
    for spec in read_extra_bots():
        if spec.token in seen:
            logger.warning('Доп. бот %s использует уже занятый токен и пропущен', spec.name)
            continue
        seen.add(spec.token)
        specs.append(spec)
    return specs


def create_bot(spec: BotSpec, plugins: list[Plugin]) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=spec.token, session=make_session())
    dp = Dispatcher()
    dp.workflow_data.update(bot_role=spec.role, bot_name=spec.name)
    for plugin in plugins:
        if spec.role in plugin.roles:
            dp.include_router(build_router(plugin))
    return bot, dp


async def run_bot(spec: BotSpec, bot: Bot, dp: Dispatcher) -> None:
    '''Ошибка вспомогательного бота не останавливает главного.'''
    set_status(spec.name, spec.role, STATE_STARTING)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        me = await bot.get_me()
        set_status(spec.name, spec.role, STATE_RUNNING, username=me.username)
        logger.info('Бот @%s (%s) запущен', me.username, spec.role)
        await dp.start_polling(bot, handle_signals=False)
        set_status(spec.name, spec.role, STATE_STOPPED)
    except asyncio.CancelledError:
        set_status(spec.name, spec.role, STATE_STOPPED)
        raise
    except Exception as exc:
        # Токен вырезаем из текста ошибки, чтобы он не попал в статус.
        message = str(exc).replace(spec.token, '***')[:150]
        set_status(spec.name, spec.role, STATE_ERROR, error=f'{type(exc).__name__}: {message}')
        logger.exception('Бот %s остановлен с ошибкой', spec.name)
        if spec.role == 'main':
            raise

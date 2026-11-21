'''Реестр ботов проекта: основной и доп. боты со статусами, проверка токенов и привязки к группе.

Используется ботом (plugins/teacher_bots.py) и Mini App. Токены в тексты и логи не попадают.
'''
from __future__ import annotations

import html
import re

from aiogram import Bot

from core.bot_manager import add_extra_bot, known_tokens, read_bots_data
from core.bot_status import (
    STATE_ERROR,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    BotStatus,
    TokenProbe,
    check_group_link,
    get_status,
    probe_token,
)

TOKEN_RE = re.compile(r'^\d{6,}:[A-Za-z0-9_-]{30,}$')

STATE_VIEW = {
    STATE_RUNNING: 'работает',
    STATE_STARTING: 'запускается',
    STATE_STOPPED: 'остановлен',
    STATE_ERROR: 'ошибка',
}
LEVEL_LABEL = {'ok': 'OK', 'warn': 'Внимание', 'error': 'Ошибка'}


def token_format_ok(token: str) -> bool:
    return bool(TOKEN_RE.match(token))


def token_taken(token: str) -> bool:
    '''Токен уже используется: основным ботом, учеников или доп. ботом из bots.json.'''
    return token in known_tokens()


def helper_items() -> tuple[list[dict], str | None]:
    '''Записи доп. ботов из configs/bots.json. Ошибка файла возвращается текстом.'''
    try:
        items = read_bots_data()['helpers']
    except ValueError as exc:
        return [], str(exc)
    return [item for item in items if isinstance(item, dict)], None


async def check_token(token: str) -> TokenProbe:
    '''getMe через Telegram. Токен не логируется.'''
    return await probe_token(token)


def save_extra_bot(name_hint: str, token: str) -> str:
    '''Записывает бота в bots.json и возвращает уникальное имя. Запуск — после перезапуска.'''
    return add_extra_bot(name_hint, token)


def _bot_line(label: str, st: BotStatus | None, enabled: bool = True,
              pending_text: str = 'ждёт перезапуска run.bat') -> list[str]:
    if not enabled:
        text = 'выключен в configs/bots.json'
    elif st is None:
        text = pending_text
    else:
        text = STATE_VIEW.get(st.state, st.state)

    name = f'@{st.username}' if st and st.username else label
    lines = [f'{html.escape(name)} — <b>{text}</b>']
    if st and st.error:
        lines.append(f'    <i>{html.escape(st.error)}</i>')
    return lines


def render_status() -> str:
    '''Текст экрана «Боты» (HTML). Совпадает с прежним render_status плагина.'''
    main = get_status('main')
    if main and main.state == STATE_RUNNING:
        head = '<b>Telegram-бот запущен!</b>'
    elif main and main.state == STATE_STARTING:
        head = '<b>Telegram-бот запускается…</b>'
    else:
        head = '<b>Основной бот не работает</b>'

    lines = [head, '']
    lines += _bot_line('основной бот', main, pending_text='не запущен')
    lines.append('')

    helpers, error = helper_items()
    if error:
        lines.append(f'Внимание: {html.escape(error)}')
    elif not helpers:
        lines.append('Доп. ботов пока нет. Нажмите «Добавить бота».')

    for item in helpers:
        name = str(item.get('name', 'helper'))
        enabled = bool(item.get('enabled', True))
        lines += _bot_line(name, get_status(name), enabled=enabled)

    return '\n'.join(lines)


async def render_link_check(main_bot: Bot) -> str:
    '''Текст проверки привязки доп. ботов к группе (HTML).'''
    helpers, error = helper_items()
    enabled = [item for item in helpers if item.get('enabled', True) and item.get('token')]

    if error:
        return f'Внимание: {html.escape(error)}'
    if not enabled:
        return 'Доп. ботов нет, проверять нечего.'

    lines = ['<b>Проверка привязки доп. ботов</b>', '']
    for item in enabled:
        report = await check_group_link(main_bot, str(item['token']).strip())
        label = f'@{report.username}' if report.username else str(item.get('name', 'helper'))
        lines.append(f'{LEVEL_LABEL[report.level]}: {html.escape(label)} — {html.escape(report.details)}')
    lines += ['', 'Ученики пишут в свои топики, поэтому бот должен быть в группе и видеть сообщения.']
    return '\n'.join(lines)

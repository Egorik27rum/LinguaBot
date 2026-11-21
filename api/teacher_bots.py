'''API ботов преподавателя: список со статусами, добавление доп. бота, проверка привязки к группе.

Токен принимается только в теле POST и наружу не возвращается. Проверка привязки работает
по имени бота: токен берётся из configs/bots.json на сервере и в ответ не попадает.
'''
from __future__ import annotations

from aiogram.exceptions import TelegramAPIError
from aiohttp import web

from api.common import flow_handler, read_json, require_admin
from core.bot_status import check_group_link, get_status
from core.config import config
from services.bot_registry import (
    check_token,
    helper_items,
    save_extra_bot,
    token_format_ok,
    token_taken,
)
from services.webapp_flow import FlowError


def _status_fields(name: str, default_state: str) -> dict:
    st = get_status(name)
    return {
        'state': st.state if st else default_state,
        'username': st.username if st else None,
        'error': st.error if st else None,
    }


@flow_handler
async def bots_list_view(request: web.Request) -> web.Response:
    require_admin(request)
    items = [{
        'name': 'main',
        'role': 'main',
        'enabled': True,
        **_status_fields('main', 'unknown'),
    }]
    if config.STUDENT_BOT_TOKEN:
        items.append({
            'name': 'student',
            'role': 'student',
            'enabled': True,
            **_status_fields('student', 'unknown'),
        })

    helpers, config_error = helper_items()
    for item in helpers:
        name = str(item.get('name', 'helper'))
        enabled = bool(item.get('enabled', True))
        if enabled:
            fields = _status_fields(name, 'pending')
        else:
            fields = {'state': 'disabled', 'username': None, 'error': None}
        items.append({'name': name, 'role': 'helper', 'enabled': enabled, **fields})

    return web.json_response({'items': items, 'config_error': config_error})


@flow_handler
async def bots_add_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    raw = body.get('token')
    if not isinstance(raw, str):
        raise FlowError('Токен бота должен быть строкой.')
    token = raw.strip()

    if not token_format_ok(token):
        raise FlowError('Токен выглядит неверно. Формат: 123456789:AAE-xxxxxxxx...')
    if token_taken(token):
        raise FlowError('Этот токен уже используется.', status=409)

    probe = await check_token(token)
    if probe.status == 'invalid':
        raise FlowError('Telegram не принял токен. Проверьте его в @BotFather.')
    if probe.status == 'unknown':
        raise FlowError('Не удалось связаться с Telegram. Попробуйте позже.', status=503)

    try:
        name = save_extra_bot(probe.username or 'helper', token)
    except ValueError:
        raise FlowError(
            'Не удалось сохранить бота: configs/bots.json недоступен или повреждён.',
            status=503,
        ) from None

    return web.json_response({
        'name': name,
        'username': probe.username,
        'restart_required': True,
    })


@flow_handler
async def bots_check_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    raw = body.get('name')
    if not isinstance(raw, str) or not raw.strip():
        raise FlowError('Укажите имя бота.')
    name = raw.strip()

    helpers, config_error = helper_items()
    if config_error:
        raise FlowError('configs/bots.json недоступен или повреждён.', status=503)

    target = next(
        (item for item in helpers if str(item.get('name')) == name and item.get('token')),
        None,
    )
    if target is None:
        raise FlowError('Бот не найден в configs/bots.json.', status=404)

    try:
        report = await check_group_link(request.app['bot'], str(target['token']).strip())
    except TelegramAPIError:
        raise FlowError('Не удалось проверить привязку: Telegram недоступен.', status=502) from None

    return web.json_response({
        'username': report.username,
        'level': report.level,
        'details': report.details,
    })


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/bots', bots_list_view)
    router.add_post('/api/teacher/bots', bots_add_view)
    router.add_post('/api/teacher/bots/check', bots_check_view)

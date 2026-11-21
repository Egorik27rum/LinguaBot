'''API настроек преподавателя: ключ Polza.ai и контекст для оценки. Доступ только по ADMIN_IDS.

Ключ принимается только в теле POST и наружу возвращается маской. Смена ключа требует confirm=true.
'''
from __future__ import annotations

from aiohttp import web

from api.common import flow_handler, mask_secret, read_json, require_admin
from services.polza_key import KEY_INVALID, KEY_OK, check_key
from services.settings import get_setting, set_setting
from services.teacher_context import CONTEXT_MAX, load_context, save_context
from services.webapp_flow import FlowError

KEY_MIN = 10
KEY_MAX = 512
POLZA_KEY_SETTING = 'polza_api_key'


@flow_handler
async def key_view(request: web.Request) -> web.Response:
    require_admin(request)
    key = await get_setting(POLZA_KEY_SETTING)
    return web.json_response({'set': bool(key), 'polza_key': mask_secret(key)})


@flow_handler
async def key_save_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    if body.get('confirm') is not True:
        raise FlowError('Смена ключа требует подтверждения: передайте confirm=true.')

    raw = body.get('api_key')
    if not isinstance(raw, str):
        raise FlowError('Ключ Polza.ai должен быть строкой.')
    key = raw.strip()
    if not KEY_MIN <= len(key) <= KEY_MAX:
        raise FlowError(f'Ключ Polza.ai должен быть от {KEY_MIN} до {KEY_MAX} символов.')

    verdict = await check_key(key)
    if verdict == KEY_INVALID:
        raise FlowError('Polza.ai отклонил ключ. Ключ не сохранён.')
    if verdict != KEY_OK:
        raise FlowError(
            'Не удалось связаться с Polza.ai. Ключ не сохранён, попробуйте позже.',
            status=503,
        )

    await set_setting(POLZA_KEY_SETTING, key)
    return web.json_response({'set': True, 'polza_key': mask_secret(key)})


@flow_handler
async def context_view(request: web.Request) -> web.Response:
    require_admin(request)
    text = await load_context()
    return web.json_response({'context': text, 'limit': CONTEXT_MAX})


@flow_handler
async def context_save_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    raw = body.get('context')
    if raw is None:
        raw = ''
    if not isinstance(raw, str):
        raise FlowError('Контекст должен быть строкой.')

    text = raw.strip()
    if len(text) > CONTEXT_MAX:
        raise FlowError(f'Контекст должен быть не длиннее {CONTEXT_MAX} символов.')

    await save_context(text)
    return web.json_response({'context': text, 'limit': CONTEXT_MAX})


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/settings/key', key_view)
    router.add_post('/api/teacher/settings/key', key_save_view)
    router.add_get('/api/teacher/settings/context', context_view)
    router.add_post('/api/teacher/settings/context', context_save_view)

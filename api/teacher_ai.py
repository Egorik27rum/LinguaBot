'''API параметров ИИ: роль, температура, длина ответа, история, исправления, язык, сброс.

Значения принимаются только из допустимых списков, иначе FlowError 400.
Доступ только по ADMIN_IDS.
'''
from __future__ import annotations

from aiohttp import web

from api.common import flow_handler, read_json, require_admin
from services.ai_settings import (
    CORRECTION_KEY,
    CORRECTION_LEVELS,
    CUSTOM_ROLE,
    CUSTOM_ROLE_MAX,
    DEFAULT_CORRECTION,
    DEFAULT_HISTORY,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_ROLE,
    DEFAULT_TEMPERATURE,
    HISTORY_KEY,
    HISTORY_OPTIONS,
    LANGUAGE_KEY,
    LANGUAGE_MODES,
    MAX_TOKENS_KEY,
    MAX_TOKENS_OPTIONS,
    ROLE_CUSTOM_KEY,
    ROLE_KEY,
    ROLE_PRESETS,
    TEMPERATURE_KEY,
    TEMPERATURE_OPTIONS,
    load_ai_params,
)
from services.settings import set_setting
from services.webapp_flow import FlowError

DEFAULTS = {
    ROLE_KEY: DEFAULT_ROLE,
    ROLE_CUSTOM_KEY: '',
    TEMPERATURE_KEY: str(DEFAULT_TEMPERATURE),
    MAX_TOKENS_KEY: str(DEFAULT_MAX_TOKENS),
    HISTORY_KEY: str(DEFAULT_HISTORY),
    CORRECTION_KEY: DEFAULT_CORRECTION,
    LANGUAGE_KEY: DEFAULT_LANGUAGE,
}


def _params_json(params) -> dict:
    return {
        'role': {'id': params.role_id, 'name': params.role_name, 'text': params.role_text},
        'temperature': params.temperature,
        'max_tokens': params.max_tokens,
        'history_limit': params.history_limit,
        'correction': params.correction,
        'reply_language': params.reply_language,
        'options': {
            'roles': [{'id': rid, 'name': name} for rid, (name, _) in ROLE_PRESETS.items()],
            'temperature': list(TEMPERATURE_OPTIONS),
            'max_tokens': list(MAX_TOKENS_OPTIONS),
            'history_limit': list(HISTORY_OPTIONS),
            'correction': [{'id': k, 'name': v[0]} for k, v in CORRECTION_LEVELS.items()],
            'reply_language': [{'id': k, 'name': v[0]} for k, v in LANGUAGE_MODES.items()],
            'custom_role_max': CUSTOM_ROLE_MAX,
        },
    }


def _number_from(body: dict, key: str, options: tuple):
    '''Число из тела запроса, которое совпадает с одним из допустимых значений.

    bool отклоняется, строка тоже. Сравнение численное: 300 и 300.0 дают один и тот же элемент списка.
    Возвращается значение из списка options, поэтому в настройки попадает только допустимое число.
    '''
    raw = body.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise FlowError(f'Значение {key} должно быть числом.')
    for option in options:
        if float(raw) == float(option):
            return option
    raise FlowError(f'Значение {key} вне допустимого списка.')


def _choice_from(body: dict, key: str, allowed) -> str:
    raw = body.get(key)
    if not isinstance(raw, str) or raw not in allowed:
        raise FlowError(f'Значение {key} вне допустимого списка.')
    return raw


@flow_handler
async def ai_view(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(_params_json(await load_ai_params()))


@flow_handler
async def ai_role_view(request: web.Request) -> web.Response:
    '''POST {role_id: friend|examiner|conversation|proofreader} или {role_id: custom, text: ...}.'''
    require_admin(request)
    body = await read_json(request)
    role_id = body.get('role_id')
    if role_id == CUSTOM_ROLE:
        text = body.get('text')
        if not isinstance(text, str):
            raise FlowError('Текст своей роли должен быть строкой.')
        text = text.strip()
        if not 1 <= len(text) <= CUSTOM_ROLE_MAX:
            raise FlowError(f'Описание роли должно быть от 1 до {CUSTOM_ROLE_MAX} символов.')
        await set_setting(ROLE_KEY, CUSTOM_ROLE)
        await set_setting(ROLE_CUSTOM_KEY, text)
    else:
        if not isinstance(role_id, str) or role_id not in ROLE_PRESETS:
            raise FlowError('Роль должна быть одной из пресетов или custom.')
        await set_setting(ROLE_KEY, role_id)
    return web.json_response(_params_json(await load_ai_params()))


@flow_handler
async def ai_temperature_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    value = _number_from(body, 'temperature', TEMPERATURE_OPTIONS)
    await set_setting(TEMPERATURE_KEY, str(value))
    return web.json_response(_params_json(await load_ai_params()))


@flow_handler
async def ai_max_tokens_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    value = _number_from(body, 'max_tokens', MAX_TOKENS_OPTIONS)
    await set_setting(MAX_TOKENS_KEY, str(value))
    return web.json_response(_params_json(await load_ai_params()))


@flow_handler
async def ai_history_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    value = _number_from(body, 'history_limit', HISTORY_OPTIONS)
    await set_setting(HISTORY_KEY, str(value))
    return web.json_response(_params_json(await load_ai_params()))


@flow_handler
async def ai_correction_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    value = _choice_from(body, 'correction', CORRECTION_LEVELS)
    await set_setting(CORRECTION_KEY, value)
    return web.json_response(_params_json(await load_ai_params()))


@flow_handler
async def ai_language_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    value = _choice_from(body, 'reply_language', LANGUAGE_MODES)
    await set_setting(LANGUAGE_KEY, value)
    return web.json_response(_params_json(await load_ai_params()))


@flow_handler
async def ai_reset_view(request: web.Request) -> web.Response:
    require_admin(request)
    for key, value in DEFAULTS.items():
        await set_setting(key, value)
    return web.json_response(_params_json(await load_ai_params()))


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/ai', ai_view)
    router.add_post('/api/teacher/ai/role', ai_role_view)
    router.add_post('/api/teacher/ai/temperature', ai_temperature_view)
    router.add_post('/api/teacher/ai/max-tokens', ai_max_tokens_view)
    router.add_post('/api/teacher/ai/history', ai_history_view)
    router.add_post('/api/teacher/ai/correction', ai_correction_view)
    router.add_post('/api/teacher/ai/language', ai_language_view)
    router.add_post('/api/teacher/ai/reset', ai_reset_view)

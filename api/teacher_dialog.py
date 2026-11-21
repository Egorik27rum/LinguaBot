'''API целей и диалога: лимит ответов нейросети, режим проверки цели, цели.

Значения принимаются только из допустимых списков, иначе FlowError 400.
Доступ только по ADMIN_IDS.
'''
from __future__ import annotations

from aiohttp import web

from api.common import flow_handler, read_json, require_admin
from services.dialogs import REPLY_LIMIT_OPTIONS, load_reply_limit, set_reply_limit
from services.goals import (
    GOAL_MODES,
    GOAL_TEXT_MAX,
    create_goal,
    get_active_goal,
    get_goal,
    list_goals,
    load_goal_mode,
    set_active_goal,
    set_goal_mode,
)
from services.webapp_flow import FlowError

GOAL_LIST_LIMIT = 10
MODE_DESCRIPTIONS_KEYS = ('soft', 'normal', 'strict')


def _goal_json(goal) -> dict:
    return {'id': goal.id, 'text': goal.text}


async def _state_json() -> dict:
    mode = await load_goal_mode()
    goal = await get_active_goal()
    return {
        'reply_limit': await load_reply_limit(),
        'reply_limit_options': list(REPLY_LIMIT_OPTIONS),
        'goal_mode': mode,
        'goal_mode_title': GOAL_MODES[mode].title,
        'active_goal': _goal_json(goal) if goal else None,
    }


def _int_value(body: dict, key: str) -> int:
    raw = body.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise FlowError(f'Значение {key} должно быть целым числом.')
    return raw


@flow_handler
async def dialog_view(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(await _state_json())


@flow_handler
async def limit_save_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    value = _int_value(body, 'reply_limit')
    if value not in REPLY_LIMIT_OPTIONS:
        raise FlowError(f'Лимит ответов должен быть одним из: {", ".join(map(str, REPLY_LIMIT_OPTIONS))}.')
    await set_reply_limit(value)
    return web.json_response(await _state_json())


@flow_handler
async def mode_modes_view(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response({
        'current': await load_goal_mode(),
        'modes': [
            {
                'id': mode_id,
                'title': GOAL_MODES[mode_id].title,
                'criteria': GOAL_MODES[mode_id].criteria,
                'cap': GOAL_MODES[mode_id].cap,
            }
            for mode_id in MODE_DESCRIPTIONS_KEYS
        ],
    })


@flow_handler
async def mode_save_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    mode = body.get('goal_mode')
    if not isinstance(mode, str) or mode not in GOAL_MODES:
        raise FlowError('Режим должен быть soft, normal или strict.')
    await set_goal_mode(mode)
    return web.json_response(await _state_json())


@flow_handler
async def goals_list_view(request: web.Request) -> web.Response:
    require_admin(request)
    goals = await list_goals(GOAL_LIST_LIMIT)
    active = await get_active_goal()
    return web.json_response({
        'active_id': active.id if active else None,
        'items': [_goal_json(g) for g in goals],
    })


@flow_handler
async def goal_create_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    raw = body.get('text')
    if not isinstance(raw, str):
        raise FlowError('Текст цели должен быть строкой.')
    text = ' '.join(raw.split())
    if not 1 <= len(text) <= GOAL_TEXT_MAX:
        raise FlowError(f'Цель должна быть от 1 до {GOAL_TEXT_MAX} символов.')
    goal = await create_goal(text)
    await set_active_goal(goal.id)
    return web.json_response({'id': goal.id})


@flow_handler
async def goal_active_view(request: web.Request) -> web.Response:
    '''POST {goal_id: число или null}: выбор активной цели, null снимает её.'''
    require_admin(request)
    body = await read_json(request)
    raw = body.get('goal_id')
    if raw is None:
        await set_active_goal(None)
    else:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise FlowError('goal_id должен быть числом или null.')
        if await get_goal(raw) is None:
            raise FlowError('Цель не найдена.', status=404)
        await set_active_goal(raw)
    return web.json_response({'active_id': raw})


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/dialog', dialog_view)
    router.add_post('/api/teacher/dialog/limit', limit_save_view)
    router.add_get('/api/teacher/dialog/mode', mode_modes_view)
    router.add_post('/api/teacher/dialog/mode', mode_save_view)
    router.add_get('/api/teacher/goals', goals_list_view)
    router.add_post('/api/teacher/goals', goal_create_view)
    router.add_post('/api/teacher/goals/active', goal_active_view)

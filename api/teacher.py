'''API преподавателя: статус, задания. Доступ только по ADMIN_IDS.

Ученики вынесены в api/teacher_students.py. Статус собирается сервисом services/teacher_status.
Ключ Polza.ai в ответе только маской.
'''
from __future__ import annotations

from aiohttp import web

from api.common import flow_handler, read_json, require_admin
from services.tasks import create_task, get_active_task, get_task, list_tasks, set_active_task
from services.task_rules import (
    content_error,
    normalize_content,
    normalize_title,
    title_error,
)
from services.teacher_status import collect_status
from services.webapp_flow import FlowError

TASK_LIST_LIMIT = 10


@flow_handler
async def status_view(request: web.Request) -> web.Response:
    require_admin(request)
    status = await collect_status()
    main = status.main_bot
    goal = status.active_goal
    task = status.active_task
    return web.json_response({
        'bot': {
            'state': main.state if main else 'unknown',
            'username': main.username if main else None,
            'error': main.error if main else None,
        },
        'polza_key': status.key_masked,
        'active_task': {'id': task.id, 'title': task.title} if task else None,
        'reply_limit': status.reply_limit,
        'goal_mode': status.goal_mode_title,
        'active_goal': {'id': goal.id, 'text': goal.text} if goal else None,
    })


@flow_handler
async def tasks_list_view(request: web.Request) -> web.Response:
    require_admin(request)
    tasks = await list_tasks(TASK_LIST_LIMIT)
    active = await get_active_task()
    return web.json_response({
        'active_id': active.id if active else None,
        'items': [{'id': t.id, 'title': t.title, 'content': t.content} for t in tasks],
    })


@flow_handler
async def tasks_create_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    raw_title = body.get('title')
    raw_content = body.get('content')
    title = normalize_title(raw_title if isinstance(raw_title, str) else '')
    content = normalize_content(raw_content if isinstance(raw_content, str) else '')
    for error in (title_error(title), content_error(content)):
        if error:
            raise FlowError(error)
    task = await create_task(title, content)
    await set_active_task(task.id)  # как в боте: новое задание сразу становится активным
    return web.json_response({'id': task.id})


@flow_handler
async def tasks_active_view(request: web.Request) -> web.Response:
    require_admin(request)
    body = await read_json(request)
    raw = body.get('task_id')
    if raw is None:
        await set_active_task(None)
    else:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise FlowError('task_id должен быть числом или null.')
        if await get_task(raw) is None:
            raise FlowError('Задание не найдено.', status=404)
        await set_active_task(raw)
    return web.json_response({'ok': True})


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/status', status_view)
    router.add_get('/api/teacher/tasks', tasks_list_view)
    router.add_post('/api/teacher/tasks', tasks_create_view)
    router.add_post('/api/teacher/tasks/active', tasks_active_view)

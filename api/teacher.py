'''API преподавателя (этап 1): статус, задания, ученики. Доступ только по ADMIN_IDS.'''
from __future__ import annotations

from aiohttp import web

from api.common import flow_handler, int_query, mask_secret, read_json, require_admin
from core.bot_status import get_status
from services.dialogs import load_reply_limit
from services.goals import GOAL_MODES, get_active_goal, load_goal_mode
from services.settings import get_setting
from services.students import delete_student, list_students
from services.tasks import create_task, get_active_task, get_task, list_tasks, set_active_task
from services.webapp_flow import FlowError

TASK_LIST_LIMIT = 10
STUDENT_PAGE = 8
TITLE_MAX = 100
CONTENT_MAX = 2000


@flow_handler
async def status_view(request: web.Request) -> web.Response:
    require_admin(request)
    main = get_status('main')
    key = await get_setting('polza_api_key')
    active = await get_active_task()
    goal = await get_active_goal()
    mode = await load_goal_mode()
    return web.json_response({
        'bot': {
            'state': main.state if main else 'unknown',
            'username': main.username if main else None,
            'error': main.error if main else None,
        },
        'polza_key': mask_secret(key),
        'active_task': {'id': active.id, 'title': active.title} if active else None,
        'reply_limit': await load_reply_limit(),
        'goal_mode': GOAL_MODES[mode].title,
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
    title = ' '.join(str(body.get('title') or '').split())
    content = str(body.get('content') or '').strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise FlowError(f'Название должно быть от 1 до {TITLE_MAX} символов.')
    if not 1 <= len(content) <= CONTENT_MAX:
        raise FlowError(f'Условие должно быть от 1 до {CONTENT_MAX} символов.')
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
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise FlowError('task_id должен быть числом или null.')
        if await get_task(raw) is None:
            raise FlowError('Задание не найдено.', status=404)
        await set_active_task(raw)
    return web.json_response({'ok': True})


@flow_handler
async def students_view(request: web.Request) -> web.Response:
    require_admin(request)
    students, page, pages, total = await list_students(int_query(request, 'page', 0), STUDENT_PAGE)
    return web.json_response({
        'page': page,
        'pages': pages,
        'total': total,
        'items': [{
            'id': s.id,
            'name': s.full_name or 'Ученик',
            'username': s.username,
            'has_topic': bool(s.topic_id),
        } for s in students],
    })


@flow_handler
async def student_delete_view(request: web.Request) -> web.Response:
    require_admin(request)
    student_id = int(request.match_info['student_id'])
    delete_topic = request.query.get('topic') == '1'
    result = await delete_student(request.app['bot'], student_id, delete_topic)
    if result is None:
        raise FlowError('Ученик не найден.', status=404)
    return web.json_response({'name': result.name, 'topic_note': result.topic_note})


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/status', status_view)
    router.add_get('/api/teacher/tasks', tasks_list_view)
    router.add_post('/api/teacher/tasks', tasks_create_view)
    router.add_post('/api/teacher/tasks/active', tasks_active_view)
    router.add_get('/api/teacher/students', students_view)
    router.add_delete(r'/api/teacher/students/{student_id:\d+}', student_delete_view)

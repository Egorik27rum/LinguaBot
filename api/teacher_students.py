'''API учеников: список по 8 на страницу и удаление с параметром topic.

Удаление необратимо, поэтому требует подтверждения на фронтенде; сервер проверяет только права и id.
'''
from __future__ import annotations

from aiohttp import web

from api.common import flow_handler, int_query, require_admin
from services.students import delete_student, list_students
from services.webapp_flow import FlowError

STUDENT_PAGE = 8


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
    raw_id = request.match_info['student_id']
    if not raw_id.isdigit():
        raise FlowError('Некорректный идентификатор ученика.')
    student_id = int(raw_id)
    delete_topic = request.query.get('topic') == '1'
    result = await delete_student(request.app['bot'], student_id, delete_topic)
    if result is None:
        raise FlowError('Ученик не найден.', status=404)
    return web.json_response({'name': result.name, 'topic_note': result.topic_note})


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/students', students_view)
    router.add_delete(r'/api/teacher/students/{student_id:\d+}', student_delete_view)

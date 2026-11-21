'''API ученика. Все маршруты требуют действительного initData.'''
from __future__ import annotations

from aiohttp import web

from api.common import flow_handler, int_query, read_json
from services import webapp_flow as flow


@flow_handler
async def state_view(request: web.Request) -> web.Response:
    return web.json_response(await flow.get_state(request['user'].tg_id))


@flow_handler
async def register_view(request: web.Request) -> web.Response:
    user = request['user']
    body = await read_json(request)
    await flow.register(request.app['bot'], user.tg_id, user.username, body.get('full_name'))
    return web.json_response(await flow.get_state(user.tg_id))


@flow_handler
async def start_view(request: web.Request) -> web.Response:
    user = request['user']
    notice = await flow.start_dialog(request.app['bot'], user.tg_id)
    return web.json_response({'notice': notice, 'state': await flow.get_state(user.tg_id)})


@flow_handler
async def finish_view(request: web.Request) -> web.Response:
    result = await flow.finish_dialog(request.app['bot'], request['user'].tg_id)
    return web.json_response(result)


@flow_handler
async def message_view(request: web.Request) -> web.Response:
    user = request['user']
    body = await read_json(request)
    result = await flow.handle_message(request.app['bot'], user.tg_id, body.get('text'))
    return web.json_response(result)


@flow_handler
async def chat_view(request: web.Request) -> web.Response:
    return web.json_response(await flow.get_chat(request['user'].tg_id))


@flow_handler
async def dialogs_view(request: web.Request) -> web.Response:
    page = int_query(request, 'page', 0)
    return web.json_response(await flow.list_dialogs(request['user'].tg_id, page))


@flow_handler
async def dialog_view(request: web.Request) -> web.Response:
    session_id = int(request.match_info['session_id'])
    return web.json_response(await flow.dialog_detail(request['user'].tg_id, session_id))


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/student/state', state_view)
    router.add_post('/api/student/register', register_view)
    router.add_post('/api/student/dialog', start_view)
    router.add_post('/api/student/dialog/finish', finish_view)
    router.add_post('/api/student/message', message_view)
    router.add_get('/api/student/chat', chat_view)
    router.add_get('/api/student/dialogs', dialogs_view)
    router.add_get(r'/api/student/dialogs/{session_id:\d+}', dialog_view)

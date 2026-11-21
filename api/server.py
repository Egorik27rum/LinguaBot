'''HTTP-сервер Mini App на aiohttp. Работает в том же event loop, что и боты.

  /              страница приложения ученика
  /teacher       страница преподавателя (доступ проверяется в API)
  /static/...    JavaScript и CSS
  /api/health    проверка работоспособности, без авторизации
  /api/...       JSON-API: каждый запрос проверяет initData
'''
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from aiogram import Bot
from aiohttp import web

from api import student as student_api
from api import teacher as teacher_api
from api.auth import InitDataError, verify_init_data
from core.config import config

logger = logging.getLogger(__name__)

WEBAPP_DIR = Path(__file__).resolve().parent.parent / 'webapp'

SECURITY_HEADERS = {
    'Content-Security-Policy': (
        "default-src 'self'; "
        "script-src 'self' https://telegram.org; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; form-action 'none'"
    ),
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
}


def _allowed_origin() -> str | None:
    '''Единственный разрешённый источник для CORS: адрес приложения без пути.'''
    if not config.WEBAPP_URL:
        return None
    parts = urlsplit(config.WEBAPP_URL)
    return f'{parts.scheme}://{parts.netloc}'


async def _check_and_call(request: web.Request, handler) -> web.StreamResponse:
    if request.path.startswith('/api/') and request.path != '/api/health':
        header = request.headers.get('Authorization', '')
        init_data = header[4:] if header.startswith('tma ') else ''
        try:
            request['user'] = verify_init_data(
                init_data, request.app['tokens'], config.WEBAPP_AUTH_MAX_AGE,
            )
        except InitDataError as exc:
            return web.json_response({'error': str(exc)}, status=401)
    return await handler(request)


@web.middleware
async def guard(request: web.Request, handler) -> web.StreamResponse:
    '''Единая точка входа: предварительный запрос CORS, авторизация, заголовки безопасности.'''
    if request.method == 'OPTIONS':
        response: web.StreamResponse = web.Response(status=204)
    else:
        try:
            response = await _check_and_call(request, handler)
        except web.HTTPException as exc:
            response = exc  # HTTPException — это ответ, поэтому заголовки добавляются и к ошибкам

    response.headers.update(SECURITY_HEADERS)
    origin = request.headers.get('Origin')
    if origin and origin == _allowed_origin():
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        response.headers['Vary'] = 'Origin'
    return response


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEBAPP_DIR / 'index.html')


async def teacher_page(request: web.Request) -> web.FileResponse:
    # Сама страница не содержит данных: все они запрашиваются через API с проверкой initData
    return web.FileResponse(WEBAPP_DIR / 'teacher.html')


async def health(request: web.Request) -> web.Response:
    return web.json_response({'status': 'ok'})


def create_app(bot: Bot, tokens: set[str]) -> web.Application:
    app = web.Application(middlewares=[guard], client_max_size=64 * 1024)
    app['bot'] = bot
    app['tokens'] = frozenset(token for token in tokens if token)
    app.router.add_get('/', index)
    app.router.add_get('/teacher', teacher_page)
    app.router.add_get('/api/health', health)
    student_api.setup(app.router)
    teacher_api.setup(app.router)
    app.router.add_static('/static/', WEBAPP_DIR, show_index=False)
    return app


async def start_webapp(bot: Bot, tokens: set[str]) -> web.AppRunner | None:
    '''Запускает сервер в текущем event loop. Возвращает runner для остановки.'''
    if config.WEBAPP_PORT <= 0:
        logger.info('Mini App отключён (WEBAPP_PORT=0)')
        return None
    app = create_app(bot, tokens)
    runner = web.AppRunner(app, access_log=None)  # без журнала доступа: в логах не должны появляться данные запросов
    await runner.setup()
    await web.TCPSite(runner, config.WEBAPP_HOST, config.WEBAPP_PORT).start()
    logger.info('Mini App слушает %s:%s', config.WEBAPP_HOST, config.WEBAPP_PORT)
    if not config.WEBAPP_URL:
        logger.warning('WEBAPP_URL не задан: кнопка приложения в боте не работает')
    elif not config.WEBAPP_URL.startswith('https://'):
        logger.warning('WEBAPP_URL должен быть HTTPS-адресом, иначе Telegram не откроет приложение')
    return runner

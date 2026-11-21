'''Общие функции API: единый формат ошибок, чтение JSON, проверка администратора, маскировка.'''
from __future__ import annotations

import functools

from aiohttp import web

from core.config import config
from services.webapp_flow import FlowError


def flow_handler(func):
    '''Превращает FlowError в JSON-ответ {'error': текст} с нужным HTTP-кодом.'''

    @functools.wraps(func)
    async def wrapper(request: web.Request) -> web.StreamResponse:
        try:
            return await func(request)
        except FlowError as exc:
            return web.json_response({'error': str(exc)}, status=exc.status)

    return wrapper


async def read_json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise FlowError('Некорректный JSON в запросе.') from None
    if not isinstance(body, dict):
        raise FlowError('Ожидался JSON-объект.')
    return body


def require_admin(request: web.Request) -> None:
    '''Доступ только по ADMIN_IDS. tg_id берётся из проверенного initData.'''
    if request['user'].tg_id not in config.ADMIN_IDS:
        raise FlowError('Нет доступа.', status=403)


def int_query(request: web.Request, name: str, default: int = 0) -> int:
    raw = request.query.get(name, '')
    return int(raw) if raw.isdigit() else default


def mask_secret(value: str | None) -> str | None:
    '''Ключ наружу отдаётся только маской: полный ключ во фронтенд не попадает.'''
    if not value:
        return None
    return '***' + value[-4:] if len(value) > 8 else '***'

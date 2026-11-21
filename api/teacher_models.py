'''API моделей Polza.ai: список по роли, полный список с ценами, выбор, обновление и сброс.

Доступ только по ADMIN_IDS. Ключ Polza.ai берётся из настроек на сервере и наружу не отдаётся.
'''
from __future__ import annotations

import httpx
from aiohttp import web

from api.common import flow_handler, int_query, read_json, require_admin
from services.polza_models import (
    CATEGORY_ORDER,
    CATEGORY_TITLES,
    DEFAULT_SORT,
    ROLE_CATEGORIES,
    ROLE_SETTING,
    ROLE_TITLES,
    SORT_MODES,
    PolzaModel,
    format_prices,
    get_models,
    sort_models,
)
from services.settings import get_setting, set_setting
from services.teacher_models_view import PAGE_SIZE, clamp_page, reset_model
from services.webapp_flow import FlowError

ROLE_IDS = tuple(ROLE_SETTING)
MODEL_ID_MAX = 200


async def _api_key() -> str:
    key = await get_setting('polza_api_key')
    if not key:
        raise FlowError('Сначала задайте ключ Polza.ai в настройках.', status=409)
    return key


async def _models(force: bool = False) -> list[PolzaModel]:
    try:
        return await get_models(await _api_key(), force=force)
    except (httpx.HTTPError, ValueError):
        raise FlowError('Не удалось получить список моделей. Попробуйте позже.', status=502) from None


def _check_role(raw: str | None) -> str:
    if raw not in ROLE_IDS:
        raise FlowError('Роль должна быть text или speech.')
    return raw


def _check_category(role: str, raw: str | None) -> str:
    if raw not in ROLE_CATEGORIES[role]:
        raise FlowError('Категория не подходит выбранной роли.')
    return raw


def _check_sort(raw: str | None) -> str:
    if raw is None:
        return DEFAULT_SORT
    if raw not in SORT_MODES:
        raise FlowError('Сортировка должна быть rec, desc или asc.')
    return raw


def _model_json(model: PolzaModel) -> dict:
    return {
        'id': model.id,
        'name': model.name,
        'category': model.category,
        'price_in': model.price_in,
        'price_out': model.price_out,
        'prices': format_prices(model),
    }


@flow_handler
async def models_list_view(request: web.Request) -> web.Response:
    '''GET /api/teacher/models?role=text|speech&category=...&sort=rec|desc|asc&page=N'''
    require_admin(request)
    role = _check_role(request.query.get('role'))
    category = request.query.get('category') or ROLE_CATEGORIES[role][0]
    _check_category(role, category)
    sort = _check_sort(request.query.get('sort'))

    models = await _models()
    items = sort_models([m for m in models if m.category == category], sort)
    page, pages = clamp_page(int_query(request, 'page', 0), len(items))
    start = page * PAGE_SIZE
    current = (await get_setting(ROLE_SETTING[role])) or None

    return web.json_response({
        'role': role,
        'role_title': ROLE_TITLES[role],
        'category': category,
        'category_title': CATEGORY_TITLES[category],
        'sort': sort,
        'page': page,
        'pages': pages,
        'page_size': PAGE_SIZE,
        'current': current,
        'items': [_model_json(m) for m in items[start:start + PAGE_SIZE]],
    })


@flow_handler
async def models_all_view(request: web.Request) -> web.Response:
    '''Полный список с ценами, сгруппированный по категориям.'''
    require_admin(request)
    models = await _models()
    groups = []
    for category in CATEGORY_ORDER:
        items = sorted((m for m in models if m.category == category), key=lambda m: m.name.lower())
        if not items:
            continue
        groups.append({
            'category': category,
            'title': CATEGORY_TITLES[category],
            'count': len(items),
            'items': [_model_json(m) for m in items],
        })
    return web.json_response({'groups': groups})


@flow_handler
async def models_select_view(request: web.Request) -> web.Response:
    '''POST {role, model_id}: выбор модели. model_id = null сбрасывает выбор на модель по умолчанию.'''
    require_admin(request)
    body = await read_json(request)
    role = _check_role(body.get('role'))
    setting = ROLE_SETTING[role]

    raw = body.get('model_id')
    if raw is None:
        await reset_model(role)
        return web.json_response({'role': role, 'current': None})

    if not isinstance(raw, str) or not raw.strip():
        raise FlowError('model_id должен быть строкой или null.')
    model_id = raw.strip()
    if len(model_id) > MODEL_ID_MAX:
        raise FlowError(f'model_id должен быть не длиннее {MODEL_ID_MAX} символов.')

    models = await _models()
    if not any(m.id == model_id and m.category in ROLE_CATEGORIES[role] for m in models):
        raise FlowError('Такой модели нет в списке Polza.ai для этой роли.', status=404)

    await set_setting(setting, model_id)
    return web.json_response({'role': role, 'current': model_id})


@flow_handler
async def models_refresh_view(request: web.Request) -> web.Response:
    require_admin(request)
    models = await _models(force=True)
    return web.json_response({'count': len(models)})


@flow_handler
async def models_reset_view(request: web.Request) -> web.Response:
    '''POST {role}: сброс модели роли на значение по умолчанию.'''
    require_admin(request)
    body = await read_json(request)
    role = _check_role(body.get('role'))
    await reset_model(role)
    return web.json_response({'role': role, 'current': None})


def setup(router: web.UrlDispatcher) -> None:
    router.add_get('/api/teacher/models', models_list_view)
    router.add_get('/api/teacher/models/all', models_all_view)
    router.add_post('/api/teacher/models/select', models_select_view)
    router.add_post('/api/teacher/models/refresh', models_refresh_view)
    router.add_post('/api/teacher/models/reset', models_reset_view)

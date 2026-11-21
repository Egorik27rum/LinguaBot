'''Проверка ключа Polza.ai до сохранения. Ключ не выводится и не логируется.'''
import logging

import httpx

from services.polza_models import BASE_URL, MODELS_PATH, REQUEST_HEADERS

logger = logging.getLogger(__name__)

KEY_OK = 'ok'
KEY_INVALID = 'invalid'
KEY_UNKNOWN = 'unknown'


def mask_key(value: str | None) -> str | None:
    '''Ключ наружу отдаётся только маской: видны последние 4 символа.'''
    if not value:
        return None
    return '***' + value[-4:] if len(value) > 8 else '***'


async def check_key(api_key: str) -> str:
    '''GET /v1/models: список моделей доступен только с действующим ключом.

    Возвращает KEY_OK, KEY_INVALID (401/403) или KEY_UNKNOWN (сеть, сервер, неверные символы).
    '''
    headers = dict(REQUEST_HEADERS)
    headers['Authorization'] = f'Bearer {api_key}'
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(BASE_URL + MODELS_PATH, headers=headers)
    except (httpx.HTTPError, UnicodeError, ValueError) as exc:
        # Только тип ошибки: текст исключения может содержать фрагменты запроса
        logger.warning('Проверка ключа Polza.ai не выполнена: %s', type(exc).__name__)
        return KEY_UNKNOWN
    if response.status_code in (401, 403):
        return KEY_INVALID
    if response.is_success:
        return KEY_OK
    return KEY_UNKNOWN

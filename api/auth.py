'''Проверка initData из Telegram Mini App.

Telegram подписывает строку initData так:
secret = HMAC-SHA256(key='WebAppData', msg=токен бота)
подпись = HMAC-SHA256(key=secret, msg=строка 'ключ=значение' без поля hash,
        отсортированная по ключам и соединённая переводом строки).

Подпись сверяется для каждого известного токену проекта: Mini App может быть открыт
и из основного, и из ученического бота.
'''
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class WebAppUser:
    tg_id: int
    first_name: str
    username: str | None


class InitDataError(Exception):
    '''initData не прошла проверку. Текст безопасен для ответа клиенту.'''


def _signature(check_string: str, token: str) -> str:
    secret = hmac.new(b'WebAppData', token.encode('utf-8'), hashlib.sha256).digest()
    return hmac.new(secret, check_string.encode('utf-8'), hashlib.sha256).hexdigest()


def verify_init_data(init_data: str, tokens: Iterable[str], max_age: int,
                     now: float | None = None) -> WebAppUser:
    '''Возвращает проверенного пользователя или поднимает InitDataError.'''
    if not init_data:
        raise InitDataError('нет данных авторизации: откройте приложение из Telegram')

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received = str(data.pop('hash', '')).lower()
    if not received:
        raise InitDataError('в данных авторизации нет подписи')

    check_string = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
    # compare_digest защищает от подбора подписи по времени ответа
    if not any(hmac.compare_digest(_signature(check_string, token), received)
               for token in tokens if token):
        raise InitDataError('подпись данных не совпала')

    try:
        auth_date = int(data.get('auth_date', ''))
    except ValueError:
        raise InitDataError('некорректная дата авторизации') from None
    current = time.time() if now is None else now
    if current - auth_date > max_age:
        raise InitDataError('сессия истекла: закройте приложение и откройте его заново')
    if auth_date > current + 60:
        raise InitDataError('дата авторизации указана в будущем')

    try:
        user = json.loads(data.get('user', ''))
    except json.JSONDecodeError:
        raise InitDataError('некорректные данные пользователя') from None
    if not isinstance(user, dict) or not isinstance(user.get('id'), int):
        raise InitDataError('некорректные данные пользователя')

    return WebAppUser(
        tg_id=user['id'],
        first_name=str(user.get('first_name') or ''),
        username=user.get('username'),
    )

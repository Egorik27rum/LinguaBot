import logging
from dataclasses import dataclass, field
from datetime import datetime

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError

from core.config import config

logger = logging.getLogger(__name__)

PROXY_URL = 'http://127.0.0.1:12334'

STATE_STARTING = 'starting'
STATE_RUNNING = 'running'
STATE_STOPPED = 'stopped'
STATE_ERROR = 'error'

MEMBER_STATUSES = {'creator', 'administrator', 'member', 'restricted'}
ADMIN_STATUSES = {'creator', 'administrator'}


@dataclass(frozen=True)
class BotStatus:
    name: str
    role: str
    state: str
    username: str | None = None
    error: str | None = None
    updated_at: datetime = field(default_factory=datetime.now)


_registry: dict[str, BotStatus] = {}


def set_status(name: str, role: str, state: str,
               username: str | None = None, error: str | None = None) -> None:
    previous = _registry.get(name)
    if username is None and previous is not None:
        username = previous.username
    _registry[name] = BotStatus(name=name, role=role, state=state,
                                username=username, error=error)


def get_status(name: str) -> BotStatus | None:
    return _registry.get(name)


def make_session() -> AiohttpSession:
    return AiohttpSession(proxy=PROXY_URL)


@dataclass(frozen=True)
class TokenProbe:
    status: str  # 'ok' | 'invalid' | 'unknown'
    user_id: int | None = None
    username: str | None = None
    can_read_all_group_messages: bool = False


async def probe_token(token: str) -> TokenProbe:
    '''Проверяет токен через getMe. Токен в логи не выводится.'''
    bot = Bot(token=token, session=make_session())
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        return TokenProbe(status='invalid')
    except Exception as exc:
        logger.warning('Не удалось проверить токен бота: %s', type(exc).__name__)
        return TokenProbe(status='unknown')
    finally:
        await bot.session.close()
    return TokenProbe(
        status='ok',
        user_id=me.id,
        username=me.username,
        can_read_all_group_messages=bool(me.can_read_all_group_messages),
    )


@dataclass(frozen=True)
class LinkReport:
    username: str | None
    level: str  # 'ok' | 'warn' | 'error'
    details: str


async def check_group_link(main_bot: Bot, token: str) -> LinkReport:
    '''Проверяет, что доп. бот состоит в группе и видит сообщения учеников.'''
    probe = await probe_token(token)
    if probe.status == 'invalid':
        return LinkReport(None, 'error', 'Telegram не принял токен')
    if probe.status == 'unknown':
        return LinkReport(None, 'error', 'не удалось связаться с Telegram')

    try:
        member = await main_bot.get_chat_member(config.GROUP_ID, probe.user_id)
    except TelegramAPIError:
        return LinkReport(probe.username, 'error', 'не найден в группе')

    if member.status not in MEMBER_STATUSES:
        return LinkReport(probe.username, 'error', 'не добавлен в группу')
    if member.status in ADMIN_STATUSES:
        return LinkReport(probe.username, 'ok', 'администратор группы, видит сообщения учеников')
    if probe.can_read_all_group_messages:
        return LinkReport(probe.username, 'ok', 'участник группы, режим приватности выключен')
    return LinkReport(
        probe.username,
        'warn',
        'участник без прав администратора: видит только команды и упоминания. '
        'Сделайте бота администратором',
    )

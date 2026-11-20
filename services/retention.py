'''Срок хранения данных: удаляет старую историю диалогов и обнуляет расшифровки.
Оценки (score) сохраняются, очищается только текст расшифровки.
'''
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from database.engine import async_session
from database.models import Attempt, ChatMessage

logger = logging.getLogger(__name__)

DAY_SECONDS = 24 * 60 * 60


async def purge_old_data(days: int) -> tuple[int, int]:
    '''Возвращает (удалено сообщений, очищено расшифровок).'''
    # SQLite хранит DateTime без таймзоны, поэтому граница задаётся как naive UTC
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    async with async_session() as session:
        messages = await session.execute(
            delete(ChatMessage).where(ChatMessage.created_at < cutoff)
        )
        attempts = await session.execute(
            update(Attempt)
            .where(Attempt.created_at < cutoff, Attempt.transcription.is_not(None))
            .values(transcription=None)
        )
        await session.commit()
    return messages.rowcount or 0, attempts.rowcount or 0


async def retention_loop(days: int) -> None:
    '''Первый проход сразу при старте, затем раз в сутки. Ошибка прохода цикл не останавливает.'''
    if days <= 0:
        logger.info('Очистка по сроку хранения отключена (RETENTION_DAYS=%s)', days)
        return
    while True:
        try:
            messages, attempts = await purge_old_data(days)
            logger.info('Очистка данных: удалено сообщений %s, очищено расшифровок %s',
                        messages, attempts)
        except Exception as exc:
            logger.error('Очистка устаревших данных не выполнена: %s', type(exc).__name__)
        await asyncio.sleep(DAY_SECONDS)

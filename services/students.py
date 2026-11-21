import logging
import math
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from sqlalchemy import delete, func, select

from core.config import config
from database.engine import async_session
from database.models import Attempt, ChatMessage, DialogSession, Student, TopicMessage
from services import chat_cleanup, screen, topic_history
from services.dialogs import OPEN_STATUSES, cancel_session
from services.topics import ensure_student_topic

logger = logging.getLogger(__name__)

TG_LIMIT = 4000
CAPTION_LIMIT = 1024


def cut_text(text: str, limit: int = TG_LIMIT) -> str:
    '''Обрезает текст под лимит сообщения Telegram.'''
    return text if len(text) <= limit else text[: limit - 1] + '…'


async def find_student(tg_id: int) -> Student | None:
    async with async_session() as session:
        return await session.scalar(select(Student).where(Student.tg_id == tg_id))


async def get_student(student_id: int) -> Student | None:
    async with async_session() as session:
        return await session.get(Student, student_id)


async def find_student_by_topic(topic_id: int) -> Student | None:
    async with async_session() as session:
        return await session.scalar(select(Student).where(Student.topic_id == topic_id))


async def list_students(page: int, size: int) -> tuple[list[Student], int, int, int]:
    '''Страница учеников (новые сверху). Возвращает (ученики, номер страницы, страниц, всего).'''
    async with async_session() as session:
        total = await session.scalar(select(func.count(Student.id))) or 0
        pages = max(1, math.ceil(total / size))
        page = max(0, min(page, pages - 1))
        rows = await session.scalars(
            select(Student).order_by(Student.id.desc()).offset(page * size).limit(size)
        )
        return list(rows.all()), page, pages, total


async def forget_topic(tg_id: int) -> None:
    '''Сбрасывает топик, если его удалили в группе: при следующем сообщении создастся новый.'''
    async with async_session() as session:
        student = await session.scalar(select(Student).where(Student.tg_id == tg_id))
        if student is not None:
            student.topic_id = None
            await session.commit()


async def ensure_topic(bot: Bot, student: Student) -> int | None:
    '''Личный топик ученика. Если создать нельзя, возвращает None и не падает.'''
    try:
        return await ensure_student_topic(bot, student.tg_id, student.full_name or 'Ученик')
    except Exception as exc:
        logger.warning('Топик ученика %s недоступен, дублирование пропущено: %s',
                       student.tg_id, type(exc).__name__)
        return None


async def register_student(bot: Bot, tg_id: int, full_name: str,
                           username: str | None) -> Student | None:
    async with async_session() as session:
        session.add(Student(tg_id=tg_id, full_name=full_name, username=username))
        await session.commit()

    student = await find_student(tg_id)
    if student is not None:
        await ensure_topic(bot, student)
    return await find_student(tg_id)


async def _send_to_topic(bot: Bot, student: Student, topic_id: int | None, send) -> list[int]:
    '''Отправляет в топик и возвращает ID отправленного сообщения (или пустой список).'''
    if not topic_id:
        return []
    try:
        sent = await send(topic_id)
    except TelegramBadRequest as exc:
        # В лог только тип ошибки: текст Telegram может содержать фрагменты запроса
        logger.warning('Не удалось отправить в топик ученика %s: %s',
                       student.tg_id, type(exc).__name__)
        if 'thread' in str(exc).lower():
            # Топик удалили вручную: сбрасываем, чтобы создать новый при следующем сообщении
            await forget_topic(student.tg_id)
        return []
    except Exception as exc:
        logger.warning('Ошибка дублирования для ученика %s: %s', student.tg_id, type(exc).__name__)
        return []
    return [sent.message_id]


async def mirror_text(bot: Bot, student: Student, topic_id: int | None, text: str) -> list[int]:
    return await _send_to_topic(
        bot, student, topic_id,
        lambda tid: bot.send_message(config.GROUP_ID, cut_text(text), message_thread_id=tid),
    )


async def mirror_voice(bot: Bot, student: Student, topic_id: int | None,
                       file_id: str, caption: str) -> list[int]:
    return await _send_to_topic(
        bot, student, topic_id,
        lambda tid: bot.send_voice(
            config.GROUP_ID, file_id,
            caption=cut_text(caption, CAPTION_LIMIT),
            message_thread_id=tid,
        ),
    )


async def mirror_exchange(bot: Bot, student: Student, topic_id: int | None,
                          user_text: str, reply: str) -> list[int]:
    name = student.full_name or 'Ученик'
    ids = await mirror_text(bot, student, topic_id, f'{name}:\n{user_text}')
    ids += await mirror_text(bot, student, topic_id, f'Ассистент:\n{reply}')
    return ids


async def _delete_topic(bot: Bot, topic_id: int) -> str:
    try:
        await bot.delete_forum_topic(chat_id=config.GROUP_ID, message_thread_id=topic_id)
    except TelegramAPIError as exc:
        logger.warning('Топик ученика не удалён: %s', type(exc).__name__)
        return 'Топик в группе не удалён: Telegram не дал это сделать. Удалите его вручную.'
    return 'Топик в группе удалён.'


@dataclass(frozen=True)
class DeleteResult:
    name: str
    topic_note: str


async def delete_student(bot: Bot, student_id: int, delete_topic: bool) -> DeleteResult | None:
    '''Полное удаление ученика и его данных. None, если ученик не найден.

    Порядок: открытый диалог отменяется, затем удаляются строки в порядке внешних ключей
    (topic_messages, chat_messages, attempts, dialog_sessions, students) в одной транзакции.
    Топик в группе удаляется после базы: ошибка Telegram уже не откатывает удаление.
    '''
    student = await get_student(student_id)
    if student is None:
        return None
    name = student.full_name or 'Ученик'

    async with async_session() as db:
        open_ids = list((await db.scalars(
            select(DialogSession.id).where(
                DialogSession.student_id == student.id,
                DialogSession.status.in_(OPEN_STATUSES),
            )
        )).all())
    for session_id in open_ids:
        await cancel_session(session_id)
        await topic_history.drop_session_messages(bot, session_id)

    if student.topic_id and not delete_topic:
        await screen.clear(bot, config.GROUP_ID, student.topic_id)

    async with async_session() as db:
        await db.execute(delete(TopicMessage).where(TopicMessage.student_id == student.id))
        await db.execute(delete(ChatMessage).where(ChatMessage.student_id == student.id))
        await db.execute(delete(Attempt).where(Attempt.student_id == student.id))
        await db.execute(delete(DialogSession).where(DialogSession.student_id == student.id))
        await db.execute(delete(Student).where(Student.id == student.id))
        await db.commit()

    # Исправлено: раньше вызов не ожидался, и список сообщений ученика не очищался
    await chat_cleanup.forget(student.tg_id)

    if not student.topic_id:
        topic_note = 'Топика в группе не было.'
    elif delete_topic:
        topic_note = await _delete_topic(bot, student.topic_id)
    else:
        topic_note = 'Топик в группе сохранён. Если он не нужен, удалите его вручную.'
    return DeleteResult(name=name, topic_note=topic_note)

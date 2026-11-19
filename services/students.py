import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select

from core.config import config
from database.engine import async_session
from database.models import Student
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


async def forget_topic(tg_id: int) -> None:
    '''Сбрасывает топик, если его удалили в группе: при следующем сообщении создастся новый.'''
    async with async_session() as session:
        student = await session.scalar(select(Student).where(Student.tg_id == tg_id))
        if student is not None:
            student.topic_id = None
            await session.commit()


async def ensure_topic(bot: Bot, student: Student) -> int | None:
    '''Личный топик ученика. Если создать нельзя (нет прав), возвращает None и не падает.'''
    try:
        return await ensure_student_topic(bot, student.tg_id, student.full_name or 'Ученик')
    except Exception as exc:
        logger.warning('Топик ученика %s недоступен, дублирование пропущено: %s',
                       student.tg_id, type(exc).__name__)
        return None


async def register_student(bot: Bot, tg_id: int, full_name: str,
                           username: str | None) -> Student | None:
    '''Сохраняет ученика и пытается создать его топик. Ошибка топика регистрацию не ломает.'''
    async with async_session() as session:
        session.add(Student(tg_id=tg_id, full_name=full_name, username=username))
        await session.commit()

    student = await find_student(tg_id)
    if student is not None:
        await ensure_topic(bot, student)
    return await find_student(tg_id)


async def _send_to_topic(bot: Bot, student: Student, topic_id: int | None, send) -> None:
    '''Отправка в топик. Любая ошибка логируется и не мешает ответу ученику.'''
    if not topic_id:
        return
    try:
        await send(topic_id)
    except TelegramBadRequest as exc:
        logger.warning('Не удалось отправить в топик ученика %s: %s', student.tg_id, exc)
        if 'thread' in str(exc).lower():
            # Топик удалили вручную: сбрасываем, чтобы создать новый при следующем сообщении.
            await forget_topic(student.tg_id)
    except Exception as exc:
        logger.warning('Ошибка дублирования для ученика %s: %s', student.tg_id, type(exc).__name__)


async def mirror_text(bot: Bot, student: Student, topic_id: int | None, text: str) -> None:
    await _send_to_topic(
        bot, student, topic_id,
        lambda tid: bot.send_message(config.GROUP_ID, cut_text(text), message_thread_id=tid),
    )


async def mirror_voice(bot: Bot, student: Student, topic_id: int | None,
                       file_id: str, caption: str) -> None:
    await _send_to_topic(
        bot, student, topic_id,
        lambda tid: bot.send_voice(
            config.GROUP_ID, file_id,
            caption=cut_text(caption, CAPTION_LIMIT),
            message_thread_id=tid,
        ),
    )


async def mirror_exchange(bot: Bot, student: Student, topic_id: int | None,
                          user_text: str, reply: str) -> None:
    '''Дублирует пару «вопрос ученика — ответ ассистента» в его топик.'''
    name = student.full_name or 'Ученик'
    await mirror_text(bot, student, topic_id, f'👤 {name}:\n{user_text}')
    await mirror_text(bot, student, topic_id, f'🤖 Ассистент:\n{reply}')

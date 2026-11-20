'''История диалогов в личном топике ученика.

Сообщения диалога пишутся в топик в реальном времени и запоминаются в topic_messages.
Когда диалог закрыт (graded или cancelled с ответами), эти сообщения удаляются,
а вместо них публикуется меню: одна кнопка на диалог. Меню и история строятся из базы,
поэтому не зависят от того, что осталось в чате Telegram.
'''
import logging
import math
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import delete, func, select

from core.config import config
from database.engine import async_session
from database.models import Attempt, ChatMessage, DialogSession, Student, TopicMessage
from services import screen
from services.dialogs import STATUS_CANCELLED, STATUS_GRADED, get_session

logger = logging.getLogger(__name__)

# 8 кнопок и строка навигации укладываются в одно сообщение с запасом по лимиту Telegram
# и остаются читаемыми на телефоне. Каждая кнопка не длиннее 64 символов
PAGE_SIZE = 8
PUBLISHED = (STATUS_GRADED, STATUS_CANCELLED)
PART_LIMIT = 3000   # один фрагмент истории (сообщение ≤ 4096 символов с запасом)
CHUNK_LIMIT = 3500  # склейка фрагментов в одно сообщение

NO_REPORT_CANCELLED = 'Диалог прерван, поэтому оценка не выставлена.'
NO_REPORT_LEGACY = 'Итог недоступен: диалог был оценён до появления истории в топике.'


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:64], callback_data=data)


def _cut(text: str, limit: int = PART_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + '…'


def _date(value: datetime | None) -> str:
    return value.strftime('%d.%m') if value else '—'


def dialog_label(session: DialogSession, score: float | None) -> str:
    if session.status == STATUS_GRADED and score is not None:
        mark = f'оценка {int(score)}'
    else:
        mark = 'без оценки'
    return f'№{session.id} · {_date(session.created_at)} · задание №{session.task_id or "—"} · {mark}'


def _chunks(parts: list[str]) -> list[str]:
    '''Склеивает фрагменты в сообщения, не превышая CHUNK_LIMIT. Порядок сохраняется.'''
    chunks: list[str] = []
    current = ''
    for part in parts:
        candidate = f'{current}\n\n{part}' if current else part
        if current and len(candidate) > CHUNK_LIMIT:
            chunks.append(current)
            current = part
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def _topic_of(student_id: int) -> int | None:
    async with async_session() as db:
        return await db.scalar(select(Student.topic_id).where(Student.id == student_id))


async def _publish(bot: Bot, topic_id: int, texts: list[str],
                   markup: InlineKeyboardMarkup, source_id: int | None) -> bool:
    try:
        await screen.show(bot, config.GROUP_ID, texts, markup,
                          source_id=source_id, thread_id=topic_id)
        return True
    except TelegramAPIError as exc:
        # Топик могли удалить вручную: меню не публикуется, но бот не падает
        logger.warning('Не удалось опубликовать меню диалогов в топике: %s', type(exc).__name__)
        return False


async def remember(student_id: int, session_id: int, message_ids: list[int], kind: str) -> None:
    '''Запоминает ID сообщений топика, относящихся к диалогу.'''
    if not message_ids:
        return
    async with async_session() as db:
        db.add_all([
            TopicMessage(student_id=student_id, session_id=session_id,
                         message_id=message_id, kind=kind)
            for message_id in message_ids
        ])
        await db.commit()


async def drop_session_messages(bot: Bot, session_id: int) -> int:
    '''Удаляет сообщения диалога из топика и их записи в базе.

    Записи удаляются после попытки удалить сообщения: если бот остановился посередине,
    при следующем закрытии сообщения обработаются повторно. Ошибки Telegram не прерывают работу.
    '''
    async with async_session() as db:
        rows = (await db.scalars(
            select(TopicMessage).where(TopicMessage.session_id == session_id)
        )).all()
        ids = [row.message_id for row in rows]

    deleted = 0
    for message_id in ids:
        try:
            await bot.delete_message(config.GROUP_ID, message_id)
            deleted += 1
        except TelegramAPIError as exc:  # старше 48 часов, уже удалено, топик удалён
            logger.info('Сообщение диалога не удалено из топика: %s', type(exc).__name__)

    async with async_session() as db:
        await db.execute(delete(TopicMessage).where(TopicMessage.session_id == session_id))
        await db.commit()
    return deleted


async def list_page(student_id: int, page: int) -> tuple[list[tuple[DialogSession, float | None]], int, int]:
    '''Страница закрытых диалогов (новые сверху), номер страницы и число страниц. Строится из базы.'''
    condition = (
        DialogSession.student_id == student_id,
        DialogSession.status.in_(PUBLISHED),
        DialogSession.replies_used > 0,
    )
    async with async_session() as db:
        total = await db.scalar(select(func.count(DialogSession.id)).where(*condition)) or 0
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(0, min(page, pages - 1))
        rows = (await db.execute(
            select(DialogSession, Attempt.score)
            .outerjoin(Attempt, Attempt.session_id == DialogSession.id)
            .where(*condition)
            .order_by(DialogSession.id.desc())
            .offset(page * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )).all()
    return [(row[0], row[1]) for row in rows], page, pages


async def show_menu(bot: Bot, student_id: int, topic_id: int, page: int = 0,
                    source_id: int | None = None) -> bool:
    '''Публикует или обновляет меню диалогов. Старое меню заменяется через screen.show.'''
    items, page, pages = await list_page(student_id, page)
    rows = [[_btn(dialog_label(session, score), f'hist:open:{session.id}:{page}')]
            for session, score in items]
    nav = []
    if page > 0:
        nav.append(_btn('‹ Назад', f'hist:list:{page - 1}'))
    if page < pages - 1:
        nav.append(_btn('Дальше ›', f'hist:list:{page + 1}'))
    if nav:
        rows.append(nav)

    text = (
        'История диалогов\n\n'
        'Выберите диалог, чтобы открыть его историю и итог.\n'
        f'Страница {page + 1} из {pages}.'
    )
    return await _publish(bot, topic_id, [text], InlineKeyboardMarkup(inline_keyboard=rows), source_id)


async def show_history(bot: Bot, student_id: int, topic_id: int, session_id: int, page: int,
                       source_id: int | None = None) -> bool:
    '''История диалога: реплики из chat_messages и итог в конце, с кнопкой «Назад к списку».'''
    session = await get_session(session_id)
    if session is None or session.student_id != student_id or session.status not in PUBLISHED:
        return False

    async with async_session() as db:
        rows = (await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc())
        )).all()

    parts = [f'История диалога №{session.id} · {_date(session.created_at)} · '
             f'задание №{session.task_id or "—"}']
    for row in rows:
        speaker = 'Ученик' if row.role == 'user' else 'Ассистент'
        parts.append(f'{speaker}:\n{_cut(row.content)}')

    if session.report:
        summary = session.report
    elif session.status == STATUS_CANCELLED:
        summary = NO_REPORT_CANCELLED
    else:
        summary = NO_REPORT_LEGACY
    parts.append(_cut(summary))  # итог всегда последний: под ним кнопка «Назад»

    markup = InlineKeyboardMarkup(inline_keyboard=[[_btn('Назад к списку', f'hist:list:{page}')]])
    return await _publish(bot, topic_id, _chunks(parts), markup, source_id)


async def close_dialog(bot: Bot, student_id: int, session_id: int) -> None:
    '''Закрывает диалог в топике: удаляет его сообщения и публикует меню.

    Вызывается только после сохранения оценки (graded) или при отмене (cancelled).
    Диалог без ответов нейросети в меню не попадает.
    '''
    async with async_session() as db:
        session = await db.get(DialogSession, session_id)
    if session is None or session.status not in PUBLISHED:
        return

    await drop_session_messages(bot, session_id)
    if session.replies_used > 0:
        topic_id = await _topic_of(student_id)
        if topic_id:
            await show_menu(bot, student_id, topic_id)


async def reset_screen(bot: Bot, student_id: int) -> None:
    '''Убирает меню и историю из топика перед началом нового диалога.'''
    topic_id = await _topic_of(student_id)
    if topic_id:
        await screen.clear(bot, config.GROUP_ID, topic_id)

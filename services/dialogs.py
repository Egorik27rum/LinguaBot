'''Диалог ученика по заданию: сессия с лимитом ответов нейросети и итоговой оценкой.

Статусы:
- active: диалог идёт, сообщения ученика уходят в диалог;
- ended: лимит исчерпан или ученик завершил диалог, оценка ещё не сохранена (повтор через /finish);
- graded: оценка сохранена в attempts;
- cancelled: диалог прерван (смена задания, пустой диалог, удаление ученика).

Лимит, цель и режим копируются в сессию при старте, поэтому изменения настроек
не влияют на уже идущий диалог.
'''
import asyncio

from sqlalchemy import select

from database.engine import async_session
from database.models import Attempt, ChatMessage, DialogSession, utcnow
from services.settings import get_setting, set_setting

STATUS_ACTIVE = 'active'
STATUS_ENDED = 'ended'
STATUS_GRADED = 'graded'
STATUS_CANCELLED = 'cancelled'
OPEN_STATUSES = (STATUS_ACTIVE, STATUS_ENDED)

REPLY_LIMIT_KEY = 'dialog_reply_limit'
REPLY_LIMIT_MIN = 1
REPLY_LIMIT_MAX = 20
DEFAULT_REPLY_LIMIT = 8  # приветствие, основная задача, уточнения и запас на исправления
REPLY_LIMIT_OPTIONS = (1, 3, 5, 8, 10, 15, 20)

_locks: dict[int, asyncio.Lock] = {}


def student_lock(student_id: int) -> asyncio.Lock:
    '''Один диалог — одна обработка за раз: защита от гонки двух быстрых сообщений.'''
    lock = _locks.get(student_id)
    if lock is None:
        lock = _locks[student_id] = asyncio.Lock()
    return lock


async def load_reply_limit() -> int:
    raw = (await get_setting(REPLY_LIMIT_KEY) or '').strip()
    if raw.isdigit() and REPLY_LIMIT_MIN <= int(raw) <= REPLY_LIMIT_MAX:
        return int(raw)
    return DEFAULT_REPLY_LIMIT


async def set_reply_limit(value: int) -> None:
    if not REPLY_LIMIT_MIN <= value <= REPLY_LIMIT_MAX:
        raise ValueError('лимит ответов вне диапазона 1–20')
    await set_setting(REPLY_LIMIT_KEY, str(value))


async def get_session(session_id: int) -> DialogSession | None:
    async with async_session() as session:
        return await session.get(DialogSession, session_id)


async def _find(student_id: int, statuses: tuple[str, ...]) -> DialogSession | None:
    async with async_session() as session:
        return await session.scalar(
            select(DialogSession)
            .where(DialogSession.student_id == student_id, DialogSession.status.in_(statuses))
            .order_by(DialogSession.id.desc())
            .limit(1)
        )


async def find_active_session(student_id: int) -> DialogSession | None:
    return await _find(student_id, (STATUS_ACTIVE,))


async def find_open_session(student_id: int) -> DialogSession | None:
    return await _find(student_id, OPEN_STATUSES)


async def open_session(student_id: int, *, task_id: int, goal_id: int | None,
                       goal_mode: str, reply_limit: int) -> DialogSession:
    async with async_session() as session:
        dialog = DialogSession(
            student_id=student_id,
            task_id=task_id,
            goal_id=goal_id,
            goal_mode=goal_mode,
            reply_limit=reply_limit,
            replies_used=0,
            status=STATUS_ACTIVE,
        )
        session.add(dialog)
        await session.commit()
        return dialog


async def record_turn(session_id: int, user_text: str, reply: str) -> DialogSession | None:
    '''Сохраняет ход диалога (сообщение ученика и ответ модели) и увеличивает счётчик.
    Возвращает None, если диалог уже не активен.
    '''
    async with async_session() as session:
        dialog = await session.get(DialogSession, session_id)
        if dialog is None or dialog.status != STATUS_ACTIVE:
            return None
        dialog.replies_used += 1
        session.add_all([
            ChatMessage(student_id=dialog.student_id, session_id=dialog.id,
                        role='user', content=user_text),
            ChatMessage(student_id=dialog.student_id, session_id=dialog.id,
                        role='assistant', content=reply),
        ])
        await session.commit()
        return dialog


async def load_dialog_messages(session_id: int) -> list[dict[str, str]]:
    async with async_session() as session:
        rows = (await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc())
        )).all()
    return [{'role': row.role, 'content': row.content} for row in rows]


async def mark_ended(session_id: int) -> bool:
    '''active -> ended. Возвращает False, если диалог уже не активен.'''
    async with async_session() as session:
        dialog = await session.get(DialogSession, session_id)
        if dialog is None or dialog.status != STATUS_ACTIVE:
            return False
        dialog.status = STATUS_ENDED
        dialog.finished_at = utcnow()
        await session.commit()
        return True


async def cancel_session(session_id: int) -> bool:
    async with async_session() as session:
        dialog = await session.get(DialogSession, session_id)
        if dialog is None or dialog.status not in OPEN_STATUSES:
            return False
        dialog.status = STATUS_CANCELLED
        dialog.finished_at = utcnow()
        await session.commit()
        return True


async def save_graded(session_id: int, student_id: int, task_id: int | None,
                      score: int, goal_result: str | None, feedback: str,
                      report: str | None = None) -> bool:
    '''ended -> graded, запись оценки в attempts и итог для истории в одной транзакции.
    Повторное сохранение возвращает False: защита от двойной оценки.
    '''
    async with async_session() as session:
        dialog = await session.get(DialogSession, session_id)
        if dialog is None or dialog.status != STATUS_ENDED:
            return False
        session.add(Attempt(
            student_id=student_id,
            task_id=task_id,
            session_id=session_id,
            score=float(score),
        ))
        dialog.status = STATUS_GRADED
        dialog.goal_result = goal_result
        dialog.feedback = feedback
        dialog.report = report
        dialog.finished_at = dialog.finished_at or utcnow()
        await session.commit()
        return True

import io
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from database.engine import async_session
from database.models import ChatMessage, DialogSession, Student
from services.ai_settings import AiParams, load_ai_params
from services.dialogs import load_dialog_messages
from services.goals import GOAL_MODES, apply_goal_cap
from services.polza_client import PolzaClient
from services.settings import get_setting
from services.tasks import get_active_task

logger = logging.getLogger(__name__)

# Режим диалога по заданию: без инструкций про оценку, только ведение разговора
DIALOG_RULES = (
    'Сейчас ученик выполняет задание в диалоге. Веди разговор: задавай уточняющие вопросы, '
    'предлагай небольшие дополнительные задания, проси переформулировать мысль. '
    'Отвечай коротко, по одному-два вопроса за раз.'
)


@dataclass(frozen=True)
class TeacherBrief:
    api_key: str | None
    context: str
    task_id: int | None
    task_title: str | None
    task_content: str | None
    model_text: str | None
    model_speech: str | None
    ai: AiParams


async def load_brief() -> TeacherBrief:
    '''Читает настройки и активное задание заново, чтобы изменения применялись сразу.'''
    api_key = await get_setting('polza_api_key')
    context = (await get_setting('teacher_context') or '').strip()
    model_text = (await get_setting('model_text') or '').strip() or None
    model_speech = (await get_setting('model_speech') or '').strip() or None
    task = await get_active_task()
    return TeacherBrief(
        api_key=api_key or None,
        context=context,
        task_id=task.id if task else None,
        task_title=task.title if task else None,
        task_content=task.content if task else None,
        model_text=model_text,
        model_speech=model_speech,
        ai=await load_ai_params(),
    )


def build_system_prompt(brief: TeacherBrief, dialog: bool = False) -> str:
    parts = [brief.ai.instructions()]
    if dialog:
        parts.append(DIALOG_RULES)
    if brief.context:
        parts.append(f'Требования преподавателя:\n{brief.context}')
    if brief.task_content:
        parts.append(f'Текущее задание «{brief.task_title or "Задание"}»:\n{brief.task_content}')
    return '\n\n'.join(parts)


async def load_history(student_id: int, limit: int) -> list[dict[str, str]]:
    '''История свободного чата. Сообщения диалогов по заданиям сюда не попадают.'''
    if limit <= 0:
        return []
    async with async_session() as session:
        rows = (await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.student_id == student_id, ChatMessage.session_id.is_(None))
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )).all()
    return [{'role': row.role, 'content': row.content} for row in reversed(rows)]


async def ask_tutor(student: Student, text: str, brief: TeacherBrief) -> str | None:
    '''Свободный чат с историей. Возвращает ответ или None при ошибке Polza.ai.'''
    history = await load_history(student.id, brief.ai.history_limit)
    messages = [
        {'role': 'system', 'content': build_system_prompt(brief)},
        *history,
        {'role': 'user', 'content': text},
    ]
    return await PolzaClient().chat(
        brief.api_key or '', messages,
        model=brief.model_text,
        temperature=brief.ai.temperature,
        max_tokens=brief.ai.max_tokens,
    )


async def ask_dialog(session: DialogSession, text: str, brief: TeacherBrief) -> str | None:
    '''Ход диалога по заданию: вся история сессии и без инструкций по оценке.'''
    history = await load_dialog_messages(session.id)
    messages = [
        {'role': 'system', 'content': build_system_prompt(brief, dialog=True)},
        *history,
        {'role': 'user', 'content': text},
    ]
    return await PolzaClient().chat(
        brief.api_key or '', messages,
        model=brief.model_text,
        temperature=brief.ai.temperature,
        max_tokens=brief.ai.max_tokens,
    )


async def save_exchange(student_id: int, user_text: str, reply: str) -> None:
    async with async_session() as session:
        session.add_all([
            ChatMessage(student_id=student_id, role='user', content=user_text),
            ChatMessage(student_id=student_id, role='assistant', content=reply),
        ])
        await session.commit()


async def transcribe_voice(bot: Bot, file_id: str, brief: TeacherBrief) -> str | None:
    '''Только распознавание речи (STT). Оценка произношения не выполняется.'''
    buf = io.BytesIO()
    try:
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination=buf)
    except TelegramAPIError as exc:
        logger.warning('Не удалось скачать голосовое сообщение: %s', type(exc).__name__)
        return None
    return await PolzaClient().transcribe(
        brief.api_key or '', buf.getvalue(), model=brief.model_speech,
    )


async def grade_text(brief: TeacherBrief, task_content: str, dialog: list[dict[str, str]],
                     goal_text: str | None, goal_mode: str | None) -> dict | None:
    '''Итоговая оценка диалога (1–5) с учётом цели и режима.

    Возвращает dict: score (итоговая), raw_score (до ограничения режимом), capped,
    feedback, goal_achieved, goal_done, goal_missed. None, если Polza.ai недоступен
    или ответ не прошёл проверку формата.
    '''
    mode = goal_mode if goal_text and goal_mode in GOAL_MODES else None
    criteria = GOAL_MODES[mode].criteria if mode else None
    result = await PolzaClient().grade_dialog(
        brief.api_key or '',
        dialog,
        task_content or '',
        brief.context,
        goal_text=goal_text if mode else None,
        goal_criteria=criteria,
        model=brief.model_text,
    )
    if result is None:
        return None
    raw = result['score']
    final = apply_goal_cap(raw, result['goal_achieved'], mode or '')
    return {**result, 'raw_score': raw, 'score': final, 'capped': final < raw, 'mode': mode}

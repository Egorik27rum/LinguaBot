import io
from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy import select

from database.engine import async_session
from database.models import Attempt, ChatMessage, Student, Task
from services.polza_client import PolzaClient
from services.settings import get_setting

HISTORY_LIMIT = 20  # сколько последних реплик передаём модели

BASE_PROMPT = (
    'Ты дружелюбный ассистент по изучению английского языка. '
    'Отвечай понятно и кратко, мягко исправляй ошибки и объясняй правило. '
    'Опирайся на задание и требования преподавателя, если они заданы. '
    'Отвечай на языке, на котором пишет ученик, если он не просит иначе.'
)


@dataclass(frozen=True)
class TeacherBrief:
    '''Состояние, которое преподаватель задал в основном боте.'''
    api_key: str | None
    context: str
    task_id: int | None
    task_title: str | None
    task_content: str | None
    model_text: str | None
    model_speech: str | None


async def load_brief() -> TeacherBrief:
    '''Читает настройки и последнее задание заново, чтобы изменения применялись сразу.'''
    api_key = await get_setting('polza_api_key')
    context = (await get_setting('teacher_context') or '').strip()
    model_text = (await get_setting('model_text') or '').strip() or None
    model_speech = (await get_setting('model_speech') or '').strip() or None
    async with async_session() as session:
        task = await session.scalar(select(Task).order_by(Task.id.desc()))
    return TeacherBrief(
        api_key=api_key or None,
        context=context,
        task_id=task.id if task else None,
        task_title=task.title if task else None,
        task_content=task.content if task else None,
        model_text=model_text,
        model_speech=model_speech,
    )


def build_system_prompt(brief: TeacherBrief) -> str:
    parts = [BASE_PROMPT]
    if brief.context:
        parts.append(f'Требования преподавателя:\n{brief.context}')
    if brief.task_content:
        parts.append(f'Текущее задание «{brief.task_title or "Задание"}»:\n{brief.task_content}')
    return '\n\n'.join(parts)


async def load_history(student_id: int) -> list[dict[str, str]]:
    async with async_session() as session:
        rows = (await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.student_id == student_id)
            .order_by(ChatMessage.id.desc())
            .limit(HISTORY_LIMIT)
        )).all()
    return [{'role': row.role, 'content': row.content} for row in reversed(rows)]


async def ask_tutor(student: Student, text: str, brief: TeacherBrief) -> str | None:
    '''Запрос к Polza.ai с историей диалога. Возвращает ответ или None при ошибке.'''
    history = await load_history(student.id)
    messages = [
        {'role': 'system', 'content': build_system_prompt(brief)},
        *history,
        {'role': 'user', 'content': text},
    ]
    return await PolzaClient().chat(brief.api_key or '', messages, model=brief.model_text)


async def save_exchange(student_id: int, user_text: str, reply: str) -> None:
    async with async_session() as session:
        session.add_all([
            ChatMessage(student_id=student_id, role='user', content=user_text),
            ChatMessage(student_id=student_id, role='assistant', content=reply),
        ])
        await session.commit()


async def analyze_voice(bot: Bot, file_id: str, brief: TeacherBrief, reference: str) -> dict | None:
    '''Скачивает голосовое и отправляет в Polza.ai (расшифровка, при наличии эталона — оценка).'''
    buf = io.BytesIO()
    file = await bot.get_file(file_id)
    await bot.download_file(file.file_path, destination=buf)
    return await PolzaClient().analyze_speech(
        brief.api_key or '', buf.getvalue(), reference, brief.context,
        model=brief.model_speech,
    )


def transcription_of(result: dict | None) -> str | None:
    if not result:
        return None
    text = str(result.get('transcription') or '').strip()
    return text or None


async def grade_text(brief: TeacherBrief, text: str) -> dict | None:
    '''Оценка текстового ответа на текущее задание.'''
    return await PolzaClient().analyze_text(
        brief.api_key or '', text, brief.task_content or '', brief.context,
        model=brief.model_text,
    )


async def save_attempt(student_id: int, task_id: int | None,
                       score: float | None, transcription: str | None) -> None:
    async with async_session() as session:
        session.add(Attempt(
            student_id=student_id,
            task_id=task_id,
            score=score,
            transcription=transcription,
        ))
        await session.commit()

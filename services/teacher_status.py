'''Статус для экранов преподавателя: бот, ключ, контекст, задание, роль, модели, цель.

Источник данных для текста «Статус» в боте (раньше собирался в teacher_settings.status_text).
Сборка данных и текст разделены, чтобы тот же набор данных можно было отдать и в API.
'''
from __future__ import annotations

from dataclasses import dataclass

from core.bot_status import BotStatus, get_status
from database.models import Goal, Task
from services.ai_settings import load_ai_params
from services.dialogs import load_reply_limit
from services.goals import GOAL_MODES, get_active_goal, load_goal_mode
from services.polza_key import mask_key
from services.settings import get_setting
from services.tasks import get_active_task
from services.teacher_context import CONTEXT_KEY


@dataclass(frozen=True)
class TeacherStatus:
    main_bot: BotStatus | None
    key_set: bool
    key_masked: str | None
    context_set: bool
    active_task: Task | None
    role_name: str
    model_text: str | None
    model_speech: str | None
    reply_limit: int
    goal_mode_title: str
    active_goal: Goal | None


async def collect_status() -> TeacherStatus:
    key = await get_setting('polza_api_key')
    context = await get_setting(CONTEXT_KEY)
    ai = await load_ai_params()
    mode = await load_goal_mode()
    return TeacherStatus(
        main_bot=get_status('main'),
        key_set=bool(key),
        key_masked=mask_key(key),
        context_set=bool(context),
        active_task=await get_active_task(),
        role_name=ai.role_name,
        model_text=(await get_setting('model_text')) or None,
        model_speech=(await get_setting('model_speech')) or None,
        reply_limit=await load_reply_limit(),
        goal_mode_title=GOAL_MODES[mode].title,
        active_goal=await get_active_goal(),
    )


def render_settings_status(status: TeacherStatus) -> str:
    '''Текст экрана «Статус» в боте. Совпадает с прежним status_text.'''
    key_state = 'задан' if status.key_set else 'не задан'
    ctx_state = 'задан' if status.context_set else 'не задан'
    task = status.active_task
    task_state = f'№{task.id} «{task.title}»' if task else 'нет'
    goal_state = f'№{status.active_goal.id}' if status.active_goal else 'не задана'
    return (
        'Статус бота\n\n'
        f'Ключ Polza.ai: {key_state}\n'
        f'Контекст для оценки: {ctx_state}\n'
        f'Активное задание: {task_state}\n'
        f'Роль ассистента: {status.role_name}\n'
        f'Модель анализа текста: {status.model_text or "по умолчанию"}\n'
        f'Модель анализа голоса: {status.model_speech or "по умолчанию"}\n'
        f'Ответов нейросети в диалоге: {status.reply_limit}\n'
        f'Режим проверки цели: {status.goal_mode_title}\n'
        f'Активная цель: {goal_state}'
    )

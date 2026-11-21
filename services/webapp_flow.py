'''Сценарии ученика для Mini App.

Правила повторяют бота (plugins/student_bot.py): статусы диалога, лимит ответов, оценка,
дублирование в топик. Очистка чата Telegram здесь не нужна: экран ведёт фронтенд.
'''
from __future__ import annotations

import json
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from core.config import config
from database.models import DialogSession, Student
from services import topic_history
from services.dialogs import (
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_ENDED,
    STATUS_GRADED,
    cancel_session,
    find_active_session,
    find_open_session,
    get_session,
    load_dialog_messages,
    load_reply_limit,
    mark_ended,
    open_session,
    record_turn,
    save_graded,
    student_lock,
)
from services.goals import GOAL_MODES, get_active_goal, get_goal, load_goal_mode
from services.reports import build_report
from services.settings import get_setting
from services.students import (
    cut_text,
    ensure_topic,
    find_student,
    mirror_exchange,
    mirror_text,
    register_student,
)
from services.tasks import get_task
from services.tutor import (
    TeacherBrief,
    ask_dialog,
    ask_tutor,
    grade_text,
    load_brief,
    load_history,
    save_exchange,
)

logger = logging.getLogger(__name__)

NAME_MIN = 2
NAME_MAX = 64
MAX_INPUT = 2000
CHAT_HISTORY_LIMIT = 200
EMPTY_DIALOG = 'В диалоге не было ответов, поэтому оценка не выставлена.'
NO_REPORT_CANCELLED = 'Диалог прерван, поэтому оценка не выставлена.'
NO_REPORT_LEGACY = 'Итог недоступен: диалог был оценён до появления истории.'


class FlowError(Exception):
    '''Ошибка сценария с текстом для ученика. status — HTTP-код ответа.'''

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


async def require_student(tg_id: int) -> Student:
    student = await find_student(tg_id)
    if student is None:
        raise FlowError('Сначала зарегистрируйтесь.', status=403)
    return student


def _require_key(brief: TeacherBrief) -> None:
    if not brief.api_key:
        raise FlowError('Преподаватель ещё не подключил ключ Polza.ai.', status=503)


def _serialize_dialog(session: DialogSession) -> dict:
    return {
        'id': session.id,
        'status': session.status,
        'task_id': session.task_id,
        'replies_used': session.replies_used,
        'reply_limit': session.reply_limit,
    }


async def get_state(tg_id: int) -> dict:
    '''Всё, что нужно главному экрану: регистрация, задание, роль, диалог, лимит и цель.'''
    student = await find_student(tg_id)
    brief = await load_brief()
    dialog = await find_open_session(student.id) if student else None
    goal = await get_active_goal()
    mode = await load_goal_mode()
    task = None
    if brief.task_id:
        task = {
            'id': brief.task_id,
            'title': brief.task_title or 'Задание',
            'content': brief.task_content or '',
        }
    return {
        'registered': student is not None,
        'full_name': student.full_name if student else None,
        'ready': bool(brief.api_key),
        'context': brief.context,
        'task': task,
        'role': {'name': brief.ai.role_name, 'text': brief.ai.role_text},
        'goal': {'text': goal.text, 'mode': GOAL_MODES[mode].title} if goal else None,
        'reply_limit': await load_reply_limit(),
        'dialog': _serialize_dialog(dialog) if dialog else None,
    }


async def register(bot: Bot, tg_id: int, username: str | None, raw_name: object) -> None:
    name = ' '.join(str(raw_name or '').split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise FlowError(f'Имя должно быть от {NAME_MIN} до {NAME_MAX} символов.')
    if await find_student(tg_id):
        raise FlowError('Вы уже зарегистрированы.', status=409)
    await register_student(bot, tg_id, name, username)


async def start_dialog(bot: Bot, tg_id: int) -> str | None:
    '''Открывает диалог по активному заданию. Возвращает пояснение, если прежний диалог отменён.'''
    student = await require_student(tg_id)
    brief = await load_brief()
    _require_key(brief)
    if brief.task_id is None:
        raise FlowError('Активного задания сейчас нет.', status=409)

    notice = None
    async with student_lock(student.id):
        open_now = await find_open_session(student.id)
        if open_now and open_now.status == STATUS_ENDED:
            raise FlowError(
                'Предыдущий диалог завершён и ждёт оценки. Нажмите «Завершить диалог».', status=409,
            )
        if open_now and open_now.task_id == brief.task_id:
            raise FlowError('Диалог по этому заданию уже идёт.', status=409)

        # Сначала убираем старое меню истории, затем отмена может опубликовать новое
        await topic_history.reset_screen(bot, student.id)
        if open_now:
            await cancel_session(open_now.id)
            await topic_history.close_dialog(bot, student.id, open_now.id)
            notice = (f'Диалог по заданию №{open_now.task_id} отменён: активное задание изменилось. '
                      'Оценка не выставлена.')

        goal = await get_active_goal()
        mode = await load_goal_mode()
        limit = await load_reply_limit()
        await open_session(
            student.id,
            task_id=brief.task_id,
            goal_id=goal.id if goal else None,
            goal_mode=mode,
            reply_limit=limit,
        )
    return notice


async def handle_message(bot: Bot, tg_id: int, raw_text: object) -> dict:
    '''Сообщение ученика: ход диалога, если он открыт, иначе свободный чат.'''
    text = str(raw_text or '').strip()[:MAX_INPUT]
    if not text:
        raise FlowError('Сообщение пустое.')
    student = await require_student(tg_id)
    brief = await load_brief()
    _require_key(brief)
    if await find_active_session(student.id):
        return await _dialog_turn(bot, student, brief, text)
    return await _free_turn(bot, student, brief, text)


async def _free_turn(bot: Bot, student: Student, brief: TeacherBrief, text: str) -> dict:
    reply = await ask_tutor(student, text, brief)
    if not reply:
        raise FlowError('Не удалось получить ответ, попробуйте чуть позже.', status=502)
    await save_exchange(student.id, text, reply)
    topic_id = await ensure_topic(bot, student)
    await mirror_exchange(bot, student, topic_id, text, reply)
    return {'mode': 'chat', 'reply': reply, 'finished': False, 'report': None, 'notice': None}


async def _dialog_turn(bot: Bot, student: Student, brief: TeacherBrief, text: str) -> dict:
    async with student_lock(student.id):
        session = await find_active_session(student.id)
        if session is None:
            raise FlowError('Диалог уже завершён. Чтобы начать новый, нажмите «Ответить на задание».',
                            status=409)
        if session.task_id != brief.task_id:
            await cancel_session(session.id)
            await topic_history.close_dialog(bot, student.id, session.id)
            raise FlowError(
                f'Диалог по заданию №{session.task_id} отменён: активное задание изменилось. '
                'Оценка не выставлена.', status=409,
            )

        reply = await ask_dialog(session, text, brief)
        if not reply:
            raise FlowError('Не удалось получить ответ нейросети. Сообщение не сохранено: '
                            'отправьте его ещё раз.', status=502)
        updated = await record_turn(session.id, text, reply)
        if updated is None:
            raise FlowError('Диалог уже завершён.', status=409)

        topic_id = await ensure_topic(bot, student)
        text_ids = await mirror_exchange(bot, student, topic_id, text, reply)
        await topic_history.remember(student.id, updated.id, text_ids, 'text')

        result = {
            'mode': 'dialog',
            'reply': reply,
            'replies_used': updated.replies_used,
            'reply_limit': updated.reply_limit,
            'finished': False,
            'report': None,
            'notice': None,
        }
        if updated.replies_used >= updated.reply_limit:
            # Лимит исчерпан: диалог завершается и сразу выставляется оценка
            await mark_ended(updated.id)
            result['finished'] = True
            try:
                result['report'] = await conclude(bot, student, updated.id)
            except FlowError as exc:
                # Сообщение уже сохранено, поэтому ошибка оценки не отменяет ход
                result['notice'] = str(exc)
        return result


async def conclude(bot: Bot, student: Student, session_id: int) -> str | None:
    '''Итоговая оценка. Вызывается под блокировкой ученика.

    Топик закрывается только после сохранения оценки. Если Polza.ai недоступен,
    диалог остаётся в статусе ended и повторяется через finish.
    '''
    session = await get_session(session_id)
    if session is None:
        return None
    brief = await load_brief()
    if not brief.api_key:
        raise FlowError('Ключ Polza.ai не подключён. Диалог сохранён: повторите завершение позже.',
                        status=503)

    task = await get_task(session.task_id) if session.task_id else None
    goal = await get_goal(session.goal_id) if session.goal_id else None
    messages = await load_dialog_messages(session.id)
    result = await grade_text(
        brief,
        task.content if task else '',
        messages,
        goal.text if goal else None,
        session.goal_mode if goal else None,
    )
    if result is None:
        raise FlowError('Не удалось подвести итог: нейросеть недоступна. '
                        'Диалог сохранён, повторите позже.', status=502)

    goal_result = None
    if goal is not None:
        goal_result = json.dumps({
            'achieved': result['goal_achieved'],
            'done': result['goal_done'],
            'missed': result['goal_missed'],
        }, ensure_ascii=False)

    title = task.title if task else 'Задание'
    report = build_report(title, result, goal, session.goal_mode if goal else None)
    saved = await save_graded(session.id, student.id, session.task_id,
                              result['score'], goal_result, result['feedback'], report=report)
    if not saved:
        raise FlowError('Оценка по этому диалогу уже выставлена.', status=409)

    topic_id = await ensure_topic(bot, student)
    report_ids = await mirror_text(bot, student, topic_id, report)
    await topic_history.remember(student.id, session.id, report_ids, 'report')
    await mirror_to_teacher(bot, student, report)
    await topic_history.close_dialog(bot, student.id, session.id)
    return report


async def mirror_to_teacher(bot: Bot, student: Student, report: str) -> None:
    raw = (await get_setting('teacher_topic_id') or '').strip()
    if not raw.isdigit():
        return
    text = f'{student.full_name or "Ученик"}:\n{report}'
    try:
        await bot.send_message(config.GROUP_ID, cut_text(text), message_thread_id=int(raw))
    except TelegramAPIError as exc:
        logger.warning('Не удалось отправить итог в топик преподавателя: %s', type(exc).__name__)


async def finish_dialog(bot: Bot, tg_id: int) -> dict:
    '''Досрочное завершение диалога и выставление оценки.'''
    student = await require_student(tg_id)
    async with student_lock(student.id):
        session = await find_open_session(student.id)
        if session is None:
            raise FlowError('Открытого диалога сейчас нет. Начните его кнопкой «Ответить на задание».')
        if session.status == STATUS_ACTIVE:
            if session.replies_used == 0:
                await cancel_session(session.id)
                await topic_history.close_dialog(bot, student.id, session.id)
                return {'report': None, 'notice': EMPTY_DIALOG}
            await mark_ended(session.id)
        report = await conclude(bot, student, session.id)
    return {'report': report, 'notice': None}


async def get_chat(tg_id: int) -> dict:
    '''Переписка для экрана чата: диалог по заданию, если он активен, иначе свободный чат.'''
    student = await require_student(tg_id)
    brief = await load_brief()
    active = await find_active_session(student.id)
    if active:
        messages = await load_dialog_messages(active.id)
        mode = 'dialog'
    else:
        messages = await load_history(student.id, CHAT_HISTORY_LIMIT)
        mode = 'chat'
    return {'mode': mode, 'messages': messages, 'ready': bool(brief.api_key)}


async def list_dialogs(tg_id: int, page: int) -> dict:
    student = await require_student(tg_id)
    items, page, pages = await topic_history.list_page(student.id, page)
    return {
        'page': page,
        'pages': pages,
        'items': [{'id': s.id, 'label': topic_history.dialog_label(s, score)} for s, score in items],
    }


async def dialog_detail(tg_id: int, session_id: int) -> dict:
    student = await require_student(tg_id)
    session = await get_session(session_id)
    if (session is None or session.student_id != student.id
            or session.status not in (STATUS_GRADED, STATUS_CANCELLED)):
        raise FlowError('Диалог не найден.', status=404)

    messages = await load_dialog_messages(session.id)
    if session.report:
        report = session.report
    elif session.status == STATUS_CANCELLED:
        report = NO_REPORT_CANCELLED
    else:
        report = NO_REPORT_LEGACY
    return {
        'id': session.id,
        'label': f'Диалог №{session.id}',
        'messages': messages,
        'report': report,
    }

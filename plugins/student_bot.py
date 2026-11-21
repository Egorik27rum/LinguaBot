import json
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from database.models import Goal, Student
from services import chat_cleanup, topic_history
from services.dialogs import (
    STATUS_ACTIVE,
    STATUS_ENDED,
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
    mirror_voice,
    register_student,
)
from services.tasks import get_task
from services.tutor import (
    TeacherBrief,
    ask_dialog,
    ask_tutor,
    grade_text,
    load_brief,
    save_exchange,
    transcribe_voice,
)

logger = logging.getLogger(__name__)

ROLES = {'student'}
PRIORITY = 30

NAME_MIN = 2
NAME_MAX = 64
MAX_INPUT = 2000
PRIVATE = F.chat.type == 'private'
EMPTY_DIALOG = 'В диалоге не было ответов, поэтому оценка не выставлена.'
NO_ACTIVE_TASK = 'Активного задания сейчас нет.'
APP_BUTTON_TEXT = 'Открыть LinguaBot'

INSTRUCTION = (
    'Инструкция\n\n'
    '1. Вопросы: пишите вопросы по английскому текстом или голосовым. '
    'Бот ответит и поможет разобраться с ошибками.\n'
    '2. Задание: нажмите «Текущее задание», чтобы увидеть условие и требования.\n'
    '3. Ответ: нажмите «Ответить на задание» или отправьте /answer. Пишите ответы текстом или голосом. '
    'Нейросеть отвечает и задаёт уточняющие вопросы.\n'
    '4. Завершение: диалог закончится, когда исчерпан лимит ответов нейросети. '
    'Досрочно — кнопка «Завершить диалог» или /finish. Затем бот выставит оценку по 5-балльной шкале.\n'
    '5. Роль: «Роль ассистента» покажет, в каком режиме сейчас работает нейросеть.\n'
    '6. Отмена: /cancel прерывает ввод регистрации. Открытый диалог от этого не прерывается.\n\n'
    'Ваши вопросы, ответы и оценки дублируются в личный топик в группе, который видит преподаватель. '
    'Когда диалог завершён, его сообщения в топике заменяются кнопкой с историей и итогом.'
)


class RegisterStates(StatesGroup):
    full_name = State()


def student_app_url() -> str | None:
    '''Адрес приложения ученика. Без HTTPS Telegram не откроет WebApp.'''
    url = config.WEBAPP_URL
    if not url or not url.startswith('https://'):
        return None
    return url.rstrip('/') + '/'


def student_menu(app_url: str | None = None) -> InlineKeyboardMarkup:
    '''Меню ученика. Кнопка приложения появляется только при HTTPS WEBAPP_URL.'''
    kb = InlineKeyboardBuilder()
    if app_url:
        kb.row(InlineKeyboardButton(text=APP_BUTTON_TEXT, web_app=WebAppInfo(url=app_url)))
    kb.button(text='Инструкция', callback_data='stu:help')
    kb.button(text='Текущее задание', callback_data='stu:task')
    kb.button(text='Роль ассистента', callback_data='stu:role')
    kb.button(text='Ответить на задание', callback_data='stu:answer')
    kb.button(text='Завершить диалог', callback_data='stu:finish')
    kb.adjust(1)
    return kb.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    '''Кнопка «Назад» для окон, которые открываются из меню ученика.'''
    kb = InlineKeyboardBuilder()
    kb.button(text='Назад', callback_data='stu:menu')
    return kb.as_markup()


def overview_text(brief: TeacherBrief) -> str:
    '''Требования преподавателя и текущее задание.'''
    requirements = (
        f'Требования преподавателя:\n{brief.context}'
        if brief.context else 'Преподаватель пока не задал требования.'
    )
    if brief.task_content:
        task = f'Текущее задание «{brief.task_title or "Задание"}»:\n{brief.task_content}'
    else:
        task = 'Активного задания пока нет.'
    return cut_text(f'{requirements}\n\n{task}')


def role_text(brief: TeacherBrief) -> str:
    ai = brief.ai
    return cut_text(f'Сейчас ассистент работает в роли «{ai.role_name}».\n\n{ai.role_text}')


async def safe_answer(cb: CallbackQuery, text: str | None = None) -> None:
    '''Подтверждает нажатие. Устаревший запрос Telegram не должен прерывать обработку.'''
    try:
        await cb.answer(text)
    except TelegramBadRequest as exc:
        logger.info('Подтверждение кнопки не принято Telegram: %s', type(exc).__name__)


async def in_open_dialog(user_id: int) -> bool:
    '''Диалог по заданию открыт (active или ended): переписка в чате не очищается.'''
    student = await find_student(user_id)
    return student is not None and await find_open_session(student.id) is not None


async def clean_outside(message: Message, user_id: int) -> None:
    '''Очистка переписки вне открытого диалога. Во время диалога ничего не удаляется.'''
    if not await in_open_dialog(user_id):
        await chat_cleanup.reset(message)


async def intake(message: Message, clean: bool) -> None:
    '''Запоминает сообщение ученика для будущей очистки; при clean=True очищает переписку вне диалога.'''
    await chat_cleanup.remember(message)
    if clean:
        await clean_outside(message, message.from_user.id)


async def prepare(message: Message) -> tuple[Student, TeacherBrief] | None:
    '''Проверяет регистрацию и ключ Polza.ai.'''
    student = await find_student(message.from_user.id)
    if student is None:
        await chat_cleanup.answer(message, 'Сначала зарегистрируйтесь: отправьте /start.')
        return None
    brief = await load_brief()
    if not brief.api_key:
        await chat_cleanup.answer(message, 'Преподаватель ещё не подключил ключ Polza.ai.')
        return None
    return student, brief


async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await intake(message, clean=True)
    student = await find_student(message.from_user.id)
    if student:
        await chat_cleanup.answer(
            message,
            f'Вы уже зарегистрированы, {student.full_name}. Выберите действие в меню ниже.',
            reply_markup=student_menu(student_app_url()),
        )
        return
    await state.set_state(RegisterStates.full_name)
    await chat_cleanup.answer(message, 'Добро пожаловать! Для регистрации напишите ваши имя и фамилию.')


async def got_full_name(message: Message, state: FSMContext, bot: Bot) -> None:
    await intake(message, clean=False)
    name = ' '.join((message.text or '').split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        await chat_cleanup.answer(
            message, f'Имя должно быть от {NAME_MIN} до {NAME_MAX} символов. Попробуйте ещё раз.')
        return

    await state.clear()
    if await find_student(message.from_user.id):
        await chat_cleanup.answer(message, 'Вы уже зарегистрированы.')
        return

    student = await register_student(bot, message.from_user.id, name, message.from_user.username)
    if student and student.topic_id:
        topic_line = 'Ваш личный топик для переписки создан.'
    else:
        topic_line = 'Топик создать не удалось, поэтому переписка пока не дублируется.'

    await chat_cleanup.answer(message, INSTRUCTION)
    await chat_cleanup.answer(
        message,
        f'Регистрация завершена, {name}!\n\n{topic_line}\n\nВыберите действие в меню.',
        reply_markup=student_menu(student_app_url()),
    )


async def open_menu(message: Message) -> None:
    await intake(message, clean=True)
    await chat_cleanup.answer(message, 'Меню ученика', reply_markup=student_menu(student_app_url()))


async def open_help(message: Message) -> None:
    await intake(message, clean=True)
    await chat_cleanup.answer(message, INSTRUCTION, reply_markup=back_kb())


async def show_context(message: Message) -> None:
    await intake(message, clean=True)
    await chat_cleanup.answer(message, overview_text(await load_brief()), reply_markup=back_kb())


async def start_dialog(reply: Message, user_id: int, bot: Bot) -> None:
    '''Открывает диалог по активному заданию. Открытый диалог по тому же заданию не дублируется.'''
    student = await find_student(user_id)
    if student is None:
        await chat_cleanup.answer(reply, 'Сначала зарегистрируйтесь: отправьте /start.')
        return
    brief = await load_brief()
    if not brief.api_key:
        await chat_cleanup.answer(reply, 'Преподаватель ещё не подключил ключ Polza.ai.')
        return
    if brief.task_id is None:
        await chat_cleanup.answer(reply, NO_ACTIVE_TASK)
        return

    async with student_lock(student.id):
        open_now = await find_open_session(student.id)
        if open_now and open_now.status == STATUS_ENDED:
            await chat_cleanup.answer(
                reply,
                'Предыдущий диалог завершён и ждёт оценки. Нажмите «Завершить диалог» '
                'или отправьте /finish, чтобы её получить.',
            )
            return
        if open_now and open_now.task_id == brief.task_id:
            await chat_cleanup.answer(
                reply,
                f'Диалог по этому заданию уже идёт. Ответов нейросети: '
                f'{open_now.replies_used} из {open_now.reply_limit}. Продолжайте писать, '
                'а /finish завершит диалог.',
            )
            return

        # Сначала убираем старое меню истории, потом отмена может опубликовать новое
        await topic_history.reset_screen(bot, student.id)
        if open_now:
            await cancel_session(open_now.id)
            await topic_history.close_dialog(bot, student.id, open_now.id)
            await chat_cleanup.answer(
                reply,
                f'Диалог по заданию №{open_now.task_id} отменён: активное задание изменилось. '
                'Оценка не выставлена.',
            )
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

    goal_line = (
        f'Цель: «{goal.text}». Режим проверки: «{GOAL_MODES[mode].title}».'
        if goal else 'Цель не задана, проверка по цели пропускается.'
    )
    await chat_cleanup.answer(
        reply,
        f'Задание «{brief.task_title or "Задание"}». Отправьте ответ текстом или голосовым сообщением. '
        'Нейросеть ответит и задаст уточняющие вопросы.\n'
        f'{goal_line}\n'
        f'Ответов нейросети: 0 из {limit}.\n'
        'Завершить досрочно: /finish.',
    )


async def answer_command(message: Message, bot: Bot) -> None:
    await chat_cleanup.remember(message)
    await start_dialog(message, message.from_user.id, bot)


CLEAN_ACTIONS = {'help', 'task', 'role', 'menu'}


async def student_action(cb: CallbackQuery, bot: Bot) -> None:
    # Подтверждаем нажатие сразу: долгие запросы к БД и Polza.ai задерживают ответ Telegram
    await safe_answer(cb)
    action = (cb.data or '').split(':', 1)[-1]
    if action in CLEAN_ACTIONS:
        await clean_outside(cb.message, cb.from_user.id)
    if action == 'menu':
        await chat_cleanup.answer(cb.message, 'Меню ученика', reply_markup=student_menu(student_app_url()))
    elif action == 'help':
        await chat_cleanup.answer(cb.message, INSTRUCTION, reply_markup=back_kb())
    elif action == 'task':
        await chat_cleanup.answer(cb.message, overview_text(await load_brief()), reply_markup=back_kb())
    elif action == 'role':
        await chat_cleanup.answer(cb.message, role_text(await load_brief()), reply_markup=back_kb())
    elif action == 'answer':
        await start_dialog(cb.message, cb.from_user.id, bot)
    elif action == 'finish':
        await finish_flow(cb.message, bot, cb.from_user.id)


async def cancel(message: Message, state: FSMContext) -> None:
    await chat_cleanup.remember(message)
    await state.clear()
    student = await find_student(message.from_user.id)
    active = await find_active_session(student.id) if student else None
    text = 'Отменено.'
    if active:
        text += '\nДиалог по заданию не прерван: продолжайте писать ответы. Завершить и получить оценку: /finish.'
    await chat_cleanup.answer(message, text, reply_markup=student_menu(student_app_url()))


async def mirror_to_teacher(bot: Bot, text: str) -> None:
    '''Дублирует итог в служебный топик преподавателя, если его id задан в настройках.'''
    raw = (await get_setting('teacher_topic_id') or '').strip()
    if not raw.isdigit():
        return
    try:
        await bot.send_message(config.GROUP_ID, cut_text(text), message_thread_id=int(raw))
    except TelegramAPIError as exc:
        logger.warning('Не удалось отправить итог в топик преподавателя: %s', type(exc).__name__)


async def conclude(reply: Message, bot: Bot, student: Student, session_id: int) -> None:
    '''Итоговая оценка по завершённому диалогу. Вызывается под блокировкой ученика.

    Топик закрывается только после сохранения оценки (статус graded).
    Если Polza.ai недоступен, диалог остаётся в статусе ended, сообщения в топике не трогаются.
    '''
    session = await get_session(session_id)
    if session is None:
        return
    brief = await load_brief()
    if not brief.api_key:
        await chat_cleanup.answer(
            reply, 'Преподаватель ещё не подключил ключ Polza.ai. Диалог сохранён: повторите /finish позже.')
        return

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
        await chat_cleanup.answer(
            reply,
            'Не удалось подвести итог: нейросеть недоступна. Диалог сохранён, повторите позже командой /finish.',
        )
        return

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
        await chat_cleanup.answer(reply, 'Оценка по этому диалогу уже выставлена.')
        return

    await chat_cleanup.answer(reply, cut_text(report))

    topic_id = await ensure_topic(bot, student)
    report_ids = await mirror_text(bot, student, topic_id, report)
    await topic_history.remember(student.id, session.id, report_ids, 'report')
    await mirror_to_teacher(bot, f'{student.full_name or "Ученик"}:\n{report}')
    # Итог уже сохранён в dialog_sessions.report: сообщения диалога убираются, остаётся меню
    await topic_history.close_dialog(bot, student.id, session.id)


async def finish_flow(reply: Message, bot: Bot, user_id: int) -> None:
    student = await find_student(user_id)
    if student is None:
        await chat_cleanup.answer(reply, 'Сначала зарегистрируйтесь: отправьте /start.')
        return

    async with student_lock(student.id):
        session = await find_open_session(student.id)
        if session is None:
            await chat_cleanup.answer(
                reply, 'Открытого диалога сейчас нет. Начните его кнопкой «Ответить на задание».')
            return
        if session.status == STATUS_ACTIVE:
            if session.replies_used == 0:
                await cancel_session(session.id)
                await topic_history.close_dialog(bot, student.id, session.id)
                await chat_cleanup.answer(reply, EMPTY_DIALOG)
                return
            await mark_ended(session.id)
        await conclude(reply, bot, student, session.id)


async def finish_command(message: Message, bot: Bot) -> None:
    await chat_cleanup.remember(message)
    await finish_flow(message, bot, message.from_user.id)


async def respond(message: Message, bot: Bot, student: Student, brief: TeacherBrief, text: str) -> None:
    '''Свободный чат вне диалога по заданию. В топике ход не привязывается к диалогу.'''
    reply = await ask_tutor(student, text, brief)
    if not reply:
        await chat_cleanup.answer(message, 'Не удалось получить ответ, попробуйте чуть позже.')
        return

    await save_exchange(student.id, text, reply)
    await chat_cleanup.answer(message, cut_text(reply))
    topic_id = await ensure_topic(bot, student)
    await mirror_exchange(bot, student, topic_id, text, reply)


async def dialog_turn(message: Message, bot: Bot, student: Student, brief: TeacherBrief,
                      text: str, voice_file_id: str | None = None) -> None:
    '''Ход диалога по заданию. Сообщения топика запоминаются под id диалога.
    При исчерпании лимита сразу выставляется итог.
    '''
    async with student_lock(student.id):
        session = await find_active_session(student.id)
        if session is None:
            await chat_cleanup.answer(
                message, 'Диалог уже завершён. Чтобы начать новый, нажмите «Ответить на задание».')
            return
        if session.task_id != brief.task_id:
            await cancel_session(session.id)
            await topic_history.close_dialog(bot, student.id, session.id)
            await chat_cleanup.answer(
                message,
                f'Диалог по заданию №{session.task_id} отменён: активное задание изменилось. '
                'Оценка не выставлена.',
            )
            return

        reply = await ask_dialog(session, text, brief)
        if not reply:
            await chat_cleanup.answer(
                message,
                'Не удалось получить ответ нейросети, попробуйте чуть позже. '
                'Сообщение не сохранено: отправьте его ещё раз.',
            )
            return

        updated = await record_turn(session.id, text, reply)
        if updated is None:
            return

        await chat_cleanup.answer(message, cut_text(
            f'{reply}\n\nОтветов нейросети: {updated.replies_used} из {updated.reply_limit}.'
        ))
        topic_id = await ensure_topic(bot, student)
        if voice_file_id:
            voice_ids = await mirror_voice(bot, student, topic_id, voice_file_id,
                                           'Голосовое сообщение в диалоге')
            await topic_history.remember(student.id, updated.id, voice_ids, 'voice')
        text_ids = await mirror_exchange(bot, student, topic_id, text, reply)
        await topic_history.remember(student.id, updated.id, text_ids, 'text')

        if updated.replies_used >= updated.reply_limit:
            await mark_ended(updated.id)
            await chat_cleanup.answer(
                message, 'Лимит ответов нейросети исчерпан, диалог завершён. Подводим итог…')
            await conclude(message, bot, student, updated.id)


async def chat_text(message: Message, bot: Bot) -> None:
    await intake(message, clean=True)
    prepared = await prepare(message)
    if prepared is None:
        return
    student, brief = prepared
    text = (message.text or '').strip()[:MAX_INPUT]
    if await find_active_session(student.id):
        await dialog_turn(message, bot, student, brief, text)
        return
    await respond(message, bot, student, brief, text)


async def chat_voice(message: Message, bot: Bot) -> None:
    await intake(message, clean=True)
    prepared = await prepare(message)
    if prepared is None:
        return
    student, brief = prepared

    # Только распознавание: оценка произношения не выполняется
    text = await transcribe_voice(bot, message.voice.file_id, brief)
    if not text:
        await chat_cleanup.answer(
            message, 'Не удалось распознать голосовое. Попробуйте ещё раз или напишите текстом.')
        return
    text = text[:MAX_INPUT]

    if await find_active_session(student.id):
        await chat_cleanup.answer(message, f'Распознано: «{cut_text(text, 500)}»')
        await dialog_turn(message, bot, student, brief, text, voice_file_id=message.voice.file_id)
        return

    topic_id = await ensure_topic(bot, student)
    await mirror_voice(bot, student, topic_id, message.voice.file_id, 'Голосовое сообщение')
    await chat_cleanup.answer(message, f'Распознано: «{cut_text(text, 500)}»')
    await respond(message, bot, student, brief, text)


def setup(router: Router) -> None:
    # Порядок важен: команды и обработчики состояний регистрируются раньше общих
    router.message(CommandStart(), PRIVATE)(cmd_start)
    router.message(Command('cancel'), PRIVATE)(cancel)
    router.message(Command('menu'), PRIVATE)(open_menu)
    router.message(Command('help'), PRIVATE)(open_help)
    router.message(Command('context'), PRIVATE)(show_context)
    router.message(Command('answer'), PRIVATE)(answer_command)
    router.message(Command('finish'), PRIVATE)(finish_command)
    router.callback_query(F.data.startswith('stu:'))(student_action)

    router.message(RegisterStates.full_name, PRIVATE, F.text)(got_full_name)

    router.message(PRIVATE, F.text, ~F.text.startswith('/'))(chat_text)
    router.message(PRIVATE, F.voice)(chat_voice)

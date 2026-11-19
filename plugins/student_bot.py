from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from database.models import Student
from services.students import (
    cut_text,
    ensure_topic,
    find_student,
    mirror_exchange,
    mirror_voice,
    register_student,
)
from services.tutor import (
    TeacherBrief,
    analyze_voice,
    ask_tutor,
    grade_text,
    load_brief,
    save_attempt,
    save_exchange,
    transcription_of,
)

ROLES = {'student'}
PRIORITY = 30

NAME_MIN = 2
NAME_MAX = 64
MAX_INPUT = 2000
PRIVATE = F.chat.type == 'private'


class RegisterStates(StatesGroup):
    full_name = State()


class AnswerStates(StatesGroup):
    waiting = State()


async def prepare(message: Message, needs_task: bool = False) -> tuple[Student, TeacherBrief] | None:
    '''Проверяет регистрацию, ключ Polza.ai и (при необходимости) наличие задания.'''
    student = await find_student(message.from_user.id)
    if student is None:
        await message.answer('Сначала зарегистрируйтесь: отправьте /start.')
        return None
    brief = await load_brief()
    if not brief.api_key:
        await message.answer('Преподаватель ещё не подключил ключ Polza.ai.')
        return None
    if needs_task and brief.task_id is None:
        await message.answer('Активного задания сейчас нет.')
        return None
    return student, brief


# ---------- регистрация ----------

async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    student = await find_student(message.from_user.id)
    if student:
        await message.answer(
            f'Вы уже зарегистрированы, {student.full_name}. '
            'Задавайте вопросы текстом или голосом, а для ответа на задание отправьте /answer.'
        )
        return
    await state.set_state(RegisterStates.full_name)
    await message.answer('Добро пожаловать! Для регистрации напишите ваши имя и фамилию.')


async def got_full_name(message: Message, state: FSMContext, bot: Bot) -> None:
    name = ' '.join((message.text or '').split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        await message.answer(f'Имя должно быть от {NAME_MIN} до {NAME_MAX} символов. Попробуйте ещё раз.')
        return

    await state.clear()
    if await find_student(message.from_user.id):
        await message.answer('Вы уже зарегистрированы.')
        return

    student = await register_student(bot, message.from_user.id, name, message.from_user.username)
    if student and student.topic_id:
        topic_line = 'Ваш личный топик для переписки создан.'
    else:
        topic_line = 'Топик создать не удалось, поэтому переписка пока не дублируется.'

    await message.answer(
        f'Регистрация завершена, {name}!\n\n{topic_line}\n\n'
        'Команды:\n'
        '/context — требования и текущее задание\n'
        '/answer — отправить ответ на задание\n'
        '/cancel — отменить ввод'
    )


# ---------- задание и контекст ----------

async def show_context(message: Message) -> None:
    brief = await load_brief()
    parts = [
        f'Требования преподавателя:\n{brief.context}'
        if brief.context else 'Преподаватель пока не задал требования.'
    ]
    if brief.task_content:
        parts.append(f'Текущее задание «{brief.task_title or "Задание"}»:\n{brief.task_content}')
    else:
        parts.append('Активного задания пока нет.')
    await message.answer(cut_text('\n\n'.join(parts)))


async def start_answer(message: Message, state: FSMContext) -> None:
    student = await find_student(message.from_user.id)
    if student is None:
        await message.answer('Сначала зарегистрируйтесь: отправьте /start.')
        return
    brief = await load_brief()
    if brief.task_id is None:
        await message.answer('Активного задания сейчас нет.')
        return
    await state.set_state(AnswerStates.waiting)
    await message.answer(
        f'Задание «{brief.task_title or "Задание"}». Отправьте ответ текстом или голосовым сообщением.\n'
        'Отменить можно командой /cancel.'
    )


async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer('Отменено.')


# ---------- ответ на задание ----------

async def finish_answer(message: Message, bot: Bot, student: Student, brief: TeacherBrief,
                        result: dict, transcription: str | None) -> None:
    score = result.get('score')
    feedback = str(result.get('feedback') or '').strip()
    score_line = f'Оценка: {score}' if score is not None else 'Оценка: не получена'
    verdict = f'{score_line}\n\n{feedback}'.strip()

    await save_attempt(student.id, brief.task_id, score, transcription)
    await message.answer(cut_text(verdict))

    topic_id = await ensure_topic(bot, student)
    await mirror_exchange(
        bot, student, topic_id,
        f'Ответ на задание «{brief.task_title or "Задание"}»:\n{transcription or "[голосовое сообщение]"}',
        verdict,
    )


async def got_answer_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    prepared = await prepare(message, needs_task=True)
    if prepared is None:
        return
    student, brief = prepared

    text = (message.text or '').strip()[:MAX_INPUT]
    result = await grade_text(brief, text)
    if not result:
        await message.answer('Не удалось проверить ответ, попробуйте позже.')
        return
    await finish_answer(message, bot, student, brief, result, transcription=text)


async def got_answer_voice(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    prepared = await prepare(message, needs_task=True)
    if prepared is None:
        return
    student, brief = prepared

    result = await analyze_voice(bot, message.voice.file_id, brief, reference=brief.task_content or '')
    if not result:
        await message.answer('Не удалось проверить голосовое, попробуйте позже.')
        return

    topic_id = await ensure_topic(bot, student)
    await mirror_voice(bot, student, topic_id, message.voice.file_id, '🎙 Голосовой ответ на задание')
    await finish_answer(message, bot, student, brief, result, transcription=transcription_of(result))


# ---------- свободный диалог ----------

async def respond(message: Message, bot: Bot, student: Student, brief: TeacherBrief, text: str) -> None:
    reply = await ask_tutor(student, text, brief)
    if not reply:
        await message.answer('Не удалось получить ответ, попробуйте чуть позже.')
        return

    await save_exchange(student.id, text, reply)
    await message.answer(cut_text(reply))
    topic_id = await ensure_topic(bot, student)
    await mirror_exchange(bot, student, topic_id, text, reply)


async def chat_text(message: Message, bot: Bot) -> None:
    prepared = await prepare(message)
    if prepared is None:
        return
    student, brief = prepared
    await respond(message, bot, student, brief, (message.text or '').strip()[:MAX_INPUT])


async def chat_voice(message: Message, bot: Bot) -> None:
    prepared = await prepare(message)
    if prepared is None:
        return
    student, brief = prepared

    # Без эталонного текста: нужна только расшифровка, а не оценка произношения.
    result = await analyze_voice(bot, message.voice.file_id, brief, reference='')
    text = transcription_of(result)
    if not text:
        await message.answer('Не удалось распознать голосовое. Попробуйте ещё раз или напишите текстом.')
        return

    topic_id = await ensure_topic(bot, student)
    await mirror_voice(bot, student, topic_id, message.voice.file_id, '🎙 Голосовое сообщение')
    await message.answer(f'🎙 Распознано: «{cut_text(text, 500)}»')
    await respond(message, bot, student, brief, text[:MAX_INPUT])


def setup(router: Router) -> None:
    # Порядок важен: команды и обработчики состояний регистрируются раньше общих.
    router.message(CommandStart(), PRIVATE)(cmd_start)
    router.message(Command('cancel'), PRIVATE)(cancel)
    router.message(Command('context'), PRIVATE)(show_context)
    router.message(Command('answer'), PRIVATE)(start_answer)

    router.message(RegisterStates.full_name, PRIVATE, F.text)(got_full_name)
    router.message(AnswerStates.waiting, PRIVATE, F.text, ~F.text.startswith('/'))(got_answer_text)
    router.message(AnswerStates.waiting, PRIVATE, F.voice)(got_answer_voice)

    router.message(PRIVATE, F.text, ~F.text.startswith('/'))(chat_text)
    router.message(PRIVATE, F.voice)(chat_voice)

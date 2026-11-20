from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from core.filters import TeacherChatFilter
from database.models import Task
from services.screen import drop, show
from services.tasks import (
    create_task,
    get_active_task,
    get_task,
    list_tasks,
    set_active_task,
)

ROLES = {'main'}
PRIORITY = 12

TITLE_MAX = 100
CONTENT_MAX = 2000
LIST_LIMIT = 10


class TaskStates(StatesGroup):
    title = State()
    content = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def guard(cb: CallbackQuery) -> bool:
    if is_admin(cb.from_user.id):
        return True
    await cb.answer('Нет доступа', show_alert=True)
    return False


async def edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await show(cb.bot, cb.message.chat.id, [text], markup, source_id=cb.message.message_id)


def cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Отмена', callback_data='tasks:cancel')
    return kb.as_markup()


def tasks_menu(tasks: list[Task], active_id: int | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for task in tasks:
        mark = '✓ ' if task.id == active_id else ''
        kb.button(text=f'{mark}№{task.id} {task.title[:30]}', callback_data=f'tasks:set:{task.id}')
    kb.button(text='Новое задание', callback_data='tasks:new')
    kb.button(text='Снять активное', callback_data='tasks:off')
    kb.button(text='Назад', callback_data='menu:main')
    kb.adjust(1)
    return kb.as_markup()


def tasks_text(active: Task | None, notice: str | None) -> str:
    lines = []
    if notice:
        lines += [notice, '']
    lines.append('Задания')
    lines.append('')
    if active:
        lines.append(f'Активное задание: №{active.id} «{active.title}»')
    else:
        lines.append('Активного задания нет. Ученики его не увидят.')
    lines += ['', 'Выберите задание, чтобы сделать его активным, или создайте новое.']
    return '\n'.join(lines)


async def show_list(bot: Bot, chat_id: int, *, notice: str | None = None,
                    source_id: int | None = None) -> None:
    tasks = await list_tasks(LIST_LIMIT)
    active = await get_active_task()
    await show(
        bot, chat_id,
        [tasks_text(active, notice)],
        tasks_menu(tasks, active.id if active else None),
        source_id=source_id,
    )


async def menu_tasks(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await show_list(cb.bot, cb.message.chat.id, source_id=cb.message.message_id)
    await cb.answer()


async def pick_task(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    raw = (cb.data or '').split(':')[-1]
    task = await get_task(int(raw)) if raw.isdigit() else None
    if task is None:
        notice = 'Задание не найдено.'
    else:
        await set_active_task(task.id)
        notice = f'Активным сделано задание №{task.id}.'
    await show_list(cb.bot, cb.message.chat.id, notice=notice, source_id=cb.message.message_id)
    await cb.answer()


async def task_off(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    await set_active_task(None)
    await show_list(cb.bot, cb.message.chat.id, notice='Активное задание снято.',
                    source_id=cb.message.message_id)
    await cb.answer()


async def new_task(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(TaskStates.title)
    await edit(cb, f'Отправьте название задания (до {TITLE_MAX} символов).', cancel_kb())
    await cb.answer()


async def title_input(message: Message, state: FSMContext) -> None:
    title = ' '.join((message.text or '').split())
    await drop(message)
    if not 1 <= len(title) <= TITLE_MAX:
        await show(message.bot, message.chat.id,
                   [f'Название должно быть от 1 до {TITLE_MAX} символов. Попробуйте ещё раз.'],
                   cancel_kb())
        return
    await state.update_data(title=title)
    await state.set_state(TaskStates.content)
    await show(message.bot, message.chat.id,
               [f'Название: «{title}»\n\nТеперь отправьте условие задания (до {CONTENT_MAX} символов).'],
               cancel_kb())


async def content_input(message: Message, state: FSMContext) -> None:
    content = (message.text or '').strip()
    await drop(message)
    if not content or len(content) > CONTENT_MAX:
        await show(message.bot, message.chat.id,
                   [f'Условие должно быть от 1 до {CONTENT_MAX} символов. Попробуйте ещё раз.'],
                   cancel_kb())
        return
    data = await state.get_data()
    await state.clear()
    task = await create_task(data.get('title') or 'Задание', content)
    await set_active_task(task.id)
    await show_list(message.bot, message.chat.id,
                    notice=f'Задание №{task.id} создано и стало активным.')


async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await show_list(cb.bot, cb.message.chat.id, source_id=cb.message.message_id)
    await cb.answer('Отменено')


def setup(router: Router) -> None:
    router.callback_query(F.data == 'menu:tasks')(menu_tasks)
    router.callback_query(F.data.startswith('tasks:set:'))(pick_task)
    router.callback_query(F.data == 'tasks:off')(task_off)
    router.callback_query(F.data == 'tasks:new')(new_task)
    router.callback_query(F.data == 'tasks:cancel')(cancel)

    router.message(TaskStates.title, TeacherChatFilter())(title_input)
    router.message(TaskStates.content, TeacherChatFilter())(content_input)

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.config import config
from core.filters import TeacherChatFilter
from services.dialogs import REPLY_LIMIT_OPTIONS, load_reply_limit, set_reply_limit
from services.goals import (
    GOAL_MODES,
    GOAL_TEXT_MAX,
    create_goal,
    get_active_goal,
    get_goal,
    list_goals,
    load_goal_mode,
    next_mode,
    set_active_goal,
    set_goal_mode,
)
from services.screen import drop, show

ROLES = {'main'}
PRIORITY = 18

GOALS_LIMIT = 10
PREVIEW = 30


class GoalStates(StatesGroup):
    text = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def guard(cb: CallbackQuery) -> bool:
    if is_admin(cb.from_user.id):
        return True
    await cb.answer('Нет доступа', show_alert=True)
    return False


async def edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await show(cb.bot, cb.message.chat.id, [text], markup, source_id=cb.message.message_id)


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:64], callback_data=data)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn('Отмена', 'dlg:cancel')]])


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + '…'


async def home_text(notice: str | None = None) -> str:
    limit = await load_reply_limit()
    mode = await load_goal_mode()
    goal = await get_active_goal()
    goal_line = (
        f'Активная цель: «{_short(goal.text, 200)}»'
        if goal else 'Активная цель: не задана, проверка по цели пропускается'
    )
    lines = [notice, ''] if notice else []
    lines += [
        'Цели и диалог',
        '',
        f'Количество ответов нейросети: {limit}',
        f'Режим проверки цели: {GOAL_MODES[mode].title}',
        goal_line,
        '',
        'Ответы нейросети ограничивают один диалог. Когда лимит исчерпан, '
        'бот выставляет итоговую оценку по шкале от 1 до 5.',
    ]
    return '\n'.join(lines)


async def home_menu() -> InlineKeyboardMarkup:
    limit = await load_reply_limit()
    mode = await load_goal_mode()
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(f'Ответов нейросети: {limit}', 'dlg:cyc:limit')],
        [btn(f'Режим проверки: {GOAL_MODES[mode].title}', 'dlg:cyc:mode')],
        [btn('Цели', 'dlg:goals')],
        [btn('Что значат режимы', 'dlg:modes')],
        [btn('Назад', 'menu:main')],
    ])


async def render_home(cb: CallbackQuery, notice: str | None = None) -> None:
    await edit(cb, await home_text(notice), await home_menu())


async def open_home(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await render_home(cb)
    await cb.answer()


async def cycle_limit(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    current = await load_reply_limit()
    idx = REPLY_LIMIT_OPTIONS.index(current) if current in REPLY_LIMIT_OPTIONS else -1
    await set_reply_limit(REPLY_LIMIT_OPTIONS[(idx + 1) % len(REPLY_LIMIT_OPTIONS)])
    await render_home(cb)
    await cb.answer('Сохранено')


async def cycle_mode(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    await set_goal_mode(next_mode(await load_goal_mode()))
    await render_home(cb)
    await cb.answer('Сохранено')


async def show_modes(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    lines = ['Режимы проверки цели', '']
    for mode_id, mode in GOAL_MODES.items():
        suffix = ' (по умолчанию)' if mode_id == 'normal' else ''
        lines.append(f'{mode.title.capitalize()}{suffix}: {mode.criteria}')
        lines.append(f'Потолок итога, если цель не достигнута: {mode.cap}.')
        lines.append('')
    lines.append(
        'Если цель достигнута, оценка не снижается. Без активной цели режим не используется.'
    )
    back = InlineKeyboardMarkup(inline_keyboard=[[btn('Назад', 'menu:dialog')]])
    await edit(cb, '\n'.join(lines), back)
    await cb.answer()


async def render_goals(bot: Bot, chat_id: int, *, notice: str | None = None,
                       source_id: int | None = None) -> None:
    goals = await list_goals(GOALS_LIMIT)
    active = await get_active_goal()
    lines = [notice, ''] if notice else []
    lines += ['Цели диалога', '']
    if active:
        lines.append(f'Активная цель: №{active.id} «{_short(active.text, 200)}»')
    else:
        lines.append('Активной цели нет. Проверка по цели пропускается.')
    lines += ['', 'Выберите цель, чтобы сделать её активной, или создайте новую.' if goals
              else 'Целей пока нет. Создайте первую.']

    rows = []
    for goal in goals:
        mark = '✓ ' if active and goal.id == active.id else ''
        rows.append([btn(f'{mark}№{goal.id} {_short(goal.text, PREVIEW)}', f'dlg:pick:{goal.id}')])
    rows += [
        [btn('Новая цель', 'dlg:new')],
        [btn('Снять активную', 'dlg:off')],
        [btn('Назад', 'menu:dialog')],
    ]
    await show(bot, chat_id, ['\n'.join(lines)], InlineKeyboardMarkup(inline_keyboard=rows),
               source_id=source_id)


async def goals_page(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await render_goals(cb.bot, cb.message.chat.id, source_id=cb.message.message_id)
    await cb.answer()


async def pick_goal(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    raw = (cb.data or '').split(':')[-1]
    goal = await get_goal(int(raw)) if raw.isdigit() else None
    if goal is None:
        notice = 'Цель не найдена.'
    else:
        await set_active_goal(goal.id)
        notice = f'Активной сделана цель №{goal.id}.'
    await render_goals(cb.bot, cb.message.chat.id, notice=notice, source_id=cb.message.message_id)
    await cb.answer()


async def goal_off(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    await set_active_goal(None)
    await render_goals(cb.bot, cb.message.chat.id, notice='Активная цель снята.',
                       source_id=cb.message.message_id)
    await cb.answer()


async def new_goal(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(GoalStates.text)
    await edit(
        cb,
        f'Отправьте цель одним сообщением (до {GOAL_TEXT_MAX} символов).\n\n'
        'Например: «ученик может заказать кофе и уточнить состав блюда».',
        cancel_kb(),
    )
    await cb.answer()


async def goal_input(message: Message, state: FSMContext) -> None:
    text = ' '.join((message.text or '').split())
    await drop(message)
    if not 1 <= len(text) <= GOAL_TEXT_MAX:
        await show(message.bot, message.chat.id,
                   [f'Цель должна быть от 1 до {GOAL_TEXT_MAX} символов. Попробуйте ещё раз.'],
                   cancel_kb())
        return
    goal = await create_goal(text)
    await set_active_goal(goal.id)
    await state.clear()
    await render_goals(message.bot, message.chat.id,
                       notice=f'Цель №{goal.id} создана и стала активной.')


async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await render_home(cb, notice='Отменено')
    await cb.answer()


def setup(router: Router) -> None:
    router.callback_query(F.data == 'menu:dialog')(open_home)
    router.callback_query(F.data == 'dlg:cyc:limit')(cycle_limit)
    router.callback_query(F.data == 'dlg:cyc:mode')(cycle_mode)
    router.callback_query(F.data == 'dlg:modes')(show_modes)
    router.callback_query(F.data == 'dlg:goals')(goals_page)
    router.callback_query(F.data.startswith('dlg:pick:'))(pick_goal)
    router.callback_query(F.data == 'dlg:off')(goal_off)
    router.callback_query(F.data == 'dlg:new')(new_goal)
    router.callback_query(F.data == 'dlg:cancel')(cancel)

    router.message(GoalStates.text, TeacherChatFilter())(goal_input)

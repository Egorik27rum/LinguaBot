import html
import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.bot_manager import add_extra_bot, known_tokens, read_bots_data
from core.bot_status import (
    STATE_ERROR,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    BotStatus,
    check_group_link,
    get_status,
    probe_token,
)
from core.config import config
from core.filters import TeacherChatFilter
from services.screen import drop, show

ROLES = {'main'}
PRIORITY = 15

TOKEN_RE = re.compile(r'^\d{6,}:[A-Za-z0-9_-]{30,}$')

PROMPT_TEXT = (
    'Отправьте токен нового бота (от @BotFather) одним сообщением.\n'
    'Чтобы отменить, отправьте /menu.'
)

STATE_VIEW = {
    STATE_RUNNING: ('✅', 'работает'),
    STATE_STARTING: ('⏳', 'запускается'),
    STATE_STOPPED: ('⏹', 'остановлен'),
    STATE_ERROR: ('❌', 'ошибка'),
}
LEVEL_ICON = {'ok': '✅', 'warn': '⚠️', 'error': '❌'}


class BotStates(StatesGroup):
    token = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def guard(cb: CallbackQuery) -> bool:
    if is_admin(cb.from_user.id):
        return True
    await cb.answer('Нет доступа', show_alert=True)
    return False


async def edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await show(cb.bot, cb.message.chat.id, [text], markup,
               parse_mode='HTML', source_id=cb.message.message_id)


def bots_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='➕ Добавить бота', callback_data='bots:add')
    kb.button(text='🔎 Проверить привязку', callback_data='bots:check')
    kb.button(text='🔄 Обновить статус', callback_data='menu:bots')
    kb.button(text='Назад', callback_data='menu:main')
    kb.adjust(1)
    return kb.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Отмена', callback_data='bots:cancel')
    return kb.as_markup()


def _helpers() -> tuple[list[dict], str | None]:
    try:
        items = read_bots_data()['helpers']
    except ValueError as exc:
        return [], str(exc)
    return [item for item in items if isinstance(item, dict)], None


def _bot_line(label: str, st: BotStatus | None, enabled: bool = True,
              pending_text: str = 'ждёт перезапуска run.bat') -> list[str]:
    if not enabled:
        icon, text = '⏸', 'выключен в configs/bots.json'
    elif st is None:
        icon, text = '🔄', pending_text
    else:
        icon, text = STATE_VIEW.get(st.state, ('❔', st.state))

    name = f'@{st.username}' if st and st.username else label
    lines = [f'{icon} {html.escape(name)} — <b>{text}</b>']
    if st and st.error:
        lines.append(f'    <i>{html.escape(st.error)}</i>')
    return lines


def render_status() -> str:
    main = get_status('main')
    if main and main.state == STATE_RUNNING:
        head = '✅ <b>Telegram-бот запущен!</b>'
    elif main and main.state == STATE_STARTING:
        head = '⏳ <b>Telegram-бот запускается…</b>'
    else:
        head = '❌ <b>Основной бот не работает</b>'

    lines = [head, '']
    lines += _bot_line('основной бот', main, pending_text='не запущен')
    lines.append('')

    helpers, error = _helpers()
    if error:
        lines.append(f'⚠️ {html.escape(error)}')
    elif not helpers:
        lines.append('ℹ️ Доп. ботов пока нет. Нажмите «Добавить бота».')

    for item in helpers:
        name = str(item.get('name', 'helper'))
        enabled = bool(item.get('enabled', True))
        lines += _bot_line(name, get_status(name), enabled=enabled)

    return '\n'.join(lines)


# ---------- меню ----------

async def menu_bots(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, render_status(), bots_menu())
    await cb.answer()


# ---------- добавление бота ----------

async def add_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(BotStates.token)
    await edit(cb, PROMPT_TEXT, cancel_kb())
    await cb.answer()


async def ask_again(message: Message, reason: str) -> None:
    # Экран с подсказкой и кнопкой «Отмена» остаётся на месте, сообщение заменяется.
    await show(message.bot, message.chat.id, [f'⚠️ {reason}\n\n{PROMPT_TEXT}'], cancel_kb())


async def add_token(message: Message, state: FSMContext) -> None:
    token = (message.text or '').strip()
    await drop(message)  # токен не должен оставаться в чате

    if not TOKEN_RE.match(token):
        await ask_again(message, 'Токен выглядит неверно. Формат: 123456789:AAE-xxxxxxxx...')
        return
    if token in known_tokens():
        await ask_again(message, 'Этот токен уже используется. Отправьте другой.')
        return

    probe = await probe_token(token)
    if probe.status == 'invalid':
        await ask_again(message, 'Telegram не принял токен. Проверьте его в @BotFather.')
        return
    if probe.status == 'unknown':
        await ask_again(message, 'Не удалось связаться с Telegram. Попробуйте позже.')
        return

    await state.clear()
    try:
        name = add_extra_bot(probe.username or 'helper', token)
    except ValueError as exc:
        await show(message.bot, message.chat.id,
                   [f'Не удалось сохранить: {html.escape(str(exc))}'],
                   bots_menu(), parse_mode='HTML')
        return

    await show(
        message.bot, message.chat.id,
        [f'✅ Бот @{html.escape(name)} добавлен в configs/bots.json.\n\n'
         'Перезапустите run.bat, чтобы он запустился.'],
        bots_menu(), parse_mode='HTML',
    )


# ---------- проверка привязки ----------

async def check_link(cb: CallbackQuery, bot: Bot) -> None:
    if not await guard(cb):
        return
    await cb.answer('Проверяю…')

    helpers, error = _helpers()
    enabled = [item for item in helpers if item.get('enabled', True) and item.get('token')]

    if error:
        text = f'⚠️ {html.escape(error)}'
    elif not enabled:
        text = 'Доп. ботов нет, проверять нечего.'
    else:
        lines = ['🔎 <b>Проверка привязки доп. ботов</b>', '']
        for item in enabled:
            report = await check_group_link(bot, str(item['token']).strip())
            label = f'@{report.username}' if report.username else str(item.get('name', 'helper'))
            lines.append(f'{LEVEL_ICON[report.level]} {html.escape(label)} — {html.escape(report.details)}')
        lines += ['', 'Ученики пишут в свои топики, поэтому бот должен быть в группе и видеть сообщения.']
        text = '\n'.join(lines)

    await show(cb.bot, cb.message.chat.id, [text], bots_menu(),
               parse_mode='HTML', source_id=cb.message.message_id)


async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, render_status(), bots_menu())
    await cb.answer('Отменено')


def setup(router: Router) -> None:
    router.callback_query(F.data == 'menu:bots')(menu_bots)
    router.callback_query(F.data == 'bots:add')(add_start)
    router.callback_query(F.data == 'bots:check')(check_link)
    router.callback_query(F.data == 'bots:cancel')(cancel)
    router.message(BotStates.token, TeacherChatFilter())(add_token)

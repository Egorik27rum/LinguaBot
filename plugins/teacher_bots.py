import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from core.filters import TeacherChatFilter
from services.bot_registry import (
    check_token,
    render_link_check,
    render_status,
    save_extra_bot,
    token_format_ok,
    token_taken,
)
from services.screen import drop, show

ROLES = {'main'}
PRIORITY = 15

PROMPT_TEXT = (
    'Отправьте токен нового бота (от @BotFather) одним сообщением.\n'
    'Чтобы отменить, отправьте /menu.'
)
DROP_TOKEN_WARNING = 'Не удалось удалить сообщение с токеном. Удалите его вручную.'


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
    kb.button(text='Добавить бота', callback_data='bots:add')
    kb.button(text='Проверить привязку', callback_data='bots:check')
    kb.button(text='Обновить статус', callback_data='menu:bots')
    kb.button(text='Назад', callback_data='menu:main')
    kb.adjust(1)
    return kb.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Отмена', callback_data='bots:cancel')
    return kb.as_markup()


async def menu_bots(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, render_status(), bots_menu())
    await cb.answer()


async def add_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(BotStates.token)
    await edit(cb, PROMPT_TEXT, cancel_kb())
    await cb.answer()


async def ask_again(message: Message, reason: str) -> None:
    # Экран с подсказкой и кнопкой «Отмена» остаётся на месте, сообщение заменяется
    await show(message.bot, message.chat.id, [f'Внимание: {reason}\n\n{PROMPT_TEXT}'], cancel_kb())


def with_notice(reason: str, notice: str) -> str:
    return f'{reason}\n{notice}' if notice else reason


async def add_token(message: Message, state: FSMContext) -> None:
    token = (message.text or '').strip()
    dropped = await drop(message)  # токен не должен оставаться в чате
    notice = '' if dropped else DROP_TOKEN_WARNING

    if not token_format_ok(token):
        await ask_again(message, with_notice(
            'Токен выглядит неверно. Формат: 123456789:AAE-xxxxxxxx...', notice))
        return
    if token_taken(token):
        await ask_again(message, with_notice('Этот токен уже используется. Отправьте другой.', notice))
        return

    probe = await check_token(token)
    if probe.status == 'invalid':
        await ask_again(message, with_notice(
            'Telegram не принял токен. Проверьте его в @BotFather.', notice))
        return
    if probe.status == 'unknown':
        await ask_again(message, with_notice('Не удалось связаться с Telegram. Попробуйте позже.', notice))
        return

    await state.clear()
    tail = f'\n\nВнимание: {html.escape(notice)}' if notice else ''
    try:
        name = save_extra_bot(probe.username or 'helper', token)
    except ValueError as exc:
        await show(message.bot, message.chat.id,
                   [f'Не удалось сохранить: {html.escape(str(exc))}{tail}'],
                   bots_menu(), parse_mode='HTML')
        return

    await show(
        message.bot, message.chat.id,
        [f'Бот @{html.escape(name)} добавлен в configs/bots.json.\n\n'
         f'Перезапустите run.bat, чтобы он запустился.{tail}'],
        bots_menu(), parse_mode='HTML',
    )


async def check_link(cb: CallbackQuery, bot: Bot) -> None:
    if not await guard(cb):
        return
    await cb.answer('Проверяю…')
    text = await render_link_check(bot)
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

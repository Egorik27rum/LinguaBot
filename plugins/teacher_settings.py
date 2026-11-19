from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from core.filters import TeacherChatFilter
from services.screen import drop, show
from services.settings import get_setting, set_setting

ROLES = {'main'}
PRIORITY = 10

POLZA_TOPUP_URL = 'https://polza.ai'


class SettingsStates(StatesGroup):
    api_key = State()
    context = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def guard(cb: CallbackQuery) -> bool:
    if is_admin(cb.from_user.id):
        return True
    await cb.answer('Нет доступа', show_alert=True)
    return False


async def edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await show(cb.bot, cb.message.chat.id, [text], markup, source_id=cb.message.message_id)


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Настройки', callback_data='menu:settings')
    kb.button(text='Статус', callback_data='menu:status')
    kb.button(text='Боты', callback_data='menu:bots')
    kb.button(text='Модели', callback_data='menu:models')
    kb.button(text='💳 Пополнить баланс', url=POLZA_TOPUP_URL)
    kb.adjust(2)
    return kb.as_markup()


async def settings_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Ключ Polza.ai', callback_data='cfg:api')
    kb.button(text='Контекст для оценки', callback_data='cfg:ctx')
    kb.button(text='Назад', callback_data='menu:main')
    kb.adjust(1)
    return kb.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Отмена', callback_data='cfg:cancel')
    return kb.as_markup()


async def status_text() -> str:
    key = await get_setting('polza_api_key')
    ctx = await get_setting('teacher_context')
    model_text = await get_setting('model_text')
    model_speech = await get_setting('model_speech')

    key_state = 'задан' if key else 'не задан'
    ctx_state = 'задан' if ctx else 'не задан'
    text_model = model_text or 'по умолчанию'
    speech_model = model_speech or 'по умолчанию'

    return (
        'Статус бота\n\n'
        f'Ключ Polza.ai: {key_state}\n'
        f'Контекст для оценки: {ctx_state}\n'
        f'Модель анализа текста: {text_model}\n'
        f'Модель анализа голоса: {speech_model}'
    )


# ---------- команды ----------

async def open_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show(message.bot, message.chat.id, ['Главное меню'], main_menu())
    await drop(message)


# ---------- навигация ----------

async def menu_main(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, 'Главное меню', main_menu())
    await cb.answer()


async def menu_settings(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, 'Настройки', await settings_menu())
    await cb.answer()


async def menu_status(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    kb = InlineKeyboardBuilder()
    kb.button(text='💳 Пополнить баланс', url=POLZA_TOPUP_URL)
    kb.button(text='Назад', callback_data='menu:main')
    kb.adjust(1)
    await edit(cb, await status_text(), kb.as_markup())
    await cb.answer()


# ---------- ключ Polza.ai ----------

async def ask_api_key(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(SettingsStates.api_key)
    await edit(cb, 'Отправьте ключ Polza.ai одним сообщением.', cancel_kb())
    await cb.answer()


async def save_api_key(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    await set_setting('polza_api_key', message.text.strip())
    await state.clear()
    await drop(message)  # ключ не должен оставаться в чате
    await show(message.bot, message.chat.id, ['Ключ сохранён.'], await settings_menu())


# ---------- контекст оценки ----------

async def ask_context(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(SettingsStates.context)
    await edit(
        cb,
        'Отправьте контекст для оценки: критерии, уровень, требования к произношению.',
        cancel_kb(),
    )
    await cb.answer()


async def save_context(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption
    if not text:
        return
    await set_setting('teacher_context', text)
    await state.clear()
    await drop(message)
    await show(message.bot, message.chat.id, ['Контекст сохранён.'], await settings_menu())


# ---------- отмена ----------

async def cancel_input(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, 'Настройки', await settings_menu())
    await cb.answer('Отменено')


def setup(router: Router) -> None:
    # Команды регистрируются первыми: они должны сбрасывать состояние ввода.
    router.message(CommandStart(), TeacherChatFilter())(open_menu)
    router.message(Command('menu'), TeacherChatFilter())(open_menu)

    router.callback_query(F.data == 'menu:main')(menu_main)
    router.callback_query(F.data == 'menu:settings')(menu_settings)
    router.callback_query(F.data == 'menu:status')(menu_status)
    router.callback_query(F.data == 'cfg:api')(ask_api_key)
    router.callback_query(F.data == 'cfg:ctx')(ask_context)
    router.callback_query(F.data == 'cfg:cancel')(cancel_input)

    router.message(SettingsStates.api_key, TeacherChatFilter())(save_api_key)
    router.message(SettingsStates.context, TeacherChatFilter())(save_context)

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from core.filters import TeacherChatFilter
from services.polza_key import KEY_INVALID, check_key
from services.screen import drop, show
from services.settings import set_setting
from services.teacher_context import save_context
from services.teacher_status import collect_status, render_settings_status

ROLES = {'main'}
PRIORITY = 10

POLZA_TOPUP_URL = 'https://polza.ai'
DROP_KEY_WARNING = 'Не удалось удалить сообщение с ключом. Удалите его вручную.'
INVALID_KEY_TEXT = 'Polza.ai отклонил ключ. Проверьте его и отправьте снова. Ключ не сохранён.'
PANEL_BUTTON_TEXT = 'Панель преподавателя'


class SettingsStates(StatesGroup):
    api_key = State()
    context = State()


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def teacher_app_url() -> str | None:
    '''Адрес панели преподавателя. Без HTTPS кнопка не показывается.'''
    url = config.WEBAPP_URL
    if not url or not url.startswith('https://'):
        return None
    return url.rstrip('/') + '/teacher'


async def guard(cb: CallbackQuery) -> bool:
    if is_admin(cb.from_user.id):
        return True
    await cb.answer('Нет доступа', show_alert=True)
    return False


async def edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await show(cb.bot, cb.message.chat.id, [text], markup, source_id=cb.message.message_id)


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    url = teacher_app_url()
    if url:
        kb.row(InlineKeyboardButton(text=PANEL_BUTTON_TEXT, web_app=WebAppInfo(url=url)))
    kb.button(text='Настройки', callback_data='menu:settings')
    kb.button(text='Статус', callback_data='menu:status')
    kb.button(text='Боты', callback_data='menu:bots')
    kb.button(text='Модели', callback_data='menu:models')
    kb.button(text='Задания', callback_data='menu:tasks')
    kb.button(text='Ученики', callback_data='menu:students')
    kb.button(text='Параметры ИИ', callback_data='menu:ai')
    kb.button(text='Цели и диалог', callback_data='menu:dialog')
    kb.button(text='Пополнить баланс', url=POLZA_TOPUP_URL)
    kb.adjust(2)
    return kb.as_markup()


def menu_hint() -> str:
    '''Пояснение в меню: почему кнопки панели нет, если WEBAPP_URL не задан или не HTTPS.'''
    if teacher_app_url() is None:
        return ('\n\nПанель преподавателя в Mini App недоступна: укажите HTTPS-адрес '
                '(WEBAPP_URL), запустите tunnel.bat.')
    return ''


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
    return render_settings_status(await collect_status())


async def open_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show(message.bot, message.chat.id, ['Главное меню' + menu_hint()], main_menu())
    await drop(message)


async def menu_main(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, 'Главное меню' + menu_hint(), main_menu())
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
    kb.button(text='Пополнить баланс', url=POLZA_TOPUP_URL)
    kb.button(text='Назад', callback_data='menu:main')
    kb.adjust(1)
    await edit(cb, await status_text(), kb.as_markup())
    await cb.answer()


async def ask_api_key(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(SettingsStates.api_key)
    await edit(cb, 'Отправьте ключ Polza.ai одним сообщением.', cancel_kb())
    await cb.answer()


async def save_api_key(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    key = message.text.strip()
    dropped = await drop(message)  # ключ не должен оставаться в чате
    verdict = await check_key(key)

    if verdict == KEY_INVALID:
        # Невалидный ключ не сохраняется; состояние сохраняется, можно отправить ключ снова
        text = INVALID_KEY_TEXT
        if not dropped:
            text += f'\n\nВнимание: {DROP_KEY_WARNING}'
        await show(message.bot, message.chat.id, [text], cancel_kb())
        return

    await set_setting('polza_api_key', key)
    await state.clear()
    text = 'Ключ сохранён.'
    if not dropped:
        text += f'\n\nВнимание: {DROP_KEY_WARNING}'
    await show(message.bot, message.chat.id, [text], await settings_menu())


async def ask_context(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(SettingsStates.context)
    await edit(
        cb,
        'Отправьте контекст для оценки: критерии, уровень и требования к ответам учеников.',
        cancel_kb(),
    )
    await cb.answer()


async def save_context_message(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption
    if not text:
        return
    await save_context(text)
    await state.clear()
    await drop(message)
    await show(message.bot, message.chat.id, ['Контекст сохранён.'], await settings_menu())


async def cancel_input(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, 'Настройки', await settings_menu())
    await cb.answer('Отменено')


def setup(router: Router) -> None:
    # Команды регистрируются первыми: они должны сбрасывать состояние ввода
    router.message(CommandStart(), TeacherChatFilter())(open_menu)
    router.message(Command('menu'), TeacherChatFilter())(open_menu)

    router.callback_query(F.data == 'menu:main')(menu_main)
    router.callback_query(F.data == 'menu:settings')(menu_settings)
    router.callback_query(F.data == 'menu:status')(menu_status)
    router.callback_query(F.data == 'cfg:api')(ask_api_key)
    router.callback_query(F.data == 'cfg:ctx')(ask_context)
    router.callback_query(F.data == 'cfg:cancel')(cancel_input)

    router.message(SettingsStates.api_key, TeacherChatFilter())(save_api_key)
    router.message(SettingsStates.context, TeacherChatFilter())(save_context_message)

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.config import config
from core.filters import TeacherChatFilter
from services.ai_settings import (
    CORRECTION_KEY,
    CORRECTION_LEVELS,
    CUSTOM_ROLE,
    CUSTOM_ROLE_MAX,
    DEFAULT_CORRECTION,
    DEFAULT_HISTORY,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_ROLE,
    DEFAULT_TEMPERATURE,
    HISTORY_KEY,
    HISTORY_OPTIONS,
    LANGUAGE_KEY,
    LANGUAGE_MODES,
    MAX_TOKENS_KEY,
    MAX_TOKENS_OPTIONS,
    ROLE_CUSTOM_KEY,
    ROLE_KEY,
    ROLE_PRESETS,
    TEMPERATURE_KEY,
    TEMPERATURE_OPTIONS,
    AiParams,
    load_ai_params,
)
from services.screen import drop, show
from services.settings import set_setting

ROLES = {'main'}
PRIORITY = 13

# callback «ai:cyc:<код>» переключает параметр по кругу
PARAM_CYCLES = {
    'temp': ('temperature', TEMPERATURE_KEY, TEMPERATURE_OPTIONS),
    'tokens': ('max_tokens', MAX_TOKENS_KEY, MAX_TOKENS_OPTIONS),
    'hist': ('history_limit', HISTORY_KEY, HISTORY_OPTIONS),
    'corr': ('correction', CORRECTION_KEY, tuple(CORRECTION_LEVELS)),
    'lang': ('reply_language', LANGUAGE_KEY, tuple(LANGUAGE_MODES)),
}

DEFAULTS = {
    ROLE_KEY: DEFAULT_ROLE,
    ROLE_CUSTOM_KEY: '',
    TEMPERATURE_KEY: str(DEFAULT_TEMPERATURE),
    MAX_TOKENS_KEY: str(DEFAULT_MAX_TOKENS),
    HISTORY_KEY: str(DEFAULT_HISTORY),
    CORRECTION_KEY: DEFAULT_CORRECTION,
    LANGUAGE_KEY: DEFAULT_LANGUAGE,
}


class AiStates(StatesGroup):
    custom_role = State()


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
    return InlineKeyboardMarkup(inline_keyboard=[[btn('Отмена', 'ai:cancel')]])


def _history_label(value: int) -> str:
    return 'выключена' if value == 0 else f'{value} реплик'


def home_text(params: AiParams, notice: str | None = None) -> str:
    lines = []
    if notice:
        lines += [notice, '']
    lines += [
        'Параметры ИИ',
        '',
        f'Роль ассистента: {params.role_name}',
        f'Температура: {params.temperature} (0 — точнее, 1.3 — разнообразнее)',
        f'Длина ответа: до {params.max_tokens} токенов',
        f'История диалога: {_history_label(params.history_limit)}',
        f'Исправления ошибок: {CORRECTION_LEVELS[params.correction][0]}',
        f'Язык ответов: {LANGUAGE_MODES[params.reply_language][0]}',
        '',
        'Нажмите параметр, чтобы переключить его. Изменения применяются к ответам сразу.',
    ]
    return '\n'.join(lines)


def home_menu(params: AiParams) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(f'Роль: {params.role_name}', 'ai:role')],
        [btn(f'Температура: {params.temperature}', 'ai:cyc:temp')],
        [btn(f'Длина ответа: {params.max_tokens}', 'ai:cyc:tokens')],
        [btn(f'История: {_history_label(params.history_limit)}', 'ai:cyc:hist')],
        [btn(f'Исправления: {CORRECTION_LEVELS[params.correction][0]}', 'ai:cyc:corr')],
        [btn(f'Язык: {LANGUAGE_MODES[params.reply_language][0]}', 'ai:cyc:lang')],
        [btn('Сбросить к умолчанию', 'ai:reset')],
        [btn('Назад', 'menu:main')],
    ])


async def show_home(bot, chat_id: int, *, notice: str | None = None,
                    source_id: int | None = None) -> None:
    params = await load_ai_params()
    await show(bot, chat_id, [home_text(params, notice)], home_menu(params), source_id=source_id)


async def render_roles(cb: CallbackQuery) -> None:
    params = await load_ai_params()
    rows = []
    for role_id, (name, _) in ROLE_PRESETS.items():
        mark = '✓ ' if params.role_id == role_id else ''
        rows.append([btn(mark + name, f'ai:pick:{role_id}')])
    mark = '✓ ' if params.role_id == CUSTOM_ROLE else ''
    rows.append([btn(mark + 'Своя роль', 'ai:custom')])
    rows.append([btn('Назад', 'menu:ai')])

    text = (
        'Роль ассистента\n\n'
        'Роль задаёт, как нейросеть общается с учениками. Ученики видят её в своём боте.\n\n'
        f'Сейчас: «{params.role_name}»\n{params.role_text}'
    )
    await edit(cb, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def open_home(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await show_home(cb.bot, cb.message.chat.id, source_id=cb.message.message_id)
    await cb.answer()


async def cycle(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    key = (cb.data or '').split(':')[-1]
    spec = PARAM_CYCLES.get(key)
    if spec is None:
        await cb.answer()
        return
    field, setting_key, options = spec
    params = await load_ai_params()
    current = getattr(params, field)
    idx = options.index(current) if current in options else -1
    value = options[(idx + 1) % len(options)]
    await set_setting(setting_key, str(value))
    await show_home(cb.bot, cb.message.chat.id, source_id=cb.message.message_id)
    await cb.answer('Сохранено')


async def reset(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    for key, value in DEFAULTS.items():
        await set_setting(key, value)
    await show_home(cb.bot, cb.message.chat.id,
                    notice='Параметры сброшены к значениям по умолчанию.',
                    source_id=cb.message.message_id)
    await cb.answer()


async def role_page(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    await render_roles(cb)
    await cb.answer()


async def pick_role(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    role_id = (cb.data or '').split(':')[-1]
    if role_id not in ROLE_PRESETS:
        await cb.answer()
        return
    await set_setting(ROLE_KEY, role_id)
    await render_roles(cb)
    await cb.answer(f'Роль: {ROLE_PRESETS[role_id][0]}')


async def ask_custom(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.set_state(AiStates.custom_role)
    await edit(
        cb,
        f'Отправьте описание роли одним сообщением (до {CUSTOM_ROLE_MAX} символов).\n\n'
        'Например: «Ты помогаешь готовиться к собеседованию на английском. '
        'Задавай вопросы как интервьюер».',
        cancel_kb(),
    )
    await cb.answer()


async def custom_input(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    await drop(message)
    if not text or len(text) > CUSTOM_ROLE_MAX:
        await show(message.bot, message.chat.id,
                   [f'Описание должно быть от 1 до {CUSTOM_ROLE_MAX} символов. Попробуйте ещё раз.'],
                   cancel_kb())
        return
    await set_setting(ROLE_KEY, CUSTOM_ROLE)
    await set_setting(ROLE_CUSTOM_KEY, text)
    await state.clear()
    await show_home(message.bot, message.chat.id, notice='Своя роль сохранена.')


async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await show_home(cb.bot, cb.message.chat.id, source_id=cb.message.message_id)
    await cb.answer('Отменено')


def setup(router: Router) -> None:
    router.callback_query(F.data == 'menu:ai')(open_home)
    router.callback_query(F.data == 'ai:role')(role_page)
    router.callback_query(F.data.startswith('ai:pick:'))(pick_role)
    router.callback_query(F.data == 'ai:custom')(ask_custom)
    router.callback_query(F.data.startswith('ai:cyc:'))(cycle)
    router.callback_query(F.data == 'ai:reset')(reset)
    router.callback_query(F.data == 'ai:cancel')(cancel)

    router.message(AiStates.custom_role, TeacherChatFilter())(custom_input)

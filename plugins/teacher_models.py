import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.config import config
from services.polza_models import (
    CATEGORY_TITLES,
    DEFAULT_SORT,
    ROLE_CATEGORIES,
    ROLE_SETTING,
    ROLE_TITLES,
    SORT_DESCRIPTIONS,
    SORT_MODES,
    SORT_TITLES,
    PolzaModel,
    format_prices,
    get_models,
    sort_models,
)
from services.screen import show
from services.settings import get_setting
from services.teacher_models_view import (
    PAGE_SIZE,
    build_all_chunks,
    clamp_page,
    normalize_sort,
    picked_items,
    picker_key,
    remember_picker,
)

ROLES = {'main'}
PRIORITY = 16


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


def _label(value: str | None) -> str:
    return value or 'не выбрана (модель по умолчанию)'


async def _models_or_alert(cb: CallbackQuery, force: bool = False) -> list[PolzaModel] | None:
    key = await get_setting('polza_api_key')
    if not key:
        await cb.answer('Сначала задайте ключ Polza.ai в настройках', show_alert=True)
        return None
    try:
        return await get_models(key, force=force)
    except (httpx.HTTPError, ValueError):
        await cb.answer('Не удалось получить список моделей', show_alert=True)
        return None


async def home_text() -> str:
    text_model = await get_setting(ROLE_SETTING['text'])
    speech_model = await get_setting(ROLE_SETTING['speech'])
    text = (
        'Модели Polza.ai\n\n'
        f'Анализ текста: {_label(text_model)}\n'
        f'Анализ голоса: {_label(speech_model)}\n\n'
        'Выберите роль, чтобы сменить модель, или откройте полный список с ценами.'
    )
    if not await get_setting('polza_api_key'):
        text += '\n\nВнимание: ключ Polza.ai не задан. Задайте его в «Настройки».'
    return text


def home_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn('Анализ текста', 'models:role:text')],
        [btn('Анализ голоса', 'models:role:speech')],
        [btn('Все модели и цены', 'models:all')],
        [btn('Обновить список', 'models:refresh')],
        [btn('Назад', 'menu:main')],
    ])


async def models_home(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await edit(cb, await home_text(), home_menu())
    await cb.answer()


async def role_categories(cb: CallbackQuery, role: str) -> None:
    models = await _models_or_alert(cb)
    if models is None:
        return

    rows = []
    for category in ROLE_CATEGORIES[role]:
        count = sum(1 for m in models if m.category == category)
        rows.append([btn(
            f'{CATEGORY_TITLES[category]} · {count}',
            f'models:cat:{role}:{category}:0:{DEFAULT_SORT}',
        )])
    rows.append([btn('Назад', 'menu:models')])

    current = await get_setting(ROLE_SETTING[role])
    text = (
        f'{ROLE_TITLES[role]}\n'
        f'Текущая модель: {_label(current)}\n\n'
        'Выберите категорию моделей.'
    )
    await edit(cb, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


async def category_page(cb: CallbackQuery, role: str, category: str, page: int,
                        sort: str = DEFAULT_SORT, note: str | None = None) -> None:
    models = await _models_or_alert(cb)
    if models is None:
        return

    sort = normalize_sort(sort)
    items = sort_models([m for m in models if m.category == category], sort)
    remember_picker(picker_key(role, category, sort), items)

    page, pages = clamp_page(page, len(items))
    start = page * PAGE_SIZE

    rows = []
    for idx in range(start, min(start + PAGE_SIZE, len(items))):
        model = items[idx]
        rows.append([btn(f'{model.name[:30]} · {format_prices(model)}',
                         f'models:set:{role}:{category}:{sort}:{idx}')])

    nav = []
    if page > 0:
        nav.append(btn('<', f'models:cat:{role}:{category}:{page - 1}:{sort}'))
    if page < pages - 1:
        nav.append(btn('>', f'models:cat:{role}:{category}:{page + 1}:{sort}'))
    if nav:
        rows.append(nav)

    rows.append([
        btn(('✓ ' if mode == sort else '') + SORT_TITLES[mode],
            f'models:cat:{role}:{category}:0:{mode}')
        for mode in SORT_MODES
    ])
    rows.append([btn('Назад', f'models:role:{role}')])

    current = await get_setting(ROLE_SETTING[role])
    text = (
        f'{CATEGORY_TITLES[category]}\n'
        f'{ROLE_TITLES[role]}, текущая: {_label(current)}\n'
        f'Сортировка: {SORT_DESCRIPTIONS[sort]}\n'
        f'Страница {page + 1}/{pages}. Цена: вход / выход за 1M токенов.'
    )
    if not items:
        text += '\n\nВ этой категории моделей нет.'

    await edit(cb, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer(note)


async def pick_model(cb: CallbackQuery, role: str, category: str, sort: str, idx: int) -> None:
    from services.settings import set_setting

    sort = normalize_sort(sort)
    items = picked_items(picker_key(role, category, sort))
    if items is None or idx >= len(items):
        # Список устарел (например, после перезапуска): перечитываем страницу
        await category_page(cb, role, category, 0, sort, note='Список обновлён, выберите снова')
        return

    model = items[idx]
    await set_setting(ROLE_SETTING[role], model.id)
    await category_page(cb, role, category, idx // PAGE_SIZE, sort,
                        note=f'Выбрано: {model.name}'[:200])


async def show_all(cb: CallbackQuery) -> None:
    models = await _models_or_alert(cb)
    if models is None:
        return

    chunks = build_all_chunks(models)
    back = InlineKeyboardMarkup(inline_keyboard=[[btn('К моделям', 'menu:models')]])

    await cb.answer()
    await show(cb.bot, cb.message.chat.id, chunks, back, source_id=cb.message.message_id)


async def refresh(cb: CallbackQuery) -> None:
    models = await _models_or_alert(cb, force=True)
    if models is None:
        return
    await edit(cb, await home_text(), home_menu())
    await cb.answer('Список обновлён')


async def dispatch(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    parts = (cb.data or '').split(':')
    action = parts[1] if len(parts) > 1 else ''

    if action == 'role' and len(parts) == 3:
        await role_categories(cb, parts[2])
    elif action == 'cat' and len(parts) == 6:
        await category_page(cb, parts[2], parts[3], int(parts[4]), parts[5])
    elif action == 'set' and len(parts) == 6:
        await pick_model(cb, parts[2], parts[3], parts[4], int(parts[5]))
    elif action == 'all':
        await show_all(cb)
    elif action == 'refresh':
        await refresh(cb)
    else:
        await cb.answer()


def setup(router: Router) -> None:
    router.callback_query(F.data == 'menu:models')(models_home)
    router.callback_query(F.data.startswith('models:'))(dispatch)

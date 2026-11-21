'''Вид списка моделей Polza.ai: страницы, сортировка, кеш выбора, разбиение длинного текста.

Сортировка и категории приходят из services/polza_models. Здесь — то, что нужно и боту, и API.
'''
from __future__ import annotations

import math

from services.polza_models import (
    CATEGORY_ORDER,
    CATEGORY_TITLES,
    DEFAULT_SORT,
    ROLE_SETTING,
    SORT_MODES,
    PolzaModel,
    format_prices,
)
from services.settings import set_setting

PAGE_SIZE = 8
ALL_VIEW_LIMIT = 25
MAX_MESSAGE = 3500

# Кеш страниц выбора: ключ "role:category:sort" -> отсортированный список.
# Индексы callback ссылаются сюда, поэтому список хранится между нажатиями
_picker: dict[str, list[PolzaModel]] = {}


def normalize_sort(raw: str) -> str:
    return raw if raw in SORT_MODES else DEFAULT_SORT


def picker_key(role: str, category: str, sort: str) -> str:
    return f'{role}:{category}:{sort}'


def remember_picker(key: str, items: list[PolzaModel]) -> None:
    _picker[key] = items


def picked_items(key: str) -> list[PolzaModel] | None:
    return _picker.get(key)


def clamp_page(page: int, total: int) -> tuple[int, int]:
    '''Возвращает (номер страницы в допустимых пределах, всего страниц).'''
    pages = max(1, math.ceil(total / PAGE_SIZE))
    return max(0, min(page, pages - 1)), pages


def split_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ''
    for line in text.split('\n'):
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current.rstrip())
            current = ''
        current += line + '\n'
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or ['']


def build_all_chunks(models: list[PolzaModel]) -> list[str]:
    '''Полный список моделей с ценами, разбитый на сообщения под лимит Telegram.'''
    lines = [
        'Модели Polza.ai и цены',
        'Цены за 1M токенов: вход / выход',
        '',
    ]
    for category in CATEGORY_ORDER:
        items = sorted((m for m in models if m.category == category), key=lambda m: m.name.lower())
        if not items:
            continue
        lines.append(f'{CATEGORY_TITLES[category]} ({len(items)})')
        for model in items[:ALL_VIEW_LIMIT]:
            lines.append(f'• {model.id} — {format_prices(model)}')
        if len(items) > ALL_VIEW_LIMIT:
            lines.append(
                f'… и ещё {len(items) - ALL_VIEW_LIMIT}. '
                'Полный выбор — через «Анализ текста» или «Анализ голоса».'
            )
        lines.append('')
    return split_text('\n'.join(lines), MAX_MESSAGE)


async def reset_model(role: str) -> None:
    '''Сбрасывает модель роли на пустое значение: используется модель по умолчанию.'''
    await set_setting(ROLE_SETTING[role], '')

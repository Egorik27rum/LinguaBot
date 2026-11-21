'''Правила названий и условий заданий преподавателя.'''
from __future__ import annotations

TITLE_MAX = 100
CONTENT_MAX = 2000


def normalize_title(raw: str | None) -> str:
    return ' '.join((raw or '').split())


def normalize_content(raw: str | None) -> str:
    return (raw or '').strip()


def title_error(title: str) -> str | None:
    if 1 <= len(title) <= TITLE_MAX:
        return None
    return f'Название должно быть от 1 до {TITLE_MAX} символов. Попробуйте ещё раз.'


def content_error(content: str) -> str | None:
    if 1 <= len(content) <= CONTENT_MAX:
        return None
    return f'Условие должно быть от 1 до {CONTENT_MAX} символов. Попробуйте ещё раз.'

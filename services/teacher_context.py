'''Контекст для оценки: требования преподавателя, которые получает нейросеть.

Хранится в settings под ключом teacher_context. Лимит CONTEXT_MAX используется Mini App;
бот сохраняет текст без ограничения, как и раньше.
'''
from services.settings import get_setting, set_setting

CONTEXT_KEY = 'teacher_context'
CONTEXT_MAX = 2000


async def load_context() -> str:
    return await get_setting(CONTEXT_KEY) or ''


async def save_context(text: str) -> None:
    await set_setting(CONTEXT_KEY, text)

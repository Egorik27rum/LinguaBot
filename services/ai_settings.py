'''Параметры ИИ, которые задаёт преподаватель. Значения хранятся в settings.
Некорректное или отсутствующее значение заменяется значением по умолчанию.
'''
from dataclasses import dataclass

from services.settings import get_setting

ROLE_KEY = 'ai_role'
ROLE_CUSTOM_KEY = 'ai_role_custom'
TEMPERATURE_KEY = 'ai_temperature'
MAX_TOKENS_KEY = 'ai_max_tokens'
HISTORY_KEY = 'ai_history_limit'
CORRECTION_KEY = 'ai_correction'
LANGUAGE_KEY = 'ai_reply_language'

CUSTOM_ROLE = 'custom'
CUSTOM_ROLE_MAX = 600

ROLE_PRESETS: dict[str, tuple[str, str]] = {
    'friend': (
        'Дружелюбный наставник',
        'Ты дружелюбный наставник по английскому языку. Хвали прогресс ученика, '
        'мягко исправляй ошибки и коротко объясняй правило.',
    ),
    'examiner': (
        'Строгий экзаменатор',
        'Ты строгий экзаменатор. Указывай на ошибки прямо, оценивай точность и полноту ответа, '
        'не смягчай формулировки.',
    ),
    'conversation': (
        'Собеседник',
        'Ты собеседник для разговорной практики. Поддерживай живой диалог и задавай встречные вопросы. '
        'Исправления давай коротко, в конце ответа.',
    ),
    'proofreader': (
        'Корректор',
        'Ты корректор текстов. Находи ошибки в грамматике, лексике и стиле и предлагай исправленный вариант.',
    ),
}
DEFAULT_ROLE = 'friend'

TEMPERATURE_OPTIONS = (0.0, 0.3, 0.7, 1.0, 1.3)
DEFAULT_TEMPERATURE = 0.7
MAX_TOKENS_OPTIONS = (300, 500, 800, 1200, 2000)
DEFAULT_MAX_TOKENS = 800
HISTORY_OPTIONS = (0, 5, 10, 20, 40)
DEFAULT_HISTORY = 20

CORRECTION_LEVELS: dict[str, tuple[str, str]] = {
    'soft': ('Мягко', 'Исправляй только заметные ошибки, без придирок.'),
    'normal': ('Обычно', 'Исправляй основные ошибки и кратко объясняй правило.'),
    'strict': ('Строго', 'Находи и исправляй все ошибки и указывай их тип: грамматика, лексика, орфография.'),
}
DEFAULT_CORRECTION = 'normal'

LANGUAGE_MODES: dict[str, tuple[str, str]] = {
    'auto': ('Как пишет ученик', 'Отвечай на том языке, на котором пишет ученик.'),
    'ru': ('Объяснения на русском', 'Объяснения давай на русском языке, примеры и фразы на английском.'),
    'en': ('Только английский', 'Отвечай только на английском языке.'),
}
DEFAULT_LANGUAGE = 'auto'

BASE_RULES = (
    'Ты ассистент по изучению английского языка. Отвечай понятно и по делу. '
    'Опирайся на задание и требования преподавателя, если они заданы.'
)


@dataclass(frozen=True)
class AiParams:
    role_id: str
    role_name: str
    role_text: str
    temperature: float
    max_tokens: int
    history_limit: int
    correction: str
    reply_language: str

    def instructions(self) -> str:
        return '\n'.join([
            BASE_RULES,
            self.role_text,
            CORRECTION_LEVELS[self.correction][1],
            LANGUAGE_MODES[self.reply_language][1],
        ])


def _option(raw: str | None, options: tuple, default):
    '''Сравнивает строку из БД с допустимыми значениями.'''
    if raw is None:
        return default
    raw = raw.strip()
    for option in options:
        if str(option) == raw:
            return option
    return default


async def load_ai_params() -> AiParams:
    role_id = (await get_setting(ROLE_KEY) or DEFAULT_ROLE).strip()
    if role_id == CUSTOM_ROLE:
        custom = (await get_setting(ROLE_CUSTOM_KEY) or '').strip()
        role_name, role_text = 'Своя роль', custom or ROLE_PRESETS[DEFAULT_ROLE][1]
    elif role_id in ROLE_PRESETS:
        role_name, role_text = ROLE_PRESETS[role_id]
    else:
        role_id = DEFAULT_ROLE
        role_name, role_text = ROLE_PRESETS[DEFAULT_ROLE]

    correction = (await get_setting(CORRECTION_KEY) or '').strip()
    language = (await get_setting(LANGUAGE_KEY) or '').strip()

    return AiParams(
        role_id=role_id,
        role_name=role_name,
        role_text=role_text,
        temperature=_option(await get_setting(TEMPERATURE_KEY), TEMPERATURE_OPTIONS, DEFAULT_TEMPERATURE),
        max_tokens=_option(await get_setting(MAX_TOKENS_KEY), MAX_TOKENS_OPTIONS, DEFAULT_MAX_TOKENS),
        history_limit=_option(await get_setting(HISTORY_KEY), HISTORY_OPTIONS, DEFAULT_HISTORY),
        correction=correction if correction in CORRECTION_LEVELS else DEFAULT_CORRECTION,
        reply_language=language if language in LANGUAGE_MODES else DEFAULT_LANGUAGE,
    )

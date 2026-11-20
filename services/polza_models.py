import logging
import math
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = 'https://polza.ai/api'
MODELS_PATH = '/v1/models'
REQUEST_HEADERS = {'accept-language': 'ru'}
CACHE_TTL = 600
PRICE_UNIT = '₽'

CATEGORY_ORDER = ('speech', 'multimodal', 'text', 'voice', 'other')
CATEGORY_TITLES = {
    'speech': 'Расшифровка голоса (STT)',
    'multimodal': 'Голос + текст (мультимодальные)',
    'text': 'Анализ текста (LLM)',
    'voice': 'Голос (TTS, аудио на выходе)',
    'other': 'Прочие',
}

ROLE_CATEGORIES = {
    'text': ('text', 'multimodal'),
    'speech': ('speech', 'multimodal'),
}
ROLE_SETTING = {
    'text': 'model_text',
    'speech': 'model_speech',
}
ROLE_TITLES = {
    'text': 'Анализ текста',
    'speech': 'Анализ голоса',
}

SORT_MODES = ('rec', 'desc', 'asc')
DEFAULT_SORT = 'rec'
SORT_TITLES = {'rec': 'Рекоменд.', 'desc': 'Цена ↓', 'asc': 'Цена ↑'}
SORT_DESCRIPTIONS = {
    'rec': 'рекомендуемые: лучшее соотношение цены и контекста',
    'desc': 'сначала дорогие',
    'asc': 'сначала дешёвые',
}
DEFAULT_CONTEXT_TOKENS = 8000
RECOMMENDED_CONTEXT_CAP = 128_000
MIN_RECOMMENDED_CONTEXT = 8000
SHORT_CONTEXT_PENALTY = 0.25
RECOMMENDED_COST_FLOOR = 0.1


@dataclass(frozen=True)
class PolzaModel:
    id: str
    name: str
    category: str
    price_in: float | None
    price_out: float | None
    price_note: str | None = None
    context_length: int | None = None


_cache: dict[str, Any] = {'at': 0.0, 'models': []}


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_context(item: dict[str, Any]) -> int | None:
    raw = item.get('context_length') or (item.get('top_provider') or {}).get('context_length')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def categorize(item: dict[str, Any]) -> str:
    '''Категория по полю type, а для чат-моделей — по модальностям.'''
    model_type = str(item.get('type') or '').lower()
    arch = item.get('architecture') or {}
    inputs = set(arch.get('input_modalities') or [])
    outputs = set(arch.get('output_modalities') or [])

    if model_type == 'stt':
        return 'speech'
    if model_type == 'tts':
        return 'voice'
    if model_type == 'audio':
        return 'voice'
    if model_type == 'chat':
        if 'audio' in outputs:
            return 'voice'
        if 'audio' in inputs and 'text' in inputs:
            return 'multimodal'
        if 'audio' in inputs:
            return 'speech'
        return 'text'
    return 'other'


def _pricing(item: dict[str, Any]) -> dict[str, Any]:
    top = item.get('top_provider') or {}
    pricing = top.get('pricing') or {}
    if not pricing:
        providers = item.get('providers') or []
        if providers and isinstance(providers[0], dict):
            pricing = providers[0].get('pricing') or {}
    return pricing


def parse_model(item: dict[str, Any]) -> PolzaModel | None:
    model_id = item.get('id')
    if not model_id:
        return None

    category = categorize(item)
    pricing = _pricing(item)

    note = None
    if category == 'speech' and _to_float(pricing.get('stt_per_minute')) is not None:
        note = f"{_to_float(pricing.get('stt_per_minute')):.2f} {PRICE_UNIT}/мин"
    elif category == 'voice' and _to_float(pricing.get('tts_per_million_characters')) is not None:
        note = f"{_to_float(pricing.get('tts_per_million_characters')):.2f} {PRICE_UNIT}/1M симв."

    return PolzaModel(
        id=str(model_id),
        name=str(item.get('name') or model_id),
        category=category,
        price_in=_to_float(pricing.get('prompt_per_million')),
        price_out=_to_float(pricing.get('completion_per_million')),
        price_note=note,
        context_length=_parse_context(item),
    )


async def fetch_models(api_key: str | None = None) -> list[PolzaModel]:
    headers = dict(REQUEST_HEADERS)
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(BASE_URL + MODELS_PATH, headers=headers)
        response.raise_for_status()
        payload = response.json()

    items = payload.get('data', []) if isinstance(payload, dict) else payload
    models = [parse_model(i) for i in items if isinstance(i, dict)]
    return sorted((m for m in models if m), key=lambda m: m.id)


async def get_models(api_key: str | None = None, force: bool = False) -> list[PolzaModel]:
    '''Список моделей с кешем на CACHE_TTL. Ошибки сети пробрасываются наружу.'''
    now = time.monotonic()
    if not force and _cache['models'] and now - _cache['at'] < CACHE_TTL:
        return _cache['models']
    models = await fetch_models(api_key)
    _cache['at'] = now
    _cache['models'] = models
    return models


def total_price(model: PolzaModel) -> float | None:
    '''Сумма цен за 1M входных и выходных токенов. None, если цены за токен не заданы.'''
    if model.price_in is None and model.price_out is None:
        return None
    return (model.price_in or 0.0) + (model.price_out or 0.0)


def recommended_score(model: PolzaModel) -> float | None:
    '''Соотношение качества и цены для студентов.

    Качество: размер контекста линейно до RECOMMENDED_CONTEXT_CAP, короткий контекст штрафуется.
    Цена: входная плюс удвоенная выходная, так как ответы ученику генерируют много выходных токенов.
    '''
    if model.price_in is None and model.price_out is None:
        return None
    cost = (model.price_in or 0.0) + 2 * (model.price_out or 0.0)
    context = model.context_length or DEFAULT_CONTEXT_TOKENS
    quality = min(context, RECOMMENDED_CONTEXT_CAP) / RECOMMENDED_CONTEXT_CAP
    if context < MIN_RECOMMENDED_CONTEXT:
        quality *= SHORT_CONTEXT_PENALTY
    return quality / (cost + RECOMMENDED_COST_FLOOR)


def sort_models(models: list[PolzaModel], mode: str) -> list[PolzaModel]:
    '''Сортирует модели. Модели без цены за токен всегда уходят в конец списка.'''
    if mode == 'desc':
        return sorted(models, key=lambda m: (
            total_price(m) is None, -(total_price(m) or 0.0), m.name.lower(),
        ))
    if mode == 'asc':
        return sorted(models, key=lambda m: (
            total_price(m) is None, total_price(m) or 0.0, m.name.lower(),
        ))
    return sorted(models, key=lambda m: (
        recommended_score(m) is None, -(recommended_score(m) or 0.0), m.name.lower(),
    ))


def _fmt(value: float | None) -> str:
    if value is None:
        return '—'
    if value == 0 or value >= 0.01:
        return f'{value:.2f}'
    return f'{value:.4f}'


def format_prices(model: PolzaModel) -> str:
    if model.price_in is None and model.price_out is None:
        return model.price_note or 'цена не указана'
    text = f'вход {_fmt(model.price_in)} / выход {_fmt(model.price_out)} {PRICE_UNIT}'
    if model.price_note:
        text += f' · {model.price_note}'
    return text

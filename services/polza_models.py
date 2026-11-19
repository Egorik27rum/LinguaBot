import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = 'https://polza.ai/api'
MODELS_PATH = '/v1/models'
REQUEST_HEADERS = {'accept-language': 'ru'}
CACHE_TTL = 600  # секунд
PRICE_UNIT = '₽'

CATEGORY_ORDER = ('speech', 'multimodal', 'text', 'voice', 'other')
CATEGORY_TITLES = {
    'speech': '🎙 Расшифровка голоса (STT)',
    'multimodal': '🧩 Голос + текст (мультимодальные)',
    'text': '📝 Анализ текста (LLM)',
    'voice': '🔊 Голос (TTS, аудио на выходе)',
    'other': '📦 Прочие',
}

# Какие категории подходят для каждой роли в боте
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


@dataclass(frozen=True)
class PolzaModel:
    id: str
    name: str
    category: str
    price_in: float | None   # ₽ за 1M входных токенов
    price_out: float | None  # ₽ за 1M выходных токенов
    price_note: str | None = None  # например, ₽/мин для STT или ₽/1M символов для TTS


_cache: dict[str, Any] = {'at': 0.0, 'models': []}


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

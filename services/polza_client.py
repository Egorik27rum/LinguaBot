import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Замените на актуальный id модели из списка моделей Polza.ai, если нужно
DEFAULT_CHAT_MODEL = 'openai/gpt-4o-mini'


class PolzaClient:
    def __init__(self):
        self.base_url = 'https://api.polza.ai/v1'

    async def analyze_speech(self, api_key: str, file_content: bytes,
                             task_text: str, context: str = '',
                             model: str | None = None) -> Optional[Dict[str, Any]]:
        headers = {'Authorization': f'Bearer {api_key}'}
        files = {'file': ('voice.ogg', file_content, 'audio/ogg')}
        data = {'reference_text': task_text, 'context': context}
        if model:
            data['model'] = model
        return await self._post('/analyze', headers, files=files, data=data)

    async def analyze_text(self, api_key: str, text: str,
                           task_text: str, context: str = '',
                           model: str | None = None) -> Optional[Dict[str, Any]]:
        # Эндпоинт для текстовой проверки уточните в документации Polza.ai
        headers = {'Authorization': f'Bearer {api_key}'}
        payload = {'text': text, 'reference_text': task_text, 'context': context}
        if model:
            payload['model'] = model
        return await self._post('/analyze/text', headers, json=payload)

    async def chat(self, api_key: str, messages: list[dict[str, str]],
                   model: str | None = None) -> Optional[str]:
        '''Диалог с нейросетью (OpenAI-совместимый формат). Возвращает текст ответа или None.'''
        headers = {'Authorization': f'Bearer {api_key}'}
        payload = {'model': model or DEFAULT_CHAT_MODEL, 'messages': messages}
        data = await self._post('/chat/completions', headers, json=payload)
        if not data:
            return None
        try:
            content = data['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            logger.error('Polza.ai: неожиданный формат ответа чата')
            return None
        content = (content or '').strip()
        return content or None

    async def _post(self, path: str, headers: dict, **kwargs) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(f'{self.base_url}{path}', headers=headers, **kwargs)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f'Polza.ai API Error: {e}')
                return None

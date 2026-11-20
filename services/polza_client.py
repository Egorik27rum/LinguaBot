import base64
import json
import logging
import math
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = 'https://polza.ai/api/v1'
DEFAULT_CHAT_MODEL = 'openai/gpt-4o-mini'
DEFAULT_STT_MODEL = 'openai/whisper-1'
GRADE_TEMPERATURE = 0.2
GRADE_MAX_TOKENS = 1200
TRANSCRIPT_LIMIT = 20000  # символов; при превышении берётся конец диалога
SCORE_MIN = 1
SCORE_MAX = 5
FEEDBACK_MAX = 1500
LIST_ITEM_MAX = 200
LIST_MAX = 10

GRADE_SYSTEM_PROMPT = (
    'Ты преподаватель английского языка. Тебе дан весь диалог ученика с нейросетью по заданию. '
    'Оцени, насколько ученик справился с заданием, по шкале от 1 до 5: 5 — отлично, 1 — почти не справился. '
    'Учитывай требования преподавателя. Верни только JSON-объект вида '
    '{"score": целое число от 1 до 5, "feedback": "краткий разбор на русском"}.'
)

GOAL_PROMPT_BLOCK = (
    'Дополнительно сверь диалог с целью и критериями проверки. Добавь в JSON поле "goal" вида '
    '{"achieved": true или false, "done": ["что выполнено"], "missed": ["что не выполнено"]}. '
    'Поле score выставляй с учётом критериев режима. Других полей не добавляй.'
)


def _mask_key(text: str, headers: dict) -> str:
    '''Заменяет ключ Polza.ai из заголовка Authorization на *** в тексте ошибки.'''
    auth = str(headers.get('Authorization', ''))
    secret = auth[len('Bearer '):] if auth.startswith('Bearer ') else ''
    return text.replace(secret, '***') if secret else text


def _strip_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.strip('`').removeprefix('json').strip()
    return cleaned


def _to_score(raw: Any) -> int | None:
    '''Только числа. Дробное значение округляется половины вверх, результат ограничивается 1–5.'''
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if isinstance(raw, float) and not math.isfinite(raw):
        return None
    return max(SCORE_MIN, min(SCORE_MAX, math.floor(raw + 0.5)))


def _str_list(raw: Any) -> list[str] | None:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    items: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None
        text = item.strip()
        if text:
            items.append(text[:LIST_ITEM_MAX])
    return items[:LIST_MAX]


def _parse_grade(content: str, with_goal: bool) -> Optional[dict[str, Any]]:
    '''Строгий разбор итоговой оценки. None, если формат неверный.
    При with_goal обязателен блок goal: без него оценка не выставляется.
    '''
    try:
        data = json.loads(_strip_fence(content))
    except json.JSONDecodeError:
        logger.error('Polza.ai: модель вернула не JSON при итоговой оценке')
        return None
    if not isinstance(data, dict):
        return None

    score = _to_score(data.get('score'))
    feedback = data.get('feedback')
    if score is None or not isinstance(feedback, str):
        logger.error('Polza.ai: в ответе нет корректной оценки или разбора')
        return None

    result: dict[str, Any] = {
        'score': score,
        'feedback': feedback.strip()[:FEEDBACK_MAX],
        'goal_achieved': None,
        'goal_done': [],
        'goal_missed': [],
    }
    if with_goal:
        goal = data.get('goal')
        if not isinstance(goal, dict) or not isinstance(goal.get('achieved'), bool):
            logger.error('Polza.ai: в ответе нет корректного блока цели')
            return None
        done = _str_list(goal.get('done'))
        missed = _str_list(goal.get('missed'))
        if done is None or missed is None:
            logger.error('Polza.ai: списки выполненных частей цели имеют неверный формат')
            return None
        result.update(goal_achieved=goal['achieved'], goal_done=done, goal_missed=missed)
    return result


def _transcript(dialog: list[dict[str, str]]) -> str:
    lines = []
    for item in dialog:
        name = 'Ученик' if item.get('role') == 'user' else 'Ассистент'
        lines.append(f"{name}: {item.get('content', '')}")
    return '\n\n'.join(lines)[-TRANSCRIPT_LIMIT:]


class PolzaClient:
    def __init__(self):
        self.base_url = BASE_URL

    async def chat(self, api_key: str, messages: list[dict[str, str]],
                   model: str | None = None,
                   temperature: float | None = None,
                   max_tokens: int | None = None,
                   json_mode: bool = False) -> Optional[str]:
        headers = {'Authorization': f'Bearer {api_key}'}
        payload: dict[str, Any] = {'model': model or DEFAULT_CHAT_MODEL, 'messages': messages}
        if temperature is not None:
            payload['temperature'] = temperature
        if max_tokens is not None:
            payload['max_tokens'] = max_tokens
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}
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

    async def transcribe(self, api_key: str, audio: bytes,
                         model: str | None = None,
                         mime: str = 'audio/ogg') -> Optional[str]:
        '''Распознавание речи (Speech-to-Text). Возвращает расшифровку или None.'''
        headers = {'Authorization': f'Bearer {api_key}'}
        encoded = base64.b64encode(audio).decode('ascii')
        payload = {
            'model': model or DEFAULT_STT_MODEL,
            'file': f'data:{mime};base64,{encoded}',
            'response_format': 'json',
        }
        data = await self._post('/audio/transcriptions', headers, json=payload)
        if not data:
            return None
        text = str(data.get('text') or '').strip()
        return text or None

    async def grade_dialog(self, api_key: str, dialog: list[dict[str, str]], task_text: str,
                           context: str = '', goal_text: str | None = None,
                           goal_criteria: str | None = None,
                           model: str | None = None) -> Optional[dict[str, Any]]:
        '''Итоговая оценка диалога по шкале 1–5. С целью добавляется блок goal.
        Возвращает разобранный результат или None.
        '''
        if not dialog:
            return None
        with_goal = bool(goal_text and goal_criteria)
        system = GRADE_SYSTEM_PROMPT + (f'\n\n{GOAL_PROMPT_BLOCK}' if with_goal else '')

        requirements = context or 'не заданы'
        task = task_text or 'не задано'
        user_message = f'Требования преподавателя:\n{requirements}\n\nЗадание:\n{task}\n\n'
        if with_goal:
            user_message += f'Цель диалога:\n{goal_text}\n\nКритерии проверки:\n{goal_criteria}\n\n'
        user_message += f'Диалог:\n{_transcript(dialog)}'

        content = await self.chat(
            api_key,
            [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_message},
            ],
            model=model,
            temperature=GRADE_TEMPERATURE,
            max_tokens=GRADE_MAX_TOKENS,
            json_mode=True,
        )
        if not content:
            return None
        return _parse_grade(content, with_goal)

    async def _post(self, path: str, headers: dict, **kwargs) -> Optional[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(f'{self.base_url}{path}', headers=headers, **kwargs)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                # Текст ошибки может содержать ключ, поэтому маскируем его
                logger.error('Polza.ai API Error (%s): %s',
                             type(e).__name__, _mask_key(str(e), headers))
                return None

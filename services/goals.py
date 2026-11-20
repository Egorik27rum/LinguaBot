'''Цели диалога и режимы проверки.

Цели хранятся в таблице goals. Активная цель — id в settings под ключом active_goal_id:
- записи нет или '0': цель не задана, проверка по цели пропускается;
- число: id активной цели.
Режим проверки хранится в settings под ключом goal_strictness.
Некорректное значение заменяется значением по умолчанию.
'''
from dataclasses import dataclass

from sqlalchemy import select

from database.engine import async_session
from database.models import Goal
from services.settings import get_setting, set_setting

ACTIVE_GOAL_KEY = 'active_goal_id'
GOAL_MODE_KEY = 'goal_strictness'
GOAL_TEXT_MAX = 500


@dataclass(frozen=True)
class GoalMode:
    title: str
    criteria: str
    cap: int  


GOAL_MODES: dict[str, GoalMode] = {
    'soft': GoalMode(
        title='мягкий',
        criteria=(
            'Достаточно, чтобы ученик понял и выполнил основную идею цели. '
            'Мелкие ошибки в формулировках и неточности не учитываются.'
        ),
        cap=4,
    ),
    'normal': GoalMode(
        title='обычный',
        criteria=(
            'Основные элементы цели обязательны: каждый должен прозвучать в диалоге, пусть и в простой форме. '
            'Ошибки в формулировках допустимы, если смысл понятен.'
        ),
        cap=3,
    ),
    'strict': GoalMode(
        title='строгий',
        criteria=(
            'Обязательны все элементы цели, и каждый выполнен полностью. '
            'Формулировки должны быть грамматически и лексически корректными. '
            'Пропущенный элемент или ошибка, искажающая смысл, означают, что цель не достигнута.'
        ),
        cap=2,
    ),
}
DEFAULT_GOAL_MODE = 'normal'
MODE_ORDER = tuple(GOAL_MODES)


async def load_goal_mode() -> str:
    raw = (await get_setting(GOAL_MODE_KEY) or '').strip()
    return raw if raw in GOAL_MODES else DEFAULT_GOAL_MODE


async def set_goal_mode(mode: str) -> None:
    if mode not in GOAL_MODES:
        raise ValueError('неизвестный режим проверки цели')
    await set_setting(GOAL_MODE_KEY, mode)


def next_mode(current: str) -> str:
    idx = MODE_ORDER.index(current) if current in MODE_ORDER else -1
    return MODE_ORDER[(idx + 1) % len(MODE_ORDER)]


def apply_goal_cap(score: int, achieved: bool | None, mode: str) -> int:
    '''Если цель не достигнута, итог не выше потолка режима.
    Без цели (achieved is None) или при достижении оценка не меняется.
    '''
    if achieved is not False:
        return score
    cap = GOAL_MODES.get(mode, GOAL_MODES[DEFAULT_GOAL_MODE]).cap
    return min(score, cap)


async def list_goals(limit: int = 10) -> list[Goal]:
    async with async_session() as session:
        rows = await session.scalars(select(Goal).order_by(Goal.id.desc()).limit(limit))
        return list(rows.all())


async def get_goal(goal_id: int) -> Goal | None:
    async with async_session() as session:
        return await session.get(Goal, goal_id)


async def create_goal(text: str) -> Goal:
    async with async_session() as session:
        goal = Goal(text=text)
        session.add(goal)
        await session.commit()
        return goal


async def get_active_goal() -> Goal | None:
    raw = (await get_setting(ACTIVE_GOAL_KEY) or '').strip()
    if not raw.isdigit() or int(raw) == 0:
        return None
    return await get_goal(int(raw))


async def set_active_goal(goal_id: int | None) -> None:
    await set_setting(ACTIVE_GOAL_KEY, str(goal_id or 0))

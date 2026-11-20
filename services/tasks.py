'''Задания преподавателя.

Активное задание хранится в settings под ключом active_task_id:
- записи нет: активно последнее созданное задание (поведение старых установок);
- '0': задание снято, ученики его не видят;
- число: id выбранного задания.
'''
from sqlalchemy import select

from database.engine import async_session
from database.models import Task
from services.settings import get_setting, set_setting

ACTIVE_TASK_KEY = 'active_task_id'


async def list_tasks(limit: int = 10) -> list[Task]:
    async with async_session() as session:
        rows = await session.scalars(select(Task).order_by(Task.id.desc()).limit(limit))
        return list(rows.all())


async def get_task(task_id: int) -> Task | None:
    async with async_session() as session:
        return await session.get(Task, task_id)


async def get_active_task() -> Task | None:
    raw = await get_setting(ACTIVE_TASK_KEY)
    if raw is None:
        async with async_session() as session:
            return await session.scalar(select(Task).order_by(Task.id.desc()).limit(1))
    if raw.strip().isdigit() and int(raw) > 0:
        return await get_task(int(raw))
    return None


async def set_active_task(task_id: int | None) -> None:
    await set_setting(ACTIVE_TASK_KEY, str(task_id or 0))


async def create_task(title: str, content: str) -> Task:
    async with async_session() as session:
        task = Task(title=title, content=content)
        session.add(task)
        await session.commit()
        return task

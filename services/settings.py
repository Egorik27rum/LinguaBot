from sqlalchemy import select
from database.engine import async_session
from database.models import Setting

async def get_setting(key: str) -> str | None:
    async with async_session() as session:
        return await session.scalar(select(Setting.value).where(Setting.key == key))

async def set_setting(key: str, value: str) -> None:
    async with async_session() as session:
        obj = await session.get(Setting, key)
        if obj:
            obj.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()

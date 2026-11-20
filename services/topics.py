from aiogram import Bot
from sqlalchemy import select

from core.config import config
from database.engine import async_session
from database.models import Student


async def ensure_student_topic(bot: Bot, tg_id: int, full_name: str) -> int:
    async with async_session() as session:
        student = await session.scalar(select(Student).where(Student.tg_id == tg_id))
        if student is None:
            student = Student(tg_id=tg_id, full_name=full_name)
            session.add(student)
        if student.topic_id is None:
            topic = await bot.create_forum_topic(
                config.GROUP_ID, name=full_name[:128]
            )
            student.topic_id = topic.message_thread_id
        await session.commit()
        return student.topic_id

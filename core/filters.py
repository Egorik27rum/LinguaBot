from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy import select

from core.config import config
from database.engine import async_session
from database.models import Student


class TeacherChatFilter(BaseFilter):
    """Пропускает сообщения администратора только из личного чата с главным ботом."""

    async def __call__(self, message: Message) -> bool:
        return (
            message.chat.type == 'private'
            and message.from_user is not None
            and message.from_user.id in config.ADMIN_IDS
        )


class StudentTopicFilter(BaseFilter):
    """Находит ученика по топику и передаёт его в хендлер как `student`."""

    async def __call__(self, message: Message):
        if message.chat.id != config.GROUP_ID or message.message_thread_id is None:
            return False
        async with async_session() as session:
            student = await session.scalar(
                select(Student).where(Student.topic_id == message.message_thread_id)
            )
        if student and student.tg_id == message.from_user.id:
            return {'student': student}
        return False

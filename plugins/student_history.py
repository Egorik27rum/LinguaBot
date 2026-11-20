'''Меню диалогов и история в личном топике ученика. Callback-префикс: hist:.

Доступ: владелец топика (его tg_id совпадает с student.tg_id) или преподаватель из ADMIN_IDS.
'''
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from core.config import config
from services import topic_history
from services.students import find_student_by_topic

logger = logging.getLogger(__name__)

ROLES = {'student'}
PRIORITY = 31


def _allowed(user_id: int, tg_id: int) -> bool:
    return user_id == tg_id or user_id in config.ADMIN_IDS


async def history_action(cb: CallbackQuery, bot: Bot) -> None:
    thread_id = cb.message.message_thread_id if cb.message else None
    student = await find_student_by_topic(thread_id) if thread_id else None
    if student is None or not _allowed(cb.from_user.id, student.tg_id):
        await cb.answer('Нет доступа', show_alert=True)
        return

    parts = (cb.data or '').split(':')
    source_id = cb.message.message_id

    if len(parts) == 3 and parts[1] == 'list' and parts[2].isdigit():
        await topic_history.show_menu(bot, student.id, thread_id, int(parts[2]), source_id=source_id)
        await cb.answer()
        return

    if len(parts) == 4 and parts[1] == 'open' and parts[2].isdigit() and parts[3].isdigit():
        shown = await topic_history.show_history(
            bot, student.id, thread_id, int(parts[2]), int(parts[3]), source_id=source_id,
        )
        if shown:
            await cb.answer()
        else:
            await cb.answer('Диалог не найден', show_alert=True)
        return

    await cb.answer()


def setup(router: Router) -> None:
    router.callback_query(F.data.startswith('hist:'))(history_action)

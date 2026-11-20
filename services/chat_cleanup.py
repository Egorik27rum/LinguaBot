'''Очистка личного чата ученика вне открытого диалога.

ID сообщений бота и ученика хранятся в settings (ключ chat:<chat_id>), поэтому очистка
переживает перезапуск бота. Очистка выполняется только вне диалога: во время диалога переписка
остаётся видимой. Удаляет сообщения тот бот, который ведёт этот чат (student-бот).
'''
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message

from services.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

MAX_TRACKED = 200  # защита от бесконтрольного роста записи в settings


def _key(chat_id: int) -> str:
    return f'chat:{chat_id}'


async def _load(chat_id: int) -> list[int]:
    raw = await get_setting(_key(chat_id)) or ''
    return [int(part) for part in raw.split(',') if part.isdigit()]


async def _store(chat_id: int, ids: list[int]) -> None:
    await set_setting(_key(chat_id), ','.join(str(i) for i in ids))


async def _add(chat_id: int, new_ids: list[int]) -> None:
    ids = (await _load(chat_id)) + new_ids
    await _store(chat_id, ids[-MAX_TRACKED:])


async def remember(message: Message) -> None:
    '''Запоминает сообщение ученика, чтобы очистка удалила его позже.'''
    await _add(message.chat.id, [message.message_id])


async def answer(message: Message, text: str,
                 reply_markup: InlineKeyboardMarkup | None = None) -> Message:
    '''Отправляет ответ бота и запоминает его ID.'''
    sent = await message.answer(text, reply_markup=reply_markup)
    await _add(message.chat.id, [sent.message_id])
    return sent


async def _delete_all(bot: Bot, chat_id: int, extra: list[int]) -> None:
    ids = set(await _load(chat_id)) | set(extra)
    for message_id in sorted(ids, reverse=True):
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as exc:  # старше 48 часов, уже удалено: только тип ошибки в лог
            logger.info('Сообщение не удалено при очистке чата: %s', type(exc).__name__)
    await _store(chat_id, [])


async def reset(message: Message) -> None:
    '''Удаляет запомненные сообщения и текущее сообщение (команду, кнопку или текст ученика).'''
    await _delete_all(message.bot, message.chat.id, [message.message_id])


async def forget(chat_id: int) -> None:
    '''Сбрасывает список запомненных сообщений без удаления.

    Используется при удалении ученика: главный бот не может удалять сообщения в личном чате
    другого бота (ограничение Telegram). Ученик после /start получает чистый список.
    '''
    await _store(chat_id, [])

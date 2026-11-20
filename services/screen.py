'''Одно главное сообщение бота в чате или в топике группы.

Новый экран заменяет предыдущий: старые сообщения бота удаляются.
ID сообщений хранятся в settings, поэтому переживают перезапуск бота.
Для топика ученика ключ включает thread_id, поэтому меню каждого ученика независимо.
'''
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message

from services.settings import get_setting, set_setting

logger = logging.getLogger(__name__)


def _key(chat_id: int, thread_id: int | None) -> str:
    return f'screen:{chat_id}' if thread_id is None else f'screen:{chat_id}:{thread_id}'


async def _load(chat_id: int, thread_id: int | None) -> list[int]:
    raw = await get_setting(_key(chat_id, thread_id)) or ''
    return [int(part) for part in raw.split(',') if part.isdigit()]


async def _store(chat_id: int, thread_id: int | None, ids: list[int]) -> None:
    await set_setting(_key(chat_id, thread_id), ','.join(str(i) for i in ids))


async def _delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        pass  # уже удалено или старше 48 часов


async def _edit(bot: Bot, chat_id: int, message_id: int, text: str,
                markup: InlineKeyboardMarkup | None, parse_mode: str | None) -> bool:
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id,
            reply_markup=markup, parse_mode=parse_mode,
        )
        return True
    except TelegramAPIError as exc:
        # Текст не изменился: это не ошибка, сообщение уже на месте
        return 'not modified' in str(exc).lower()


async def show(bot: Bot, chat_id: int, texts: list[str],
               markup: InlineKeyboardMarkup | None = None, *,
               parse_mode: str | None = None, source_id: int | None = None,
               thread_id: int | None = None) -> None:
    '''Показывает экран. При одном тексте и source_id сообщение редактируется на месте,
    иначе прежние сообщения экрана удаляются, а новые отправляются.
    '''
    old = await _load(chat_id, thread_id)

    if source_id is not None and len(texts) == 1:
        if await _edit(bot, chat_id, source_id, texts[0], markup, parse_mode):
            for message_id in old:
                if message_id != source_id:
                    await _delete(bot, chat_id, message_id)
            await _store(chat_id, thread_id, [source_id])
            return

    to_delete = set(old) | ({source_id} if source_id is not None else set())
    for message_id in to_delete:
        await _delete(bot, chat_id, message_id)

    ids: list[int] = []
    for index, text in enumerate(texts):
        is_last = index == len(texts) - 1
        sent = await bot.send_message(
            chat_id, text,
            parse_mode=parse_mode,
            reply_markup=markup if is_last else None,
            message_thread_id=thread_id,
        )
        ids.append(sent.message_id)
    await _store(chat_id, thread_id, ids)


async def clear(bot: Bot, chat_id: int, thread_id: int | None = None) -> None:
    '''Удаляет все сообщения экрана. Ошибки Telegram не прерывают очистку.'''
    for message_id in await _load(chat_id, thread_id):
        await _delete(bot, chat_id, message_id)
    await _store(chat_id, thread_id, [])


async def drop(message: Message) -> bool:
    '''Удаляет сообщение пользователя (команду, токен, ключ). Возвращает False, если Telegram не дал удалить.'''
    try:
        await message.delete()
        return True
    except TelegramAPIError as exc:
        # Только тип ошибки: текст может содержать фрагменты сообщения
        logger.warning('Не удалось удалить сообщение пользователя: %s', type(exc).__name__)
        return False

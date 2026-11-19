from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

ROLES = {'main', 'helper'}
PRIORITY = 50


async def ping(message: Message) -> None:
    me = await message.bot.get_me()
    await message.answer(f'pong от @{me.username}')


def setup(router: Router) -> None:
    router.message(Command('ping'))(ping)

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from core.config import config

ROLES = {'main', 'student'}
PRIORITY = 40
PRIVATE = F.chat.type == 'private'
MENU_TEXT = 'Откройте LinguaBot: здесь задания, диалог с нейросетью и история.'
TEACHER_TEXT = 'Панель преподавателя: статус, задания и ученики.'
UNAVAILABLE_TEXT = (
    'Приложение пока недоступно: преподаватель должен указать HTTPS-адрес (WEBAPP_URL) в настройках.'
)


def page_url(path: str) -> str | None:
    '''Адрес страницы приложения. Без HTTPS Telegram не откроет WebApp.'''
    url = config.WEBAPP_URL
    if not url or not url.startswith('https://'):
        return None
    return url.rstrip('/') + path


def is_teacher(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id in config.ADMIN_IDS


async def open_app(message: Message, bot_role: str) -> None:
    student_url = page_url('/')
    if student_url is None:
        await message.answer(UNAVAILABLE_TEXT)
        return

    rows = [[InlineKeyboardButton(text='Открыть LinguaBot', web_app=WebAppInfo(url=student_url))]]
    if is_teacher(message) and bot_role == 'main':
        teacher_url = page_url('/teacher')
        if teacher_url is not None:
            rows.append([InlineKeyboardButton(
                text='Панель преподавателя', web_app=WebAppInfo(url=teacher_url),
            )])
            await message.answer(TEACHER_TEXT, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            return
    await message.answer(MENU_TEXT, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


def setup(router: Router) -> None:
    router.message(Command('app'), PRIVATE)(open_app)

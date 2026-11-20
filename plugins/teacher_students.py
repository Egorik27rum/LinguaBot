import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.config import config
from services.screen import show
from services.students import delete_student, get_student, list_students

logger = logging.getLogger(__name__)

ROLES = {'main'}
PRIORITY = 19

PAGE_SIZE = 8
PREVIEW = 30


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def guard(cb: CallbackQuery) -> bool:
    if is_admin(cb.from_user.id):
        return True
    await cb.answer('Нет доступа', show_alert=True)
    return False


async def edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await show(cb.bot, cb.message.chat.id, [text], markup, source_id=cb.message.message_id)


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:64], callback_data=data)


def _ints(parts: list[str], count: int) -> list[int] | None:
    tail = parts[2:]
    if len(tail) != count or not all(p.isdigit() for p in tail):
        return None
    return [int(p) for p in tail]


async def render_list(cb: CallbackQuery, page: int, notice: str | None = None) -> None:
    students, page, pages, total = await list_students(page, PAGE_SIZE)

    lines = [notice, ''] if notice else []
    lines.append('Ученики')
    lines.append('')
    if total:
        lines.append(f'Зарегистрировано: {total}. Страница {page + 1} из {pages}.')
    else:
        lines.append('Зарегистрированных учеников пока нет.')

    rows = []
    for student in students:
        name = (student.full_name or 'Ученик')[:PREVIEW]
        rows.append([
            btn(name, 'students:noop'),
            btn('Удалить', f'students:ask:{student.id}:{page}'),
        ])

    nav = []
    if page > 0:
        nav.append(btn('‹ Назад', f'students:page:{page - 1}'))
    if page < pages - 1:
        nav.append(btn('Дальше ›', f'students:page:{page + 1}'))
    if nav:
        rows.append(nav)
    rows.append([btn('К главному меню', 'menu:main')])

    await edit(cb, '\n'.join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


async def render_confirm(cb: CallbackQuery, student_id: int, page: int,
                         delete_topic: bool) -> None:
    student = await get_student(student_id)
    if student is None:
        await render_list(cb, page, notice='Ученик не найден: возможно, он уже удалён.')
        return

    name = student.full_name or 'Ученик'
    text = (
        f'Удалить ученика {name}? Его история и оценки будут удалены.\n\n'
        'Открытый диалог будет отменён. Сообщения в личном чате с ботом ученика не удаляются: '
        'после удаления ему нужно отправить /start, чтобы пройти регистрацию заново и получить новый топик.\n\n'
        f'Удалить топик в группе: {"да" if delete_topic else "нет"}.'
    )
    toggle_text = ('✓ ' if delete_topic else '') + 'Удалить топик в группе'
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [btn(toggle_text, f'students:topic:{student.id}:{page}:{0 if delete_topic else 1}')],
        [btn('Да, удалить', f'students:yes:{student.id}:{page}:{1 if delete_topic else 0}')],
        [btn('Отмена', f'students:page:{page}')],
    ])
    await edit(cb, text, markup)


async def confirm_delete(cb: CallbackQuery, student_id: int, page: int,
                         delete_topic: bool) -> None:
    try:
        result = await delete_student(cb.bot, student_id, delete_topic)
    except Exception as exc:  # ошибка БД не должна ронять бота
        logger.error('Удаление ученика не выполнено: %s', type(exc).__name__)
        await render_list(cb, page, notice='Не удалось удалить ученика. Попробуйте позже.')
        return

    if result is None:
        notice = 'Ученик не найден: возможно, он уже удалён.'
    else:
        notice = (
            f'Ученик {result.name} удалён. {result.topic_note}\n'
            'Если он снова напишет боту, ему нужно пройти регистрацию заново: /start. '
            'После этого для него создастся новый топик.'
        )
    await render_list(cb, page, notice=notice)


async def menu_students(cb: CallbackQuery, state: FSMContext) -> None:
    if not await guard(cb):
        return
    await state.clear()
    await render_list(cb, 0)
    await cb.answer()


async def dispatch(cb: CallbackQuery) -> None:
    if not await guard(cb):
        return
    parts = (cb.data or '').split(':')
    action = parts[1] if len(parts) > 1 else ''

    if action == 'page' and (ids := _ints(parts, 1)):
        await render_list(cb, ids[0])
    elif action == 'ask' and (ids := _ints(parts, 2)):
        await render_confirm(cb, ids[0], ids[1], delete_topic=False)
    elif action == 'topic' and (ids := _ints(parts, 3)):
        await render_confirm(cb, ids[0], ids[1], delete_topic=ids[2] == 1)
    elif action == 'yes' and (ids := _ints(parts, 3)):
        await confirm_delete(cb, ids[0], ids[1], delete_topic=ids[2] == 1)
    else:
        await cb.answer()
        return
    await cb.answer()


def setup(router: Router) -> None:
    router.callback_query(F.data == 'menu:students')(menu_students)
    router.callback_query(F.data.startswith('students:'))(dispatch)

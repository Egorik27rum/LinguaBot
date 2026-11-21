'''Итог диалога для ученика, преподавателя и истории. Совпадает с итогом в боте.'''
from __future__ import annotations

from database.models import Goal
from services.goals import GOAL_MODES


def build_report(title: str, result: dict, goal: Goal | None, mode: str | None) -> str:
    lines = [f'Итог диалога по заданию «{title}»', f'Оценка: {result["score"]} из 5', '']
    if goal is not None and mode in GOAL_MODES:
        verdict = 'достигнута' if result['goal_achieved'] else 'не достигнута'
        lines.append(f'Цель «{goal.text}»: {verdict} (режим «{GOAL_MODES[mode].title}»)')
        lines.append('Выполнено: ' + ('; '.join(result['goal_done']) or 'нет'))
        lines.append('Не выполнено: ' + ('; '.join(result['goal_missed']) or 'нет'))
        if result['capped']:
            lines.append(
                f'Оценка снижена с {result["raw_score"]} до {result["score"]}: цель не достигнута, '
                f'потолок режима «{GOAL_MODES[mode].title}» — {GOAL_MODES[mode].cap}.'
            )
        lines.append('')
    if result['feedback']:
        lines.append(f'Разбор: {result["feedback"]}')
    return '\n'.join(lines).strip()

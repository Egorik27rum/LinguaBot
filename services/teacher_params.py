'''Переключение параметра по кругу: общая логика кнопок бота и API.'''
from typing import Any, Sequence


def next_in_cycle(options: Sequence[Any], current: Any) -> Any:
    '''Следующее значение по кругу. Если текущего нет в списке, берётся первое.'''
    idx = options.index(current) if current in options else -1
    return options[(idx + 1) % len(options)]

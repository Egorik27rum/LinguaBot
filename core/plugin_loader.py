import importlib
import logging
import pkgutil
from dataclasses import dataclass
from types import ModuleType

from aiogram import Router

import plugins as plugins_pkg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Plugin:
    name: str
    module: ModuleType
    roles: frozenset[str]
    priority: int


def load_plugins() -> list[Plugin]:
    '''Импортирует все plugins/*.py (кроме _*.py). Файлы *.py.disabled не загружаются.'''
    found: list[Plugin] = []
    for info in pkgutil.iter_modules(plugins_pkg.__path__):
        if info.name.startswith('_'):
            continue
        module = importlib.import_module(f'{plugins_pkg.__name__}.{info.name}')
        if not hasattr(module, 'setup'):
            logger.warning('Плагин %s пропущен: нет функции setup(router)', info.name)
            continue
        found.append(Plugin(
            name=info.name,
            module=module,
            roles=frozenset(getattr(module, 'ROLES', {'main'})),
            priority=getattr(module, 'PRIORITY', 100),
        ))
    return sorted(found, key=lambda p: (p.priority, p.name))


def build_router(plugin: Plugin) -> Router:
    '''Каждому боту нужен свой Router: один Router нельзя прикрепить к двум Dispatcher.'''
    router = Router(name=plugin.name)
    plugin.module.setup(router)
    return router

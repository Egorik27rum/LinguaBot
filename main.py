import asyncio
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram.utils.token import TokenValidationError

from api.server import start_webapp
from core.bot_manager import build_specs, create_bot, known_tokens, migrate_bots_file, run_bot
from core.config import config
from core.plugin_loader import load_plugins
from database.engine import init_db
from services.retention import retention_loop
from services.settings import get_setting, migrate_secrets, set_setting

ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / 'logs' / 'bot.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
TOKEN_PATTERN = re.compile(r'\d{6,}:[A-Za-z0-9_-]{30,}')
MIN_SECRET_LEN = 8  # короче — риск замаскировать случайные совпадения


class SecretMaskFilter(logging.Filter):
    '''Маскирует токены Telegram и известные секреты в сообщениях, аргументах и traceback.'''

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def add(self, *values: str | None) -> None:
        for value in values:
            value = (value or '').strip()
            if len(value) >= MIN_SECRET_LEN:
                self._secrets.add(value)

    def mask(self, text: str) -> str:
        # Сначала длинные секреты, чтобы короткий фрагмент не «съел» длинный
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, '***')
        return TOKEN_PATTERN.sub('***', text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = '[сообщение не удалось отформатировать]'
        record.msg = self.mask(message)
        record.args = ()
        if record.exc_info:
            # Traceback форматируется позже Formatter'ом, поэтому маскируем здесь
            record.exc_text = self.mask(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging() -> SecretMaskFilter:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    mask = SecretMaskFilter()
    formatter = logging.Formatter(LOG_FORMAT)
    console = logging.StreamHandler()
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8',
    )
    handlers = [console, file_handler]
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(mask)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    return mask


async def main():
    mask = setup_logging()

    if not os.path.exists('lingua_data.db'):
        logging.info('Создание новой базы данных...')
    await init_db()

    # Однократная миграция: зашифровать уже сохранённые секреты и токены
    migrated = await migrate_secrets()
    if migrated:
        logging.info('Зашифровано секретов в базе: %s', migrated)
    migrate_bots_file()

    if config.POLZA_API_KEY and not await get_setting('polza_api_key'):
        await set_setting('polza_api_key', config.POLZA_API_KEY)
        logging.info('Ключ Polza.ai из .env перенесён в базу данных.')

    mask.add(
        await get_setting('polza_api_key'),
        config.POLZA_API_KEY,
        config.BOT_TOKEN,
        config.STUDENT_BOT_TOKEN,
        *known_tokens(),
    )

    plugins = load_plugins()
    specs = build_specs()

    # Каждый бот создаётся отдельно: неверный токен доп. бота не должен остановить главного
    pairs = []
    for spec in specs:
        try:
            bot, dp = create_bot(spec, plugins)
        except TokenValidationError as exc:
            if spec.role == 'main':
                raise
            logging.error('Бот %s пропущен: токен отклонён (%s). Проверьте configs/bots.json',
                          spec.name, type(exc).__name__)
            continue
        pairs.append((spec, bot, dp))

    main_bot = next(bot for spec, bot, _ in pairs if spec.role == 'main')
    # Все токены проекта: initData проверяется по тому боту, из которого открыто приложение
    tokens = known_tokens()

    retention_task = asyncio.create_task(retention_loop(config.RETENTION_DAYS))
    webapp_runner = None
    try:
        try:
            webapp_runner = await start_webapp(main_bot, tokens)
        except OSError as exc:
            # Занятый порт не должен останавливать ботов
            logging.error('Mini App не запущен (%s): порт %s занят или недоступен. '
                          'Боты работают без приложения.', type(exc).__name__, config.WEBAPP_PORT)
        logging.info(f'Запуск ботов: {len(pairs)} (плагинов: {len(plugins)})')
        await asyncio.gather(*(
            run_bot(spec, bot, dp) for spec, bot, dp in pairs
        ))
    finally:
        retention_task.cancel()
        if webapp_runner is not None:
            await webapp_runner.cleanup()
        await asyncio.gather(*(bot.session.close() for _, bot, _ in pairs), return_exceptions=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info('Боты остановлены.')

import asyncio
import logging
import os

from core.bot_manager import build_specs, create_bot, run_bot
from core.plugin_loader import load_plugins
from database.engine import init_db
from services.settings import get_setting, set_setting
from core.config import config


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    if not os.path.exists('lingua_data.db'):
        logging.info('Создание новой базы данных...')
    await init_db()

    if config.POLZA_API_KEY and not await get_setting('polza_api_key'):
        await set_setting('polza_api_key', config.POLZA_API_KEY)
        logging.info('Ключ Polza.ai из .env перенесён в базу данных.')

    plugins = load_plugins()
    specs = build_specs()
    bots = [create_bot(spec, plugins) for spec in specs]

    try:
        logging.info(f'Запуск ботов: {len(bots)} (плагинов: {len(plugins)})')
        await asyncio.gather(*(
            run_bot(spec, bot, dp) for spec, (bot, dp) in zip(specs, bots)
        ))
    finally:
        await asyncio.gather(*(bot.session.close() for bot, _ in bots), return_exceptions=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info('Боты остановлены.')

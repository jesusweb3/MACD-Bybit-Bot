# main.py

import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from src.utils.config import config
from src.utils.logger import logger
from src.database.database import db

# Импорты обработчиков
from src.bot.handlers.start import start
from src.bot.handlers.settings import settings
from src.bot.handlers.trade import trade


async def main():
    if not config.telegram_token:
        logger.error("TELEGRAM_TOKEN not found in environment")
        return

    bot = Bot(token=config.telegram_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Подключаем обработчики
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(trade.router)

    db.create_tables()
    logger.info("Bot starting with simplified setup...")

    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
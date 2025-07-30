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
    """Главная функция запуска бота"""
    if not config.telegram_token:
        logger.error("TELEGRAM_TOKEN not found in environment")
        return

    # Создаем бота и диспетчер
    bot = Bot(token=config.telegram_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Подключаем обработчики
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(trade.router)

    # Создаем таблицы базы данных
    db.create_tables()
    logger.info("✅ MACD бот запускается...")

    try:
        # Запускаем polling
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        logger.info("🔄 Получен сигнал остановки...")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка бота: {e}")
    finally:
        # Останавливаем все активные стратегии при завершении
        from src.strategy import strategy_manager
        if strategy_manager.get_active_strategies_count() > 0:
            logger.info("⏹️ Останавливаем активные стратегии...")
            await strategy_manager.stop_all_strategies("Bot shutdown")

        # Закрываем сессию бота
        await bot.session.close()
        logger.info("👋 MACD бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Выход по Ctrl+C")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        exit(1)
# main.py
import asyncio
import signal
import sys
from typing import Optional
from src.utils.config import config
from src.utils.logger import logger
from src.utils.helpers import format_msk_time
from src.database.database import db
from src.strategy import strategy_manager


class TradingBot:
    """Главный класс торгового бота без Telegram"""

    def __init__(self):
        self.is_running = False
        self.shutdown_requested = False

    async def startup(self) -> bool:
        """Инициализация бота"""
        try:
            start_time_msk = format_msk_time()
            logger.info("=" * 60)
            logger.info(f"🚀 ЗАПУСК ТОРГОВОГО БОТА")
            logger.info(f"⏰ Время запуска: {start_time_msk} МСК")
            logger.info("=" * 60)

            # Выводим конфигурацию
            config.print_config()

            # Создаем таблицы базы данных
            db.create_tables()

            # Синхронизируемся с БД
            await strategy_manager.cleanup_and_sync_with_db()

            # Проверяем не была ли стратегия запущена ранее
            db_status = db.get_strategy_status()
            if db_status.get('is_active'):
                logger.warning("⚠️ Обнаружена активная стратегия в БД от предыдущей сессии")
                logger.info("🔧 Отмечаем как остановленную...")
                db.set_strategy_inactive("Bot restart - previous session cleanup")

            # Выводим текущую статистику
            db.print_statistics()
            strategy_manager.print_status()

            logger.info("✅ Инициализация завершена")
            logger.info("🎯 Готов к запуску стратегии...")

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации: {e}")
            return False

    async def run_strategy(self):
        """Основной цикл работы со стратегией"""
        try:
            # Запускаем стратегию
            result = await strategy_manager.start_strategy()

            if not result['success']:
                logger.error(f"❌ Не удалось запустить стратегию: {result['error']}")
                return False

            logger.info("🎯 Стратегия запущена! Ожидание сигналов...")
            self.is_running = True

            # Основной цикл - просто ждем пока стратегия работает
            while self.is_running and not self.shutdown_requested:
                # Проверяем статус стратегии каждые 10 секунд
                if not strategy_manager.is_strategy_active():
                    logger.warning("⚠️ Стратегия больше не активна")
                    break

                # Ждем 10 секунд
                await asyncio.sleep(10)

                # Можно добавить периодический вывод статистики
                # (каждые 5 минут например)

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка в основном цикле: {e}")
            return False

    async def shutdown(self, reason: str = "Normal shutdown"):
        """Корректное завершение работы"""
        try:
            if self.shutdown_requested:
                return

            self.shutdown_requested = True
            shutdown_time_msk = format_msk_time()

            logger.info("=" * 60)
            logger.info(f"⏹️ ОСТАНОВКА ТОРГОВОГО БОТА")
            logger.info(f"📝 Причина: {reason}")
            logger.info(f"⏰ Время остановки: {shutdown_time_msk} МСК")
            logger.info("=" * 60)

            # Останавливаем стратегию если активна
            if strategy_manager.is_strategy_active():
                logger.info("⏹️ Останавливаем активную стратегию...")
                stop_result = await strategy_manager.stop_strategy(reason)

                if stop_result['success']:
                    logger.info(f"✅ Стратегия остановлена: {stop_result['strategy_name']}")
                else:
                    logger.error(f"❌ Ошибка остановки стратегии: {stop_result['error']}")

            # Выводим финальную статистику
            logger.info("📊 Финальная статистика:")
            db.print_statistics()

            self.is_running = False
            logger.info("👋 Торговый бот остановлен")

        except Exception as e:
            logger.error(f"❌ Ошибка при завершении: {e}")

    def setup_signal_handlers(self):
        """Настройка обработчиков сигналов для корректного завершения"""

        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            logger.info(f"📡 Получен сигнал {signal_name}")

            # Создаем задачу для корректного завершения
            if not self.shutdown_requested:
                asyncio.create_task(self.shutdown(f"Signal {signal_name}"))

        # Регистрируем обработчики
        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # kill

        logger.info("📡 Обработчики сигналов настроены (Ctrl+C для остановки)")


async def main():
    """Главная функция"""
    bot = TradingBot()

    try:
        # Настраиваем обработчики сигналов
        bot.setup_signal_handlers()

        # Инициализация
        if not await bot.startup():
            logger.error("❌ Не удалось инициализировать бота")
            sys.exit(1)

        # Запускаем стратегию и основной цикл
        success = await bot.run_strategy()

        if not success:
            logger.error("❌ Ошибка в работе стратегии")
            await bot.shutdown("Strategy error")
            sys.exit(1)

        # Если дошли сюда, значит цикл завершился нормально
        if not bot.shutdown_requested:
            await bot.shutdown("Strategy completed")

    except KeyboardInterrupt:
        logger.info("⚠️ Получен Ctrl+C")
        await bot.shutdown("Keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        await bot.shutdown(f"Critical error: {e}")
        sys.exit(1)


def run_bot():
    """Функция запуска для удобства"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Выход по Ctrl+C")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_bot()
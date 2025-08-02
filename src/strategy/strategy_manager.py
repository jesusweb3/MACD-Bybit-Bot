# src/strategy/strategy_manager.py
from typing import Optional, Dict, Any
from .macd import MACDStrategy
from ..database.database import db
from ..utils.logger import logger
from ..utils.config import config


class StrategyManager:
    """Упрощенный менеджер для управления одной MACD стратегией"""

    def __init__(self):
        # Одна глобальная стратегия вместо множества
        self.strategy: Optional[MACDStrategy] = None

    async def start_strategy(self) -> Dict[str, Any]:
        """
        Запуск MACD стратегии

        Returns:
            Результат запуска стратегии
        """
        try:
            # Проверяем что стратегия не запущена
            if self.strategy is not None:
                return {
                    'success': False,
                    'error': f'Стратегия уже запущена: {self.strategy.strategy_name}'
                }

            logger.info(f"🚀 Запуск MACD стратегии")

            # Создаем экземпляр стратегии
            self.strategy = MACDStrategy()

            # Запускаем стратегию
            start_success = await self.strategy.start()

            if start_success:
                logger.info(f"✅ MACD стратегия успешно запущена")

                return {
                    'success': True,
                    'strategy_name': self.strategy.strategy_name,
                    'message': f'Стратегия {self.strategy.strategy_name} успешно запущена!',
                    'config': {
                        'symbol': config.trading_pair,
                        'timeframe': config.timeframe,
                        'leverage': config.leverage,
                        'position_size': f"{config.position_size_usdt} USDT"
                    }
                }
            else:
                error_msg = self.strategy.error_message or 'Неизвестная ошибка при запуске'
                logger.error(f"❌ Не удалось запустить MACD стратегию: {error_msg}")

                # Очищаем стратегию при ошибке
                self.strategy = None

                return {
                    'success': False,
                    'error': f'Ошибка запуска: {error_msg}'
                }

        except Exception as e:
            logger.error(f"❌ Исключение при запуске MACD стратегии: {e}")

            # Очищаем стратегию при ошибке
            self.strategy = None

            return {
                'success': False,
                'error': f'Критическая ошибка: {str(e)}'
            }

    async def stop_strategy(self, reason: str = "Manual stop") -> Dict[str, Any]:
        """
        Остановка стратегии

        Args:
            reason: Причина остановки

        Returns:
            Результат остановки стратегии
        """
        try:
            # Проверяем есть ли активная стратегия
            if self.strategy is None:
                return {
                    'success': False,
                    'error': 'Нет активной стратегии для остановки'
                }

            strategy_name = self.strategy.strategy_name

            logger.info(f"⏹️ Остановка стратегии {strategy_name}: {reason}")

            # Останавливаем стратегию
            stop_success = await self.strategy.stop(reason)

            # Удаляем стратегию из памяти
            self.strategy = None

            if stop_success:
                logger.info(f"✅ Стратегия {strategy_name} успешно остановлена")

                return {
                    'success': True,
                    'strategy_name': strategy_name,
                    'message': f'Стратегия {strategy_name} остановлена'
                }
            else:
                logger.warning(f"⚠️ Стратегия остановлена с предупреждениями")

                return {
                    'success': True,  # Считаем успехом, даже если были предупреждения
                    'strategy_name': strategy_name,
                    'message': f'Стратегия {strategy_name} остановлена (с предупреждениями)'
                }

        except Exception as e:
            logger.error(f"❌ Исключение при остановке стратегии: {e}")

            # Все равно удаляем стратегию из памяти
            strategy_name = self.strategy.strategy_name if self.strategy else "неизвестная"
            self.strategy = None

            return {
                'success': False,
                'strategy_name': strategy_name,
                'error': f'Ошибка остановки: {str(e)}'
            }

    def get_strategy(self) -> Optional[MACDStrategy]:
        """Получение активной стратегии"""
        return self.strategy

    def is_strategy_active(self) -> bool:
        """Проверка активности стратегии"""
        return self.strategy is not None and self.strategy.is_active

    def get_strategy_status(self) -> Dict[str, Any]:
        """Получение статуса стратегии"""
        if self.strategy is None:
            # Проверяем БД на случай если стратегия была запущена в прошлой сессии
            db_status = db.get_strategy_status()
            return {
                'is_active': False,
                'strategy_name': db_status.get('strategy_name'),
                'status': 'not_running',
                'in_memory': False,
                'last_db_status': db_status
            }

        # Получаем статус из активной стратегии
        status_info = self.strategy.get_status_info()
        status_info['in_memory'] = True

        return status_info

    async def restart_strategy(self, reason: str = "Restart requested") -> Dict[str, Any]:
        """Перезапуск стратегии"""
        logger.info(f"🔄 Перезапуск стратегии: {reason}")

        # Сначала останавливаем если запущена
        if self.is_strategy_active():
            stop_result = await self.stop_strategy(f"Restart: {reason}")
            if not stop_result['success']:
                return {
                    'success': False,
                    'error': f"Не удалось остановить для перезапуска: {stop_result['error']}"
                }

        # Затем запускаем
        start_result = await self.start_strategy()
        if start_result['success']:
            start_result['message'] = f"Стратегия перезапущена: {reason}"

        return start_result

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики"""
        # Статистика из БД
        db_stats = db.get_statistics()

        # Статистика активной стратегии
        strategy_stats = {}
        if self.strategy:
            strategy_info = self.strategy.get_status_info()
            strategy_stats = {
                'signals_received': strategy_info.get('total_signals_received', 0),
                'signals_processed': strategy_info.get('signals_processed', 0),
                'position_state': strategy_info.get('position_state'),
                'strategy_state': strategy_info.get('strategy_state'),
                'last_signal_time': strategy_info.get('last_signal_time')
            }

        return {
            'database_stats': db_stats,
            'strategy_stats': strategy_stats,
            'is_active': self.is_strategy_active(),
            'config': {
                'symbol': config.trading_pair,
                'timeframe': config.timeframe,
                'leverage': config.leverage,
                'position_size': f"{config.position_size_usdt} USDT"
            }
        }

    def print_status(self):
        """Вывод статуса в консоль"""
        print("\n" + "=" * 70)
        print("СТАТУС МЕНЕДЖЕРА СТРАТЕГИЙ")
        print("=" * 70)

        # Статус стратегии
        if self.strategy:
            print(f"Активная стратегия: 🟢 {self.strategy.strategy_name}")
            self.strategy.print_status()
        else:
            print("Активная стратегия: 🔴 Нет")

            # Проверяем последний статус в БД
            db_status = db.get_strategy_status()
            if db_status:
                print(f"Последняя в БД: {db_status.get('strategy_name', 'N/A')}")
                print(f"Статус в БД: {'Активна' if db_status.get('is_active') else 'Остановлена'}")

        # Общая статистика
        stats = self.get_statistics()
        db_stats = stats['database_stats']

        print("\n📊 ОБЩАЯ СТАТИСТИКА:")
        print(f"Всего сделок: {db_stats.get('total_trades', 0)}")
        print(f"Открытых сделок: {db_stats.get('closed_trades', 0)}")
        print(f"Общий P&L: {db_stats.get('total_pnl', 0):.2f} USDT")
        print(f"Винрейт: {db_stats.get('win_rate', 0):.1f}%")

        # Конфигурация
        config_info = stats['config']
        print(f"\n⚙️ КОНФИГУРАЦИЯ:")
        print(f"Символ: {config_info['symbol']}")
        print(f"Таймфрейм: {config_info['timeframe']}")
        print(f"Плечо: {config_info['leverage']}x")
        print(f"Размер позиции: {config_info['position_size']}")

        print("=" * 70)

    async def cleanup_and_sync_with_db(self):
        """Очистка памяти и синхронизация с БД"""
        try:
            # Проверяем статус в БД
            db_status = db.get_strategy_status()

            if self.strategy is None and db_status.get('is_active'):
                # В БД стратегия помечена как активная, но в памяти её нет
                logger.warning("⚠️ Обнаружено рассинхронизация: БД показывает активную стратегию, но в памяти её нет")
                db.set_strategy_inactive("Cleanup: strategy not in memory")

            elif self.strategy is not None and not db_status.get('is_active'):
                # В памяти есть стратегия, но в БД она не активна
                logger.warning("⚠️ Обнаружено рассинхронизация: стратегия в памяти, но БД показывает неактивную")
                if self.strategy.is_active:
                    db.set_strategy_active(self.strategy.strategy_name)
                else:
                    # Стратегия в памяти но неактивна - удаляем
                    logger.info("🧹 Удаляем неактивную стратегию из памяти")
                    self.strategy = None

            logger.info("✅ Синхронизация с БД завершена")

        except Exception as e:
            logger.error(f"❌ Ошибка синхронизации с БД: {e}")


# Глобальный экземпляр менеджера стратегий
strategy_manager = StrategyManager()
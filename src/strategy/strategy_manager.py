# src/strategy/strategy_manager.py
from typing import Optional, Dict, Any
from .macd import MACDStrategy
from ..utils.logger import logger
from ..utils.config import config


class StrategyManager:
    """менеджер для управления одной MACD стратегией"""

    def __init__(self):
        # Одна глобальная стратегия
        self.strategy: Optional[MACDStrategy] = None

    async def start_strategy(self) -> Dict[str, Any]:
        """Запуск MACD стратегии"""
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
        """Остановка стратегии"""
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
            return {
                'is_active': False,
                'strategy_name': None,
                'status': 'not_running'
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

        # Конфигурация
        print(f"\n⚙️ КОНФИГУРАЦИЯ:")
        print(f"Символ: {config.trading_pair}")
        print(f"Таймфрейм: {config.timeframe}")
        print(f"Плечо: {config.leverage}x")
        print(f"Размер позиции: {config.position_size_usdt} USDT")

        print("=" * 70)


# Глобальный экземпляр менеджера стратегий
strategy_manager = StrategyManager()
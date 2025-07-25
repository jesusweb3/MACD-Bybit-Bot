# src/strategies/strategy_manager.py
from typing import Dict, Optional, Any
from .base_strategy import BaseStrategy
from .macd_full import MACDFullStrategy
from ..utils.logger import logger
from ..database.database import db


class StrategyManager:
    """Менеджер для управления активными стратегиями"""

    def __init__(self):
        # Словарь активных стратегий: {telegram_id: BaseStrategy}
        self.active_strategies: Dict[int, BaseStrategy] = {}

        # Доступные стратегии
        self.available_strategies = {
            'macd_full': MACDFullStrategy,
            'macd_long': None,  # TODO: Реализовать позже
            'macd_short': None  # TODO: Реализовать позже
        }

    async def start_strategy(self, telegram_id: int, strategy_name: str) -> Dict[str, Any]:
        """
        Запуск стратегии для пользователя

        Args:
            telegram_id: ID пользователя Telegram
            strategy_name: Название стратегии (macd_full, macd_long, macd_short)

        Returns:
            Результат запуска стратегии
        """
        try:
            # Проверяем что стратегия существует
            if strategy_name not in self.available_strategies:
                return {
                    'success': False,
                    'error': f'Стратегия {strategy_name} не найдена'
                }

            strategy_class = self.available_strategies[strategy_name]
            if strategy_class is None:
                return {
                    'success': False,
                    'error': f'Стратегия {strategy_name} еще не реализована'
                }

            # Проверяем что у пользователя нет активной стратегии
            if telegram_id in self.active_strategies:
                return {
                    'success': False,
                    'error': 'У вас уже запущена стратегия. Остановите ее перед запуском новой.'
                }

            # Проверяем активную стратегию в БД
            active_strategy_db = db.get_active_strategy(telegram_id)
            if active_strategy_db:
                return {
                    'success': False,
                    'error': 'У вас есть активная стратегия в базе данных. Перезапустите бота.'
                }

            logger.info(f"Запуск стратегии {strategy_name} для пользователя {telegram_id}")

            # Создаем экземпляр стратегии
            strategy = strategy_class(telegram_id)

            # Запускаем стратегию
            start_success = await strategy.start()

            if start_success:
                # Сохраняем в активные стратегии
                self.active_strategies[telegram_id] = strategy

                logger.info(f"✅ Стратегия {strategy_name} успешно запущена для {telegram_id}")

                return {
                    'success': True,
                    'strategy_name': strategy_name,
                    'strategy_id': strategy.strategy_id,
                    'message': f'Стратегия {strategy_name} успешно запущена!'
                }
            else:
                error_msg = strategy.error_message or 'Неизвестная ошибка при запуске'
                logger.error(f"❌ Не удалось запустить стратегию {strategy_name}: {error_msg}")

                return {
                    'success': False,
                    'error': f'Ошибка запуска: {error_msg}'
                }

        except Exception as e:
            logger.error(f"❌ Исключение при запуске стратегии {strategy_name}: {e}")
            return {
                'success': False,
                'error': f'Критическая ошибка: {str(e)}'
            }

    async def stop_strategy(self, telegram_id: int, reason: str = "Manual stop") -> Dict[str, Any]:
        """
        Остановка стратегии пользователя

        Args:
            telegram_id: ID пользователя Telegram
            reason: Причина остановки

        Returns:
            Результат остановки стратегии
        """
        try:
            # Проверяем есть ли активная стратегия
            if telegram_id not in self.active_strategies:
                return {
                    'success': False,
                    'error': 'У вас нет активной стратегии'
                }

            strategy = self.active_strategies[telegram_id]
            strategy_name = strategy.strategy_name

            logger.info(f"Остановка стратегии {strategy_name} для пользователя {telegram_id}: {reason}")

            # Останавливаем стратегию
            stop_success = await strategy.stop(reason)

            # Удаляем из активных стратегий
            del self.active_strategies[telegram_id]

            if stop_success:
                logger.info(f"✅ Стратегия {strategy_name} успешно остановлена для {telegram_id}")

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

            # Все равно удаляем из активных стратегий
            if telegram_id in self.active_strategies:
                del self.active_strategies[telegram_id]

            return {
                'success': False,
                'error': f'Ошибка остановки: {str(e)}'
            }

    def get_active_strategy(self, telegram_id: int) -> Optional[BaseStrategy]:
        """Получение активной стратегии пользователя"""
        return self.active_strategies.get(telegram_id)

    def is_strategy_active(self, telegram_id: int) -> bool:
        """Проверка активности стратегии у пользователя"""
        return telegram_id in self.active_strategies

    def get_strategy_status(self, telegram_id: int) -> Dict[str, Any]:
        """Получение статуса стратегии пользователя"""
        if telegram_id not in self.active_strategies:
            return {
                'is_active': False,
                'strategy_name': None,
                'status': 'not_running'
            }

        strategy = self.active_strategies[telegram_id]
        status_info = strategy.get_status_info()

        # Добавляем информацию о позиции для MACD Full
        if hasattr(strategy, 'get_position_info'):
            position_info = strategy.get_position_info()
            status_info.update(position_info)

        status_info['is_active'] = True
        return status_info

    def get_active_strategies_count(self) -> int:
        """Получение количества активных стратегий"""
        return len(self.active_strategies)

    def get_all_active_strategies(self) -> Dict[int, Dict[str, Any]]:
        """Получение всех активных стратегий"""
        result = {}
        for telegram_id, strategy in self.active_strategies.items():
            result[telegram_id] = strategy.get_status_info()
        return result

    async def stop_all_strategies(self, reason: str = "System shutdown") -> Dict[str, Any]:
        """Остановка всех активных стратегий"""
        logger.info(f"Остановка всех активных стратегий: {reason}")

        stopped_count = 0
        error_count = 0

        # Копируем список telegram_id, чтобы избежать изменения словаря во время итерации
        telegram_ids = list(self.active_strategies.keys())

        for telegram_id in telegram_ids:
            try:
                result = await self.stop_strategy(telegram_id, reason)
                if result['success']:
                    stopped_count += 1
                else:
                    error_count += 1
                    logger.error(f"Ошибка остановки стратегии для {telegram_id}: {result.get('error')}")
            except Exception as e:
                error_count += 1
                logger.error(f"Исключение при остановке стратегии для {telegram_id}: {e}")

        logger.info(f"Остановлено стратегий: {stopped_count}, ошибок: {error_count}")

        return {
            'stopped_count': stopped_count,
            'error_count': error_count,
            'total_processed': len(telegram_ids)
        }

    def get_available_strategies(self) -> Dict[str, bool]:
        """Получение списка доступных стратегий"""
        return {
            name: strategy_class is not None
            for name, strategy_class in self.available_strategies.items()
        }


# Глобальный экземпляр менеджера стратегий
strategy_manager = StrategyManager()
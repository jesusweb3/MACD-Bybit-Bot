# src/strategy/strategy_manager.py
from typing import Dict, Optional, Any
from .macd import MACDStrategy
from ..utils.logger import logger


class StrategyManager:
    """Упрощенный менеджер для управления MACD стратегиями"""

    def __init__(self):
        # Словарь активных стратегий: {telegram_id: MACDStrategy}
        self.active_strategies: Dict[int, MACDStrategy] = {}

    async def start_strategy(self, telegram_id: int) -> Dict[str, Any]:
        """
        Запуск MACD стратегии для пользователя

        Args:
            telegram_id: ID пользователя Telegram

        Returns:
            Результат запуска стратегии
        """
        try:
            # Проверяем что у пользователя нет активной стратегии
            if telegram_id in self.active_strategies:
                current_strategy = self.active_strategies[telegram_id]
                return {
                    'success': False,
                    'error': f'У вас уже запущена стратегия {current_strategy.strategy_name}. Остановите ее перед запуском новой.'
                }

            logger.info(f"Запуск MACD стратегии для пользователя {telegram_id}")

            # Создаем экземпляр стратегии
            strategy = MACDStrategy(telegram_id)

            # Запускаем стратегию
            start_success = await strategy.start()

            if start_success:
                # Сохраняем в активные стратегии
                self.active_strategies[telegram_id] = strategy

                logger.info(f"✅ MACD стратегия успешно запущена для {telegram_id}")

                # Добавляем сводку настроек в ответ
                settings_summary = strategy.get_settings_summary()

                return {
                    'success': True,
                    'strategy_name': strategy.strategy_name,
                    'strategy_id': strategy.strategy_id,
                    'message': f'Стратегия {strategy.strategy_name} успешно запущена!',
                    'settings': settings_summary
                }
            else:
                error_msg = strategy.error_message or 'Неизвестная ошибка при запуске'
                logger.error(f"❌ Не удалось запустить MACD стратегию: {error_msg}")

                return {
                    'success': False,
                    'error': f'Ошибка запуска: {error_msg}'
                }

        except Exception as e:
            logger.error(f"❌ Исключение при запуске MACD стратегии: {e}")
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
                strategy_name = self.active_strategies[telegram_id].strategy_name
                del self.active_strategies[telegram_id]
            else:
                strategy_name = "неизвестная"

            return {
                'success': False,
                'strategy_name': strategy_name,
                'error': f'Ошибка остановки: {str(e)}'
            }

    def get_active_strategy(self, telegram_id: int) -> Optional[MACDStrategy]:
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

        # Добавляем сводку настроек
        settings_summary = strategy.get_settings_summary()
        status_info['settings'] = settings_summary
        status_info['is_active'] = True

        return status_info

    def get_active_strategies_count(self) -> int:
        """Получение количества активных стратегий"""
        return len(self.active_strategies)

    def get_all_active_strategies(self) -> Dict[int, Dict[str, Any]]:
        """Получение всех активных стратегий"""
        result = {}
        for telegram_id, strategy in self.active_strategies.items():
            status_info = strategy.get_status_info()
            settings_summary = strategy.get_settings_summary()
            status_info['settings'] = settings_summary
            result[telegram_id] = status_info

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

    def cleanup_inactive_strategies(self):
        """Очистка неактивных стратегий из памяти"""
        inactive_telegram_ids = []

        for telegram_id, strategy in self.active_strategies.items():
            if not strategy.is_active:
                inactive_telegram_ids.append(telegram_id)

        for telegram_id in inactive_telegram_ids:
            logger.info(f"Удаляем неактивную стратегию для пользователя {telegram_id}")
            del self.active_strategies[telegram_id]

        if inactive_telegram_ids:
            logger.info(f"Очищено {len(inactive_telegram_ids)} неактивных стратегий")


# Глобальный экземпляр менеджера стратегий
strategy_manager = StrategyManager()
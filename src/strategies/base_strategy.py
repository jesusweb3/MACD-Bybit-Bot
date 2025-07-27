# src/strategies/base_strategy.py
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime, UTC
from ..utils.logger import logger
from ..database.database import db
from ..exchange.bybit import BybitClient
from ..indicators.macd import MACDIndicator


class StrategyStatus(Enum):
    """Статусы стратегии"""
    WAITING = "waiting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class BaseStrategy(ABC):
    """Базовый класс для всех торговых стратегий"""

    def __init__(self, telegram_id: int, strategy_name: str):
        self.telegram_id = telegram_id
        self.strategy_name = strategy_name
        self.status = StrategyStatus.WAITING
        self.strategy_id: Optional[int] = None
        self.start_time: Optional[datetime] = None
        self.stop_time: Optional[datetime] = None
        self.error_message: Optional[str] = None

        # ID пользователя в БД (получаем по telegram_id)
        self.user_id: Optional[int] = None

        # Компоненты стратегии
        self.bybit_client: Optional[BybitClient] = None
        self.macd_indicator: Optional[MACDIndicator] = None

        # Настройки пользователя
        self.user_settings: Optional[Dict[str, Any]] = None

        # Флаг активности
        self.is_active = False

    async def initialize(self) -> bool:
        """Инициализация стратегии"""
        try:
            logger.info(f"Инициализация стратегии {self.strategy_name} для пользователя {self.telegram_id}")

            # Получаем пользователя и его ID в БД
            user = db.get_or_create_user(self.telegram_id)
            self.user_id = user['id']
            logger.debug(f"User ID в БД: {self.user_id}")

            # Получаем настройки пользователя
            self.user_settings = db.get_user_settings(self.telegram_id)
            if not self.user_settings:
                raise Exception("Настройки пользователя не найдены")

            # Проверяем обязательные настройки
            if not self._validate_settings():
                return False

            # Инициализируем Bybit клиент
            api_key = self.user_settings.get('bybit_api_key')
            secret_key = self.user_settings.get('bybit_secret_key')

            if not api_key or not secret_key:
                raise Exception("API ключи не настроены")

            self.bybit_client = BybitClient(api_key, secret_key)

            # Тестируем подключение
            connection_test = await self.bybit_client.balance.test_connection()
            if not connection_test:
                raise Exception("Не удалось подключиться к Bybit API")

            # Инициализируем специфичные компоненты стратегии
            if not await self._initialize_strategy_components():
                return False

            logger.info(f"✅ Стратегия {self.strategy_name} успешно инициализирована")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации стратегии: {e}")
            self.error_message = str(e)
            self.status = StrategyStatus.ERROR
            return False

    async def start(self) -> bool:
        """Запуск стратегии"""
        try:
            if self.is_active:
                logger.warning("Стратегия уже запущена")
                return False

            # Инициализируем если еще не инициализирована
            if self.status == StrategyStatus.WAITING:
                if not await self.initialize():
                    return False

            # Сохраняем стратегию в БД (используем user_id, а не telegram_id)
            if self.user_id is None:
                raise Exception("User ID не определен")

            self.strategy_id = db.create_active_strategy(
                user_id=self.user_id,  # Используем правильный параметр
                strategy_name=self.strategy_name
            )

            self.start_time = datetime.now(UTC)
            self.status = StrategyStatus.RUNNING
            self.is_active = True

            logger.info(f"🚀 Запуск стратегии {self.strategy_name} (ID: {self.strategy_id})")

            # Запускаем логику стратегии
            await self._start_strategy_logic()

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка запуска стратегии: {e}")
            self.error_message = str(e)
            self.status = StrategyStatus.ERROR
            return False

    async def stop(self, reason: str = "Manual stop") -> bool:
        """Остановка стратегии"""
        try:
            if not self.is_active:
                logger.warning("Стратегия уже остановлена")
                return True

            logger.info(f"⏹️ Остановка стратегии {self.strategy_name}: {reason}")

            # Останавливаем логику стратегии
            await self._stop_strategy_logic()

            self.is_active = False
            self.status = StrategyStatus.STOPPED
            self.stop_time = datetime.now(UTC)

            # Обновляем статус в БД
            if self.strategy_id:
                db.update_active_strategy_status(self.strategy_id, "stopped")

            # Закрываем соединения
            await self._cleanup()

            logger.info(f"✅ Стратегия {self.strategy_name} остановлена")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка остановки стратегии: {e}")
            self.status = StrategyStatus.ERROR
            return False

    async def _cleanup(self):
        """Очистка ресурсов"""
        try:
            # ИСПРАВЛЕНО: Правильный порядок закрытия ресурсов
            if self.macd_indicator:
                logger.debug("Закрываем MACD индикатор...")
                await self.macd_indicator.close()
                self.macd_indicator = None

            if self.bybit_client:
                logger.debug("Закрываем Bybit клиент...")
                await self.bybit_client.close()
                self.bybit_client = None

            logger.debug("Ресурсы стратегии очищены")

        except Exception as e:
            logger.error(f"Ошибка очистки ресурсов: {e}")

    def _validate_settings(self) -> bool:
        """Проверка настроек пользователя"""
        if not self.user_settings:
            logger.error("Настройки пользователя отсутствуют")
            self.error_message = "Настройки пользователя не найдены"
            return False

        required_fields = [
            'bybit_api_key', 'bybit_secret_key', 'trading_pair',
            'leverage', 'entry_timeframe', 'exit_timeframe'
        ]

        missing_fields = []
        for field in required_fields:
            value = self.user_settings.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                missing_fields.append(field)

        if missing_fields:
            logger.error(f"Отсутствуют обязательные настройки: {', '.join(missing_fields)}")
            self.error_message = f"Не настроено: {', '.join(missing_fields)}"
            return False

        # Проверяем размер позиции
        position_size_info = db.get_position_size_info(self.telegram_id)
        if not position_size_info.get('value') or position_size_info.get('value') <= 0:
            logger.error("Размер позиции не настроен или равен нулю")
            self.error_message = "Размер позиции не настроен"
            return False

        # Проверяем корректность leverage
        leverage = self.user_settings.get('leverage')
        if not isinstance(leverage, int) or leverage < 1 or leverage > 100:
            logger.error(f"Некорректное плечо: {leverage}")
            self.error_message = "Некорректное значение плеча"
            return False

        # Проверяем корректность таймфреймов
        entry_tf = self.user_settings.get('entry_timeframe')
        exit_tf = self.user_settings.get('exit_timeframe')

        valid_timeframes = ['5m', '15m', '45m', '50m', '55m', '1h', '2h', '3h', '4h']

        if entry_tf not in valid_timeframes:
            logger.error(f"Некорректный таймфрейм входа: {entry_tf}")
            self.error_message = f"Неподдерживаемый таймфрейм входа: {entry_tf}"
            return False

        if exit_tf not in valid_timeframes:
            logger.error(f"Некорректный таймфрейм выхода: {exit_tf}")
            self.error_message = f"Неподдерживаемый таймфрейм выхода: {exit_tf}"
            return False

        logger.debug("✅ Все настройки пользователя валидны")
        return True

    def get_status_info(self) -> Dict[str, Any]:
        """Получение информации о статусе стратегии"""
        return {
            'strategy_name': self.strategy_name,
            'status': self.status.value,
            'is_active': self.is_active,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'stop_time': self.stop_time.isoformat() if self.stop_time else None,
            'error_message': self.error_message,
            'strategy_id': self.strategy_id,
            'telegram_id': self.telegram_id,
            'user_id': self.user_id
        }

    def get_settings_summary(self) -> Dict[str, Any]:
        """Получение краткой сводки настроек стратегии"""
        if not self.user_settings:
            return {}

        position_size_info = db.get_position_size_info(self.telegram_id)
        tp_sl_info = db.get_tp_sl_info(self.telegram_id)

        return {
            'trading_pair': self.user_settings.get('trading_pair'),
            'leverage': self.user_settings.get('leverage'),
            'entry_timeframe': self.user_settings.get('entry_timeframe'),
            'exit_timeframe': self.user_settings.get('exit_timeframe'),
            'position_size': position_size_info.get('display', 'не установлен'),
            'tp_sl_enabled': tp_sl_info.get('enabled', False),
            'tp_sl_display': tp_sl_info.get('display', 'не настроено'),
            'bot_duration_hours': self.user_settings.get('bot_duration_hours')
        }

    @abstractmethod
    async def _initialize_strategy_components(self) -> bool:
        """Инициализация компонентов специфичных для стратегии"""
        pass

    @abstractmethod
    async def _start_strategy_logic(self):
        """Запуск основной логики стратегии"""
        pass

    @abstractmethod
    async def _stop_strategy_logic(self):
        """Остановка логики стратегии"""
        pass
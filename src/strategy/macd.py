# src/strategy/macd.py
import asyncio
from typing import Dict, Any, Optional, Union
from enum import Enum
from datetime import datetime, timedelta
from ..indicators.macd_5m import MACD5mIndicator
from ..indicators.macd_45m import MACD45mIndicator
from ..exchange.bybit import BybitClient
from ..database.database import db
from ..utils.logger import logger
from ..utils.helpers import get_msk_time, format_msk_time


class PositionState(Enum):
    """Состояние позиции в стратегии"""
    NO_POSITION = "no_position"
    LONG_POSITION = "long_position"
    SHORT_POSITION = "short_position"


class StrategyState(Enum):
    """Состояние алгоритма торговли"""
    WAITING_FIRST_SIGNAL = "waiting_first_signal"  # Ждем первое пересечение в интервале
    POSITION_OPENED = "position_opened"  # Позиция открыта, ждем закрытия интервала
    CHECKING_CONFIRMATION = "checking_confirmation"  # Проверяем подтверждение на закрытии интервала
    WAITING_REVERSE_SIGNAL = "waiting_reverse_signal"  # Ждем обратного пересечения


class MACDStrategy:

    def __init__(self, telegram_id: int):
        self.telegram_id = telegram_id
        self.strategy_name = "MACD Full (Interval Filter)"
        self.position_state = PositionState.NO_POSITION
        self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
        self.is_active = False

        # Компоненты стратегии
        self.bybit_client: Optional[BybitClient] = None
        self.macd_indicator: Optional[Union[MACD5mIndicator, MACD45mIndicator]] = None

        # Настройки пользователя и торговые параметры
        self.user_settings: Optional[Dict[str, Any]] = None
        self.user_id: Optional[int] = None
        self.strategy_id: Optional[int] = None
        self.symbol: Optional[str] = None
        self.timeframe: Optional[str] = None

        # Параметры повторных попыток
        self.retry_attempts = 3
        self.retry_delay = 1.0

        # Время запуска
        self.start_time: Optional[datetime] = None
        self.error_message: Optional[str] = None

        # Счетчики для режима
        self.total_signals_received = 0
        self.signals_processed = 0
        self.last_signal_time: Optional[datetime] = None

        # НОВАЯ ЛОГИКА: Отслеживание интервалов и пересечений
        self.current_interval_start: Optional[datetime] = None
        self.first_signal_in_interval: Optional[Dict[str, Any]] = None
        self.last_interval_macd_state: Optional[Dict[str, Any]] = None  # Состояние MACD на закрытии интервала
        self.signals_blocked_until_interval_close = False

        # Защита от слишком частых операций
        self.min_operation_interval_seconds = 5  # Минимум 5 секунд между операциями
        self.last_operation_time: Optional[datetime] = None

    async def initialize(self) -> bool:
        """Инициализация стратегии"""
        try:
            logger.info(f"🔧 Инициализация MACD стратегии (новая логика) для пользователя {self.telegram_id}")

            # Получаем пользователя и настройки
            user = db.get_or_create_user(self.telegram_id)
            self.user_id = user['id']

            self.user_settings = db.get_user_settings(self.telegram_id)
            if not self.user_settings:
                raise Exception("Настройки пользователя не найдены")

            # Проверяем настройки
            if not self._validate_settings():
                return False

            # Извлекаем основные параметры
            self.symbol = self.user_settings.get('trading_pair')
            self.timeframe = self.user_settings.get('timeframe')

            logger.info(f"🎯 Выбранный таймфрейм: {self.timeframe}")

            # Инициализируем Bybit клиент
            api_key = self.user_settings.get('bybit_api_key')
            secret_key = self.user_settings.get('bybit_secret_key')

            self.bybit_client = BybitClient(api_key, secret_key)

            # Тестируем подключение
            async with self.bybit_client as client:
                connection_test = await client.balance.test_connection()
                if not connection_test:
                    raise Exception("Не удалось подключиться к Bybit API")

            # Устанавливаем плечо
            leverage = self.user_settings.get('leverage')
            async with self.bybit_client as client:
                leverage_result = await client.leverage.set_leverage(self.symbol, leverage)
                if leverage_result['success']:
                    logger.info(f"⚡ Плечо {leverage}x установлено для {self.symbol}")
                else:
                    logger.info(f"⚡ Плечо {leverage}x уже было установлено для {self.symbol}")

            # Тестируем расчет размера позиции
            test_position_size = await self._calculate_position_size()
            if not test_position_size:
                raise Exception("Не удалось рассчитать размер позиции")

            logger.info(f"✅ Тестовый размер позиции: {test_position_size}")

            # Инициализируем правильный MACD индикатор
            if self.timeframe == '5m':
                logger.info("🔧 Инициализация MACD 5m индикатора")
                self.macd_indicator = MACD5mIndicator(symbol=self.symbol, limit=200)
            elif self.timeframe == '45m':
                logger.info("🔧 Инициализация MACD 45m индикатора")
                self.macd_indicator = MACD45mIndicator(symbol=self.symbol, limit=200)
            else:
                raise Exception(f"Неподдерживаемый таймфрейм: {self.timeframe}")

            logger.info(f"✅ MACD стратегия инициализирована: {self.symbol} {self.timeframe}")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка инициализации MACD стратегии: {e}")
            self.error_message = str(e)
            return False

    def _validate_settings(self) -> bool:
        """Проверка настроек пользователя"""
        if not self.user_settings:
            logger.error("❌ Настройки пользователя отсутствуют")
            self.error_message = "Настройки пользователя не найдены"
            return False

        required_fields = [
            'bybit_api_key', 'bybit_secret_key', 'trading_pair',
            'leverage', 'timeframe'
        ]

        missing_fields = []
        for field in required_fields:
            value = self.user_settings.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                missing_fields.append(field)

        if missing_fields:
            logger.error(f"❌ Отсутствуют настройки: {', '.join(missing_fields)}")
            self.error_message = f"Не настроено: {', '.join(missing_fields)}"
            return False

        # Проверяем размер позиции
        position_size_info = db.get_position_size_info(self.telegram_id)
        if not position_size_info.get('value') or position_size_info.get('value') <= 0:
            logger.error("❌ Размер позиции не настроен")
            self.error_message = "Размер позиции не настроен"
            return False

        # Проверяем таймфрейм
        timeframe = self.user_settings.get('timeframe')
        if timeframe not in ['5m', '45m']:
            logger.error(f"❌ Неподдерживаемый таймфрейм: {timeframe}")
            self.error_message = f"Неподдерживаемый таймфрейм: {timeframe}"
            return False

        return True

    async def start(self) -> bool:
        """Запуск стратегии"""
        try:
            if self.is_active:
                logger.warning("⚠️ Стратегия уже запущена")
                return False

            # Инициализируем если еще не инициализирована
            if not await self.initialize():
                return False

            # Сохраняем стратегию в БД
            self.strategy_id = db.create_active_strategy(
                user_id=self.user_id,
                strategy_name=self.strategy_name
            )

            self.start_time = get_msk_time()
            self.is_active = True

            # Сбрасываем состояние стратегии
            self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
            self.current_interval_start = None
            self.first_signal_in_interval = None
            self.last_interval_macd_state = None
            self.signals_blocked_until_interval_close = False

            logger.info(f"🚀 Запуск MACD стратегии (новая логика) (ID: {self.strategy_id})")

            # Добавляем callback для MACD сигналов
            self.macd_indicator.add_callback(self._handle_macd_signal)

            # Запускаем MACD индикатор
            await self.macd_indicator.start()

            # Определяем начальное состояние позиции
            await self._determine_initial_position_state()

            logger.info(f"✅ MACD стратегия запущена: {self.symbol} {self.timeframe}")
            logger.info(f"📊 Состояние позиции: {self.position_state.value}")
            logger.info(f"🎯 Состояние алгоритма: {self.strategy_state.value}")
            logger.info(f"💹 Размер позиции: динамический расчет перед каждой сделкой")
            logger.info(f"🔧 Движок: {'MACD 5m' if self.timeframe == '5m' else 'MACD 45m'}")
            logger.info(f"🔄 Логика: Фильтрация по интервалам с подтверждением")

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка запуска MACD стратегии: {e}")
            self.error_message = str(e)
            self.is_active = False
            return False

    async def stop(self, reason: str = "Manual stop") -> bool:
        """Остановка стратегии"""
        try:
            if not self.is_active:
                return True

            logger.info(f"⏹️ Остановка MACD стратегии (новая логика): {reason}")

            # Останавливаем MACD индикатор
            if self.macd_indicator:
                await self.macd_indicator.stop()

            self.is_active = False

            # Обновляем статус в БД
            if self.strategy_id:
                db.update_active_strategy_status(self.strategy_id, "stopped")

            # Закрываем соединения
            await self._cleanup()

            # Логируем статистику
            logger.info(
                f"📊 Статистика: получено {self.total_signals_received} сигналов, обработано {self.signals_processed}"
            )
            logger.info(f"✅ MACD стратегия остановлена")

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка остановки MACD стратегии: {e}")
            return False

    async def _cleanup(self):
        """Очистка ресурсов"""
        try:
            if self.macd_indicator:
                # Новые индикаторы не требуют отдельного закрытия
                self.macd_indicator = None

        except Exception as e:
            logger.error(f"❌ Ошибка очистки ресурсов: {e}")

    def _is_new_interval(self, signal_timestamp: datetime) -> bool:
        """Проверка начала нового интервала"""
        if self.timeframe == '5m':
            # Для 5m интервал меняется каждые 5 минут (00, 05, 10, 15, ...)
            current_interval_minute = (signal_timestamp.minute // 5) * 5
            current_interval_start = signal_timestamp.replace(
                minute=current_interval_minute,
                second=0,
                microsecond=0
            )
        elif self.timeframe == '45m':
            # Для 45m используем логику из индикатора
            if hasattr(self.macd_indicator, 'get_45m_interval_start'):
                current_interval_start = self.macd_indicator.get_45m_interval_start(signal_timestamp)
            else:
                # Fallback для 45m
                day_start = signal_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                minutes_from_start = (signal_timestamp - day_start).total_seconds() / 60
                interval_number = int(minutes_from_start // 45)
                current_interval_start = day_start + timedelta(minutes=interval_number * 45)
        else:
            return False

        # Проверяем изменился ли интервал
        if self.current_interval_start is None:
            # Первый запуск - просто сохраняем текущий интервал
            self.current_interval_start = current_interval_start
            logger.info(
                f"🎯 Инициализация: текущий {self.timeframe} интервал {current_interval_start.strftime('%H:%M')}")
            return False
        elif self.current_interval_start != current_interval_start:
            # Интервал изменился
            old_interval = self.current_interval_start
            self.current_interval_start = current_interval_start

            logger.info(
                f"🔄 Новый {self.timeframe} интервал: {old_interval.strftime('%H:%M')} -> {current_interval_start.strftime('%H:%M')}")
            return True

        return False

    def _check_interval_by_time(self, signal_timestamp: datetime) -> bool:
        """Принудительная проверка интервала по времени"""
        if self.current_interval_start is None:
            return False

        # Вычисляем когда должен закрыться текущий интервал
        if self.timeframe == '5m':
            interval_end = self.current_interval_start + timedelta(minutes=5)
        elif self.timeframe == '45m':
            interval_end = self.current_interval_start + timedelta(minutes=45)
        else:
            return False

        # Проверяем прошло ли время закрытия интервала
        if signal_timestamp >= interval_end:
            logger.info(
                f"⏰ Принудительная проверка: интервал {self.current_interval_start.strftime('%H:%M')} должен был закрыться в {interval_end.strftime('%H:%M')}")

            # Обновляем текущий интервал
            if self.timeframe == '5m':
                new_interval_minute = (signal_timestamp.minute // 5) * 5
                self.current_interval_start = signal_timestamp.replace(
                    minute=new_interval_minute,
                    second=0,
                    microsecond=0
                )
            elif self.timeframe == '45m':
                if hasattr(self.macd_indicator, 'get_45m_interval_start'):
                    self.current_interval_start = self.macd_indicator.get_45m_interval_start(signal_timestamp)
                else:
                    day_start = signal_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                    minutes_from_start = (signal_timestamp - day_start).total_seconds() / 60
                    interval_number = int(minutes_from_start // 45)
                    self.current_interval_start = day_start + timedelta(minutes=interval_number * 45)

            logger.info(f"🔄 Обновлен интервал на: {self.current_interval_start.strftime('%H:%M')}")
            return True

        return False

    async def _handle_macd_signal(self, signal: Dict[str, Any]):
        """НОВАЯ ЛОГИКА: Обработка сигналов с фильтрацией по интервалам"""
        try:
            if not self.is_active:
                logger.warning("⚠️ Получен сигнал, но стратегия неактивна")
                return

            # Увеличиваем счетчик полученных сигналов
            self.total_signals_received += 1
            self.last_signal_time = get_msk_time()

            signal_type = signal.get('type')
            price = signal.get('price')
            crossover_type = signal.get('crossover_type')
            timeframe = signal.get('timeframe')
            signal_timestamp = signal.get('timestamp')

            current_time_msk = format_msk_time()
            logger.info(
                f"🎯 MACD сигнал #{self.total_signals_received}: {signal_type.upper()} ({crossover_type}) "
                f"при цене {price} (TF: {timeframe})"
            )
            logger.info(
                f"📊 Позиция: {self.position_state.value} | Алгоритм: {self.strategy_state.value} | Время: {current_time_msk} МСК")

            # Проверяем новый ли это интервал
            is_new_interval = self._is_new_interval(signal_timestamp)

            # Дополнительная проверка: принудительная проверка по времени
            if not is_new_interval:
                is_new_interval = self._check_interval_by_time(signal_timestamp)

            if is_new_interval:
                await self._handle_new_interval()

            # Проверяем защиту от частых операций
            if self.last_operation_time:
                time_since_last = (get_msk_time() - self.last_operation_time).total_seconds()
                if time_since_last < self.min_operation_interval_seconds:
                    logger.warning(
                        f"⚠️ Операция проигнорирована (защита): {time_since_last:.1f}с < {self.min_operation_interval_seconds}с"
                    )
                    return

            # Обрабатываем сигнал в зависимости от состояния стратегии
            if self.strategy_state == StrategyState.WAITING_FIRST_SIGNAL:
                await self._handle_first_signal_in_interval(signal)
            elif self.strategy_state == StrategyState.WAITING_REVERSE_SIGNAL:
                await self._handle_reverse_signal(signal)
            else:
                # В состояниях POSITION_OPENED и CHECKING_CONFIRMATION игнорируем сигналы
                logger.info(f"🔒 Сигнал проигнорирован: состояние {self.strategy_state.value}")

            self.signals_processed += 1
            logger.info(f"✅ Сигнал #{self.signals_processed} обработан")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки MACD сигнала: {e}")

    async def _handle_new_interval(self):
        """Обработка начала нового интервала"""
        logger.info(f"🆕 Начат новый {self.timeframe} интервал")

        # Если была позиция и ждали закрытия интервала - проверяем подтверждение
        if self.strategy_state == StrategyState.POSITION_OPENED:
            await self._check_signal_confirmation()

        # Сбрасываем блокировку сигналов и первый сигнал
        self.signals_blocked_until_interval_close = False
        self.first_signal_in_interval = None

        # Переходим в ожидание первого сигнала если нет позиции
        if self.position_state == PositionState.NO_POSITION:
            self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
            logger.info("🎯 Состояние: Ожидание первого сигнала в новом интервале")

    async def _handle_first_signal_in_interval(self, signal: Dict[str, Any]):
        """Обработка первого сигнала в интервале"""
        logger.info("🥇 Первый сигнал в интервале - открываем позицию")

        # Сохраняем первый сигнал
        self.first_signal_in_interval = signal.copy()

        # Открываем позицию
        if signal['type'] == 'buy':
            success = await self._open_long_position(signal)
            if success:
                self.position_state = PositionState.LONG_POSITION
        else:
            success = await self._open_short_position(signal)
            if success:
                self.position_state = PositionState.SHORT_POSITION

        if success:
            # Переходим в состояние "позиция открыта, ждем закрытия интервала"
            self.strategy_state = StrategyState.POSITION_OPENED
            self.signals_blocked_until_interval_close = True
            logger.info("🔒 Позиция открыта, сигналы заблокированы до закрытия интервала")

    async def _handle_reverse_signal(self, signal: Dict[str, Any]):
        """Обработка обратного сигнала (когда ждем разворот)"""
        if not self.first_signal_in_interval:
            logger.warning("⚠️ Нет сохраненного первого сигнала для сравнения")
            return

        # Проверяем что это действительно обратный сигнал
        first_signal_type = self.first_signal_in_interval['type']
        current_signal_type = signal['type']

        if first_signal_type != current_signal_type:
            logger.info(f"🔄 Обратный сигнал получен: {first_signal_type} -> {current_signal_type}")

            # Закрываем текущую позицию и открываем противоположную
            if self.position_state == PositionState.LONG_POSITION:
                await self._close_position_with_retry("LONG")
                success = await self._open_short_position(signal)
                if success:
                    self.position_state = PositionState.SHORT_POSITION
            elif self.position_state == PositionState.SHORT_POSITION:
                await self._close_position_with_retry("SHORT")
                success = await self._open_long_position(signal)
                if success:
                    self.position_state = PositionState.LONG_POSITION

            if success:
                # Обновляем первый сигнал и переходим в ожидание закрытия интервала
                self.first_signal_in_interval = signal.copy()
                self.strategy_state = StrategyState.POSITION_OPENED
                self.signals_blocked_until_interval_close = True
                logger.info("✅ Позиция развернута, ждем закрытия интервала")
        else:
            logger.info(f"🔄 Сигнал в том же направлении, игнорируем")

    async def _check_signal_confirmation(self):
        """Проверка подтверждения сигнала на закрытии интервала"""
        if not self.first_signal_in_interval:
            logger.warning("⚠️ Нет сигнала для проверки подтверждения")
            return

        # Получаем текущее состояние MACD
        current_macd_values = self.macd_indicator.get_current_macd_values()
        if not current_macd_values:
            logger.warning("⚠️ Не удалось получить текущие значения MACD")
            return

        current_macd = current_macd_values['macd_line']
        current_signal_line = current_macd_values['signal_line']
        first_signal_type = self.first_signal_in_interval['type']

        # Проверяем сохранилось ли пересечение
        if first_signal_type == 'buy':
            # Для бычьего сигнала MACD должна быть выше signal
            is_confirmed = current_macd > current_signal_line
        else:
            # Для медвежьего сигнала MACD должна быть ниже signal
            is_confirmed = current_macd < current_signal_line

        logger.info(
            f"🔍 Проверка подтверждения {first_signal_type} сигнала: "
            f"MACD={current_macd:.6f}, Signal={current_signal_line:.6f}, "
            f"Подтверждено: {'ДА' if is_confirmed else 'НЕТ'}"
        )

        if is_confirmed:
            # Сигнал подтвержден - ждем обратного пересечения
            self.strategy_state = StrategyState.WAITING_REVERSE_SIGNAL
            logger.info("✅ Сигнал подтвержден, ждем обратного пересечения")
        else:
            # Сигнал не подтвержден - разворачиваем позицию
            logger.info("❌ Сигнал НЕ подтвержден, разворачиваем позицию")
            await self._reverse_position()

    async def _reverse_position(self):
        """Разворот позиции при неподтвержденном сигнале"""
        if self.position_state == PositionState.LONG_POSITION:
            logger.info("🔄 Разворот: LONG -> SHORT")
            await self._close_position_with_retry("LONG")
            # Создаем фиктивный сигнал для открытия SHORT
            reverse_signal = {
                'type': 'sell',
                'price': self.macd_indicator.get_current_macd_values()['price'],
                'timestamp': get_msk_time()
            }
            success = await self._open_short_position(reverse_signal)
            if success:
                self.position_state = PositionState.SHORT_POSITION
                self.first_signal_in_interval = reverse_signal.copy()

        elif self.position_state == PositionState.SHORT_POSITION:
            logger.info("🔄 Разворот: SHORT -> LONG")
            await self._close_position_with_retry("SHORT")
            # Создаем фиктивный сигнал для открытия LONG
            reverse_signal = {
                'type': 'buy',
                'price': self.macd_indicator.get_current_macd_values()['price'],
                'timestamp': get_msk_time()
            }
            success = await self._open_long_position(reverse_signal)
            if success:
                self.position_state = PositionState.LONG_POSITION
                self.first_signal_in_interval = reverse_signal.copy()

        # Переходим в ожидание закрытия интервала для проверки нового сигнала
        self.strategy_state = StrategyState.POSITION_OPENED
        self.signals_blocked_until_interval_close = True
        logger.info("🔒 Позиция развернута, ждем закрытия интервала для проверки")

    async def _close_position_with_retry(self, position_type: str) -> bool:
        """Закрытие позиции с повторными попытками"""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with self.bybit_client as client:
                    result = await client.positions.close_position(self.symbol)

                if result['success']:
                    logger.info(f"✅ {position_type} позиция закрыта")
                    await self._record_trade_close(position_type, result)
                    self.last_operation_time = get_msk_time()
                    return True
                else:
                    error_msg = result.get('error', 'Unknown error')

                    # Проверяем специальные случаи
                    if "position" in error_msg.lower() and "not found" in error_msg.lower():
                        logger.info(f"📊 Позиция уже закрыта: {error_msg}")
                        return True

                    logger.warning(f"⚠️ Попытка {attempt}: {error_msg}")

            except Exception as e:
                logger.error(f"❌ Исключение при закрытии позиции (попытка {attempt}): {e}")

            if attempt < self.retry_attempts:
                await asyncio.sleep(self.retry_delay)

        logger.error(f"❌ Не удалось закрыть {position_type} позицию за {self.retry_attempts} попыток")
        return False

    async def _open_long_position(self, signal: Dict[str, Any]) -> bool:
        """Открытие лонг позиции с динамическим размером"""
        try:
            # Пересчитываем размер позиции с актуальной ценой
            current_position_size = await self._calculate_position_size()
            if not current_position_size:
                logger.error("❌ Не удалось рассчитать размер позиции")
                return False

            logger.info(f"💹 Размер позиции: {current_position_size} (цена: {signal['price']})")

            async with self.bybit_client as client:
                result = await client.orders.buy_market(
                    symbol=self.symbol,
                    qty=current_position_size
                )

            if result['success']:
                logger.info(f"✅ LONG позиция открыта: {result['order_id']}")
                await self._record_trade_open('LONG', signal, result)
                self.last_operation_time = get_msk_time()
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ Ошибка открытия LONG: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"❌ Исключение при открытии LONG: {e}")
            return False

    async def _open_short_position(self, signal: Dict[str, Any]) -> bool:
        """Открытие шорт позиции с динамическим размером"""
        try:
            # Пересчитываем размер позиции с актуальной ценой
            current_position_size = await self._calculate_position_size()
            if not current_position_size:
                logger.error("❌ Не удалось рассчитать размер позиции")
                return False

            logger.info(f"💹 Размер позиции: {current_position_size} (цена: {signal['price']})")

            async with self.bybit_client as client:
                result = await client.orders.sell_market(
                    symbol=self.symbol,
                    qty=current_position_size
                )

            if result['success']:
                logger.info(f"✅ SHORT позиция открыта: {result['order_id']}")
                await self._record_trade_open('SHORT', signal, result)
                self.last_operation_time = get_msk_time()
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ Ошибка открытия SHORT: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"❌ Исключение при открытии SHORT: {e}")
            return False

    async def _calculate_position_size(self) -> Optional[str]:
        """Расчет размера позиции на основе настроек пользователя с актуальной ценой"""
        try:
            position_info = db.get_position_size_info(self.telegram_id)

            # Получаем актуальную цену
            async with self.bybit_client as client:
                price_result = await client.price.get_price(self.symbol)
                if not price_result['success']:
                    raise Exception(f"Не удалось получить цену {self.symbol}")

                current_price = price_result['price']

            if position_info['type'] == 'fixed_usdt':
                # Фиксированная сумма в USDT
                usdt_amount = position_info['value']
            elif position_info['type'] == 'percentage':
                # Процент от баланса
                async with self.bybit_client as client:
                    balance_result = await client.balance.get_balance()

                balance = balance_result.get('free_usdt', 0)
                if balance <= 0:
                    raise Exception("Недостаточно средств на балансе")

                usdt_amount = balance * (position_info['value'] / 100)
            else:
                raise Exception("Неизвестный тип размера позиции")

            # Применяем плечо
            leverage = self.user_settings.get('leverage', 1)
            total_volume_usdt = usdt_amount * leverage

            # Рассчитываем количество
            quantity = total_volume_usdt / current_price

            # Форматируем с актуальными данными от биржи
            async with self.bybit_client as client:
                format_result = await client.symbol_info.format_quantity_for_symbol(self.symbol, quantity)

                if not format_result['success']:
                    raise Exception(f"Ошибка форматирования количества: {format_result['error']}")

                return format_result['formatted_quantity']

        except Exception as e:
            logger.error(f"❌ Ошибка расчета размера позиции: {e}")
            return None

    async def _determine_initial_position_state(self):
        """Определение начального состояния позиции"""
        try:
            async with self.bybit_client as client:
                positions_result = await client.positions.get_positions(self.symbol)

            if positions_result['success'] and positions_result['positions']:
                position = positions_result['positions'][0]
                side = position['side']
                size = position['size']

                if side == 'Buy':
                    self.position_state = PositionState.LONG_POSITION
                    self.strategy_state = StrategyState.WAITING_REVERSE_SIGNAL  # Ждем обратного сигнала
                    logger.info(f"📈 Обнаружена LONG позиция: {size}")
                elif side == 'Sell':
                    self.position_state = PositionState.SHORT_POSITION
                    self.strategy_state = StrategyState.WAITING_REVERSE_SIGNAL  # Ждем обратного сигнала
                    logger.info(f"📉 Обнаружена SHORT позиция: {size}")
            else:
                self.position_state = PositionState.NO_POSITION
                self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
                logger.info("📊 Открытых позиций нет")

        except Exception as e:
            logger.error(f"❌ Ошибка определения состояния позиции: {e}")
            self.position_state = PositionState.NO_POSITION
            self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL

    async def _record_trade_open(self, side: str, signal: Dict[str, Any], order_result: Dict[str, Any]):
        """Запись открытия сделки в историю"""
        try:
            if self.strategy_id and self.user_id:
                quantity = order_result.get('qty', 'unknown')
                if quantity == 'unknown':
                    current_size = await self._calculate_position_size()
                    quantity = current_size if current_size else 'unknown'

                trade_id = db.create_trade_record(
                    user_id=self.user_id,
                    strategy_id=self.strategy_id,
                    symbol=self.symbol,
                    side=side,
                    quantity=str(quantity),
                    order_id=order_result.get('order_id')
                )
                logger.info(f"📝 Записана сделка: ID={trade_id}, {side}, размер: {quantity}")
        except Exception as e:
            logger.error(f"❌ Ошибка записи сделки: {e}")

    async def _record_trade_close(self, side: str, close_result: Dict[str, Any]):
        """Запись закрытия сделки в историю"""
        try:
            logger.info(f"📝 Сделка {side} закрыта: {close_result.get('order_id')}")
        except Exception as e:
            logger.error(f"❌ Ошибка записи закрытия сделки: {e}")

    # Методы для получения информации о стратегии
    def get_status_info(self) -> Dict[str, Any]:
        """Получение информации о статусе стратегии"""
        return {
            'strategy_name': self.strategy_name,
            'is_active': self.is_active,
            'position_state': self.position_state.value,
            'strategy_state': self.strategy_state.value,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'position_size': 'dynamic',
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'error_message': self.error_message,
            'strategy_id': self.strategy_id,
            'telegram_id': self.telegram_id,
            'user_id': self.user_id,
            'total_signals_received': self.total_signals_received,
            'signals_processed': self.signals_processed,
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'current_interval_start': self.current_interval_start.isoformat() if self.current_interval_start else None,
            'signals_blocked': self.signals_blocked_until_interval_close,
            'first_signal_in_interval': self.first_signal_in_interval,
            'indicator_engine': f'MACD {self.timeframe}' if self.timeframe else 'Unknown'
        }

    def get_settings_summary(self) -> Dict[str, Any]:
        """Получение краткой сводки настроек стратегии"""
        if not self.user_settings:
            return {}

        position_size_info = db.get_position_size_info(self.telegram_id)

        return {
            'trading_pair': self.user_settings.get('trading_pair'),
            'leverage': self.user_settings.get('leverage'),
            'timeframe': self.timeframe,
            'position_size': position_size_info.get('display', '—'),
            'mode': f'Фильтрация по интервалам MACD {self.timeframe}',
            'engine': f'python-binance + {"Direct 5m" if self.timeframe == "5m" else "15m->45m conversion"}',
            'logic': 'Первый сигнал + подтверждение на закрытии интервала'
        }
# src/strategy/macd.py
import asyncio
from typing import Dict, Any, Optional, Union
from enum import Enum
from datetime import datetime, timedelta
from ..indicators.macd_5m import MACD5mIndicator
from ..indicators.macd_45m import MACD45mIndicator
from ..exchange.bybit import BybitClient
from ..utils.config import config
from ..utils.logger import logger
from ..utils.helpers import get_msk_time, format_msk_time


class PositionState(Enum):
    """Состояние позиции в стратегии"""
    NO_POSITION = "no_position"
    LONG_POSITION = "long_position"
    SHORT_POSITION = "short_position"


class StrategyState(Enum):
    """Состояние алгоритма торговли"""
    WAITING_FIRST_SIGNAL = "waiting_first_signal"
    POSITION_OPENED = "position_opened"
    CHECKING_CONFIRMATION = "checking_confirmation"
    WAITING_REVERSE_SIGNAL = "waiting_reverse_signal"


class MACDStrategy:
    """MACD стратегия"""

    def __init__(self):
        self.strategy_name = "MACD Full (Interval Filter)"
        self.position_state = PositionState.NO_POSITION
        self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
        self.is_active = False

        # Компоненты стратегии
        self.bybit_client: Optional[BybitClient] = None
        self.macd_indicator: Optional[Union[MACD5mIndicator, MACD45mIndicator]] = None

        # Торговые параметры из конфигурации
        self.symbol = config.trading_pair
        self.timeframe = config.timeframe
        self.leverage = config.leverage
        self.position_size_usdt = config.position_size_usdt

        # Параметры повторных попыток
        self.retry_attempts = 3
        self.retry_delay = 1.0

        # Время запуска
        self.start_time: Optional[datetime] = None
        self.error_message: Optional[str] = None

        # Счетчики
        self.total_signals_received = 0
        self.signals_processed = 0
        self.last_signal_time: Optional[datetime] = None

        # Логика интервалов и пересечений
        self.current_interval_start: Optional[datetime] = None
        self.first_signal_in_interval: Optional[Dict[str, Any]] = None
        self.last_interval_macd_state: Optional[Dict[str, Any]] = None
        self.signals_blocked_until_interval_close = False

        # Защита от частых операций
        self.min_operation_interval_seconds = 5
        self.last_operation_time: Optional[datetime] = None

        logger.info(f"🔧 Создана MACD стратегия: {self.symbol} {self.timeframe} {self.position_size_usdt}USDT {self.leverage}x")

    async def initialize(self) -> bool:
        """Инициализация стратегии"""
        try:
            logger.info(f"🔧 Инициализация MACD стратегии для {self.symbol}")

            # Валидация конфигурации
            config.validate()

            # Инициализируем Bybit клиент
            self.bybit_client = BybitClient(config.bybit_api_key, config.bybit_secret_key)

            # Тестируем подключение
            async with self.bybit_client as client:
                connection_test = await client.balance.test_connection()
                if not connection_test:
                    raise Exception("Не удалось подключиться к Bybit API")

            # Устанавливаем плечо
            async with self.bybit_client as client:
                leverage_result = await client.leverage.set_leverage(self.symbol, self.leverage)
                if leverage_result['success']:
                    logger.info(f"⚡ Плечо {self.leverage}x установлено для {self.symbol}")
                else:
                    logger.info(f"⚡ Плечо {self.leverage}x уже было установлено для {self.symbol}")

            # Тестируем расчет размера позиции
            test_position_size = await self._calculate_position_size()
            if not test_position_size:
                raise Exception("Не удалось рассчитать размер позиции")

            logger.info(f"✅ Тестовый размер позиции: {test_position_size}")

            # Инициализируем MACD индикатор
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

    async def start(self) -> bool:
        """Запуск стратегии"""
        try:
            if self.is_active:
                logger.warning("⚠️ Стратегия уже запущена")
                return False

            # Инициализируем если еще не инициализирована
            if not await self.initialize():
                return False

            self.start_time = get_msk_time()
            self.is_active = True

            # Сбрасываем состояние стратегии
            self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
            self.current_interval_start = None
            self.first_signal_in_interval = None
            self.last_interval_macd_state = None
            self.signals_blocked_until_interval_close = False

            logger.info(f"🚀 Запуск MACD стратегии")

            # Добавляем callback для MACD сигналов
            self.macd_indicator.add_callback(self._handle_macd_signal)

            # Запускаем MACD индикатор
            await self.macd_indicator.start()

            # Определяем начальное состояние позиции
            await self._determine_initial_position_state()

            logger.info(f"✅ MACD стратегия запущена: {self.symbol} {self.timeframe}")
            logger.info(f"📊 Состояние позиции: {self.position_state.value}")
            logger.info(f"🎯 Состояние алгоритма: {self.strategy_state.value}")
            logger.info(f"💹 Размер позиции: {self.position_size_usdt} USDT (с плечом {self.leverage}x)")
            logger.info(f"🔧 Движок: {'MACD 5m' if self.timeframe == '5m' else 'MACD 45m'}")

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

            logger.info(f"⏹️ Остановка MACD стратегии: {reason}")

            # Останавливаем MACD индикатор
            if self.macd_indicator:
                await self.macd_indicator.stop()

            self.is_active = False

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
                self.macd_indicator = None

        except Exception as e:
            logger.error(f"❌ Ошибка очистки ресурсов: {e}")

    def _is_new_interval(self, signal_timestamp: datetime) -> bool:
        """Проверка начала нового интервала"""
        if self.timeframe == '5m':
            current_interval_minute = (signal_timestamp.minute // 5) * 5
            current_interval_start = signal_timestamp.replace(
                minute=current_interval_minute,
                second=0,
                microsecond=0
            )
        elif self.timeframe == '45m':
            if hasattr(self.macd_indicator, 'get_45m_interval_start'):
                current_interval_start = self.macd_indicator.get_45m_interval_start(signal_timestamp)
            else:
                day_start = signal_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                minutes_from_start = (signal_timestamp - day_start).total_seconds() / 60
                interval_number = int(minutes_from_start // 45)
                current_interval_start = day_start + timedelta(minutes=interval_number * 45)
        else:
            return False

        if self.current_interval_start is None:
            self.current_interval_start = current_interval_start
            logger.info(
                f"🎯 Инициализация: текущий {self.timeframe} интервал {current_interval_start.strftime('%H:%M')}")
            return False
        elif self.current_interval_start != current_interval_start:
            old_interval = self.current_interval_start
            self.current_interval_start = current_interval_start

            logger.info(
                f"🔄 Новый {self.timeframe} интервал: {old_interval.strftime('%H:%M')} -> {current_interval_start.strftime('%H:%M')}")
            return True

        return False

    async def _handle_macd_signal(self, signal: Dict[str, Any]):
        """Обработка сигналов MACD"""
        try:
            if not self.is_active:
                logger.warning("⚠️ Получен сигнал, но стратегия неактивна")
                return

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
                logger.info(f"🔒 Сигнал проигнорирован: состояние {self.strategy_state.value}")

            self.signals_processed += 1
            logger.info(f"✅ Сигнал #{self.signals_processed} обработан")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки MACD сигнала: {e}")

    async def _handle_new_interval(self):
        """Обработка начала нового интервала"""
        logger.info(f"🆕 Начат новый {self.timeframe} интервал")

        if self.strategy_state == StrategyState.POSITION_OPENED:
            await self._check_signal_confirmation()

        self.signals_blocked_until_interval_close = False
        self.first_signal_in_interval = None

        if self.position_state == PositionState.NO_POSITION:
            self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
            logger.info("🎯 Состояние: Ожидание первого сигнала в новом интервале")

    async def _handle_first_signal_in_interval(self, signal: Dict[str, Any]):
        """Обработка первого сигнала в интервале"""
        logger.info("🥇 Первый сигнал в интервале - открываем позицию")

        self.first_signal_in_interval = signal.copy()

        if signal['type'] == 'buy':
            success = await self._open_long_position(signal)
            if success:
                self.position_state = PositionState.LONG_POSITION
        else:
            success = await self._open_short_position(signal)
            if success:
                self.position_state = PositionState.SHORT_POSITION

        if success:
            self.strategy_state = StrategyState.POSITION_OPENED
            self.signals_blocked_until_interval_close = True
            logger.info("🔒 Позиция открыта, сигналы заблокированы до закрытия интервала")

    async def _handle_reverse_signal(self, signal: Dict[str, Any]):
        """Обработка обратного сигнала"""
        if not self.first_signal_in_interval:
            logger.warning("⚠️ Нет сохраненного первого сигнала для сравнения")
            return

        first_signal_type = self.first_signal_in_interval['type']
        current_signal_type = signal['type']

        if first_signal_type != current_signal_type:
            logger.info(f"🔄 Обратный сигнал получен: {first_signal_type} -> {current_signal_type}")

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
                self.first_signal_in_interval = signal.copy()
                self.strategy_state = StrategyState.POSITION_OPENED
                self.signals_blocked_until_interval_close = True
                logger.info("✅ Позиция развернута, ждем закрытия интервала")

    async def _check_signal_confirmation(self):
        """Проверка подтверждения сигнала на закрытии интервала"""
        if not self.first_signal_in_interval:
            logger.warning("⚠️ Нет сигнала для проверки подтверждения")
            return

        current_macd_values = self.macd_indicator.get_current_macd_values()
        if not current_macd_values:
            logger.warning("⚠️ Не удалось получить текущие значения MACD")
            return

        current_macd = current_macd_values['macd_line']
        current_signal_line = current_macd_values['signal_line']
        first_signal_type = self.first_signal_in_interval['type']

        if first_signal_type == 'buy':
            is_confirmed = current_macd > current_signal_line
        else:
            is_confirmed = current_macd < current_signal_line

        logger.info(
            f"🔍 Проверка подтверждения {first_signal_type} сигнала: "
            f"MACD={current_macd:.6f}, Signal={current_signal_line:.6f}, "
            f"Подтверждено: {'ДА' if is_confirmed else 'НЕТ'}"
        )

        if is_confirmed:
            self.strategy_state = StrategyState.WAITING_REVERSE_SIGNAL
            logger.info("✅ Сигнал подтвержден, ждем обратного пересечения")
        else:
            logger.info("❌ Сигнал НЕ подтвержден, разворачиваем позицию")
            await self._reverse_position()

    async def _reverse_position(self):
        """Разворот позиции при неподтвержденном сигнале"""
        if self.position_state == PositionState.LONG_POSITION:
            logger.info("🔄 Разворот: LONG -> SHORT")
            await self._close_position_with_retry("LONG")
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
            reverse_signal = {
                'type': 'buy',
                'price': self.macd_indicator.get_current_macd_values()['price'],
                'timestamp': get_msk_time()
            }
            success = await self._open_long_position(reverse_signal)
            if success:
                self.position_state = PositionState.LONG_POSITION
                self.first_signal_in_interval = reverse_signal.copy()

        self.strategy_state = StrategyState.POSITION_OPENED
        self.signals_blocked_until_interval_close = True
        logger.info("🔒 Позиция развернута, ждем закрытия интервала для проверки")

    async def _open_long_position(self, signal: Dict[str, Any]) -> bool:
        """Открытие лонг позиции"""
        try:
            current_position_size = await self._calculate_position_size()
            if not current_position_size:
                logger.error("❌ Не удалось рассчитать размер позиции")
                return False

            logger.info(f"💹 Открываем LONG: {current_position_size} при цене {signal['price']}")

            async with self.bybit_client as client:
                result = await client.orders.buy_market(
                    symbol=self.symbol,
                    qty=current_position_size
                )

            if result['success']:
                logger.info(f"✅ LONG позиция открыта: {result['order_id']}")
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
        """Открытие шорт позиции"""
        try:
            current_position_size = await self._calculate_position_size()
            if not current_position_size:
                logger.error("❌ Не удалось рассчитать размер позиции")
                return False

            logger.info(f"💹 Открываем SHORT: {current_position_size} при цене {signal['price']}")

            async with self.bybit_client as client:
                result = await client.orders.sell_market(
                    symbol=self.symbol,
                    qty=current_position_size
                )

            if result['success']:
                logger.info(f"✅ SHORT позиция открыта: {result['order_id']}")
                self.last_operation_time = get_msk_time()
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ Ошибка открытия SHORT: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"❌ Исключение при открытии SHORT: {e}")
            return False

    async def _close_position_with_retry(self, position_type: str) -> bool:
        """Закрытие позиции с повторными попытками"""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with self.bybit_client as client:
                    result = await client.positions.close_position(self.symbol)

                if result['success']:
                    logger.info(f"✅ {position_type} позиция закрыта")
                    self.last_operation_time = get_msk_time()
                    return True
                else:
                    error_msg = result.get('error', 'Unknown error')

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

    async def _calculate_position_size(self) -> Optional[str]:
        """Расчет размера позиции"""
        try:
            # Получаем актуальную цену
            async with self.bybit_client as client:
                price_result = await client.price.get_price(self.symbol)
                if not price_result['success']:
                    raise Exception(f"Не удалось получить цену {self.symbol}")

                current_price = price_result['price']

            # Используем фиксированную сумму из конфигурации
            usdt_amount = self.position_size_usdt

            # Применяем плечо
            total_volume_usdt = usdt_amount * self.leverage

            # Рассчитываем количество
            quantity = total_volume_usdt / current_price

            # Форматируем с учетом требований биржи
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
                    self.strategy_state = StrategyState.WAITING_REVERSE_SIGNAL
                    logger.info(f"📈 Обнаружена LONG позиция: {size}")
                elif side == 'Sell':
                    self.position_state = PositionState.SHORT_POSITION
                    self.strategy_state = StrategyState.WAITING_REVERSE_SIGNAL
                    logger.info(f"📉 Обнаружена SHORT позиция: {size}")
            else:
                self.position_state = PositionState.NO_POSITION
                self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL
                logger.info("📊 Открытых позиций нет")

        except Exception as e:
            logger.error(f"❌ Ошибка определения состояния позиции: {e}")
            self.position_state = PositionState.NO_POSITION
            self.strategy_state = StrategyState.WAITING_FIRST_SIGNAL

    def get_status_info(self) -> Dict[str, Any]:
        """Получение информации о статусе стратегии"""
        return {
            'strategy_name': self.strategy_name,
            'is_active': self.is_active,
            'position_state': self.position_state.value,
            'strategy_state': self.strategy_state.value,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'position_size_usdt': self.position_size_usdt,
            'leverage': self.leverage,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'error_message': self.error_message,
            'total_signals_received': self.total_signals_received,
            'signals_processed': self.signals_processed,
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'current_interval_start': self.current_interval_start.isoformat() if self.current_interval_start else None,
            'signals_blocked': self.signals_blocked_until_interval_close,
            'first_signal_in_interval': self.first_signal_in_interval,
            'indicator_engine': f'MACD {self.timeframe}'
        }

    def print_status(self):
        """Вывод статуса в консоль"""
        print("\n" + "=" * 60)
        print("СТАТУС MACD СТРАТЕГИИ")
        print("=" * 60)
        print(f"Статус: {'🟢 АКТИВНА' if self.is_active else '🔴 ОСТАНОВЛЕНА'}")
        print(f"Символ: {self.symbol}")
        print(f"Таймфрейм: {self.timeframe}")
        print(f"Размер позиции: {self.position_size_usdt} USDT (плечо {self.leverage}x)")
        print(f"Состояние позиции: {self.position_state.value}")
        print(f"Состояние алгоритма: {self.strategy_state.value}")
        print(f"Всего сигналов: {self.total_signals_received}")
        print(f"Обработано: {self.signals_processed}")
        if self.last_signal_time:
            print(f"Последний сигнал: {format_msk_time(self.last_signal_time)}")
        if self.error_message:
            print(f"Ошибка: {self.error_message}")
        print("=" * 60)
# src/strategy/macd.py
import asyncio
from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime
from ..indicators.macd import MACDIndicator
from ..exchange.bybit import BybitClient
from ..database.database import db
from ..utils.logger import logger
from ..utils.helpers import get_msk_time, format_msk_time


class PositionState(Enum):
    """Состояние позиции в стратегии"""
    NO_POSITION = "no_position"
    LONG_POSITION = "long_position"
    SHORT_POSITION = "short_position"


class MACDStrategy:

    def __init__(self, telegram_id: int):
        self.telegram_id = telegram_id
        self.strategy_name = "MACD Full (Real-time)"
        self.position_state = PositionState.NO_POSITION
        self.is_active = False

        # Компоненты стратегии
        self.bybit_client: Optional[BybitClient] = None
        self.macd_indicator: Optional[MACDIndicator] = None

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

        # Счетчики для real-time режима
        self.total_signals_received = 0
        self.signals_processed = 0
        self.last_signal_time: Optional[datetime] = None

        # Защита от слишком частых сигналов (debounce)
        self.min_signal_interval_seconds = 10  # Минимум 10 секунд между сигналами
        self.last_processed_signal_time: Optional[datetime] = None

    async def initialize(self) -> bool:
        """Инициализация стратегии"""
        try:
            logger.info(f"🔧 Инициализация MACD стратегии для пользователя {self.telegram_id}")

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

            # Инициализируем MACD индикатор
            self.macd_indicator = MACDIndicator(
                symbol=self.symbol,
                timeframe=self.timeframe
            )

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

            logger.info(f"🚀 Запуск MACD стратегии (ID: {self.strategy_id})")

            # Добавляем callback для MACD сигналов
            self.macd_indicator.add_callback(self._handle_macd_signal)

            # Запускаем MACD индикатор
            await self.macd_indicator.start()

            # Определяем начальное состояние позиции
            await self._determine_initial_position_state()

            logger.info(f"✅ MACD стратегия запущена: {self.symbol} {self.timeframe}")
            logger.info(f"📊 Состояние позиции: {self.position_state.value}")
            logger.info(f"💹 Размер позиции: динамический расчет перед каждой сделкой")

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

            # Обновляем статус в БД
            if self.strategy_id:
                db.update_active_strategy_status(self.strategy_id, "stopped")

            # Закрываем соединения
            await self._cleanup()

            # Логируем статистику
            logger.info(
                f"📊 Статистика: получено {self.total_signals_received} сигналов, обработано {self.signals_processed}")
            logger.info(f"✅ MACD стратегия остановлена")

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка остановки MACD стратегии: {e}")
            return False

    async def _cleanup(self):
        """Очистка ресурсов"""
        try:
            if self.macd_indicator:
                await self.macd_indicator.close()
                self.macd_indicator = None

        except Exception as e:
            logger.error(f"❌ Ошибка очистки ресурсов: {e}")

    async def _handle_macd_signal(self, signal: Dict[str, Any]):
        """Обработка сигналов MACD с защитой от частых срабатываний"""
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

            current_time_msk = format_msk_time()
            logger.info(
                f"🎯 MACD сигнал #{self.total_signals_received}: {signal_type.upper()} ({crossover_type}) при цене {price}")
            logger.info(f"📊 Текущее состояние: {self.position_state.value} | Время: {current_time_msk} МСК")

            # Проверяем debounce (защита от слишком частых сигналов)
            if self.last_processed_signal_time:
                time_since_last = (get_msk_time() - self.last_processed_signal_time).total_seconds()
                if time_since_last < self.min_signal_interval_seconds:
                    logger.warning(
                        f"⚠️ Сигнал проигнорирован (debounce): {time_since_last:.1f}с < {self.min_signal_interval_seconds}с")
                    return

            # Обрабатываем сигнал
            if signal_type == 'buy':  # Бычье пересечение
                await self._handle_bullish_signal(signal)
            elif signal_type == 'sell':  # Медвежье пересечение
                await self._handle_bearish_signal(signal)
            else:
                logger.warning(f"⚠️ Неизвестный тип сигнала: {signal_type}")
                return

            # Обновляем время последней обработки
            self.last_processed_signal_time = get_msk_time()
            self.signals_processed += 1

            logger.info(f"✅ Сигнал #{self.signals_processed} обработан успешно")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки MACD сигнала: {e}")

    async def _handle_bullish_signal(self, signal: Dict[str, Any]):
        """Обработка бычьего сигнала - переход в лонг"""
        logger.info("🟢 Бычий сигнал: переход в LONG позицию")

        # Закрываем шорт если есть
        if self.position_state == PositionState.SHORT_POSITION:
            logger.info("📉 Закрываем SHORT позицию")
            close_success = await self._close_position_with_retry("SHORT")
            if not close_success:
                logger.warning("⚠️ Не удалось закрыть SHORT, пропускаем открытие LONG")
                return

        # Открываем лонг
        logger.info("📈 Открываем LONG позицию")
        open_success = await self._open_long_position(signal)

        if open_success:
            self.position_state = PositionState.LONG_POSITION
            logger.info("✅ Успешно перешли в LONG позицию")
        else:
            logger.warning("⚠️ Не удалось открыть LONG позицию")
            self.position_state = PositionState.NO_POSITION

    async def _handle_bearish_signal(self, signal: Dict[str, Any]):
        """Обработка медвежьего сигнала - переход в шорт"""
        logger.info("🔴 Медвежий сигнал: переход в SHORT позицию")

        # Закрываем лонг если есть
        if self.position_state == PositionState.LONG_POSITION:
            logger.info("📈 Закрываем LONG позицию")
            close_success = await self._close_position_with_retry("LONG")
            if not close_success:
                logger.warning("⚠️ Не удалось закрыть LONG, пропускаем открытие SHORT")
                return

        # Открываем шорт
        logger.info("📉 Открываем SHORT позицию")
        open_success = await self._open_short_position(signal)

        if open_success:
            self.position_state = PositionState.SHORT_POSITION
            logger.info("✅ Успешно перешли в SHORT позицию")
        else:
            logger.warning("⚠️ Не удалось открыть SHORT позицию")
            self.position_state = PositionState.NO_POSITION

    async def _close_position_with_retry(self, position_type: str) -> bool:
        """Закрытие позиции с повторными попытками"""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with self.bybit_client as client:
                    result = await client.positions.close_position(self.symbol)

                if result['success']:
                    logger.info(f"✅ {position_type} позиция закрыта")
                    await self._record_trade_close(position_type, result)
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
                    logger.info(f"📈 Обнаружена LONG позиция: {size}")
                elif side == 'Sell':
                    self.position_state = PositionState.SHORT_POSITION
                    logger.info(f"📉 Обнаружена SHORT позиция: {size}")
            else:
                self.position_state = PositionState.NO_POSITION
                logger.info("📊 Открытых позиций нет")

        except Exception as e:
            logger.error(f"❌ Ошибка определения состояния позиции: {e}")
            self.position_state = PositionState.NO_POSITION

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
            'min_signal_interval_seconds': self.min_signal_interval_seconds
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
            'position_size': position_size_info.get('display', 'не установлен'),
            'mode': 'Real-time динамический расчет размера'
        }
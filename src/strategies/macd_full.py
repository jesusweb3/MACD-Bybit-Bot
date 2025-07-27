# src/strategies/macd_full.py
import asyncio
from typing import Dict, Any, Optional, Tuple
from enum import Enum
from .base_strategy import BaseStrategy
from ..indicators.macd import MACDIndicator
from ..utils.logger import logger
from ..database.database import db


class PositionState(Enum):
    """Состояние позиции в стратегии"""
    NO_POSITION = "no_position"
    LONG_POSITION = "long_position"
    SHORT_POSITION = "short_position"


class MACDFullStrategy(BaseStrategy):
    """
    MACD Full стратегия - всегда в позиции
    При бычьем пересечении: закрыть шорт → открыть лонг
    При медвежьем пересечении: закрыть лонг → открыть шорт

    ИСПРАВЛЕНО: Правильная работа с кастомными таймфреймами
    """

    def __init__(self, telegram_id: int):
        super().__init__(telegram_id, "MACD Full")
        self.position_state = PositionState.NO_POSITION
        self.current_symbol: Optional[str] = None
        self.position_size: Optional[str] = None
        self.retry_attempts = 3
        self.retry_delay = 1.0  # секунды

        # Правила торговли (получаем из API)
        self.trading_rules: Optional[Dict[str, Any]] = None

    async def _initialize_strategy_components(self) -> bool:
        """Инициализация MACD индикатора для Full стратегии"""
        try:
            # ИСПРАВЛЕНО: Проверяем что таймфреймы одинаковые для MACD Full
            entry_tf = self.user_settings.get('entry_timeframe')
            exit_tf = self.user_settings.get('exit_timeframe')

            if not entry_tf or not exit_tf:
                raise Exception("Таймфреймы входа и выхода должны быть настроены")

            if entry_tf != exit_tf:
                raise Exception(f"Для MACD Full стратегии таймфреймы входа и выхода должны быть одинаковыми. "
                                f"Текущие: вход={entry_tf}, выход={exit_tf}")

            symbol = self.user_settings.get('trading_pair')
            if not symbol:
                raise Exception("Торговая пара не настроена")

            logger.info(f"Инициализация MACD для {symbol} на {entry_tf}")
            logger.info(f"Кастомный ТФ: {'Да' if self._is_custom_timeframe(entry_tf) else 'Нет'}")

            # Создаем MACD индикатор (используем одинаковый ТФ для входа и выхода)
            self.macd_indicator = MACDIndicator(
                symbol=symbol,
                entry_timeframe=entry_tf,
                exit_timeframe=entry_tf  # ВАЖНО: одинаковый ТФ для Full стратегии
            )

            # Устанавливаем leverage
            leverage = self.user_settings.get('leverage')
            logger.info(f"Устанавливаем плечо {leverage}x для {symbol}")

            leverage_result = await self.bybit_client.leverage.set_leverage(symbol, leverage)
            if not leverage_result['success']:
                logger.warning(f"Предупреждение при установке плеча: {leverage_result.get('error', 'Unknown')}")

            # Получаем правила торговли для символа
            await self._load_trading_rules(symbol)

            # Рассчитываем размер позиции
            self.position_size = await self._calculate_position_size()
            if not self.position_size:
                raise Exception("Не удалось рассчитать размер позиции")

            logger.info(f"Размер позиции: {self.position_size}")

            # Сохраняем текущий символ
            self.current_symbol = symbol

            return True

        except Exception as e:
            logger.error(f"Ошибка инициализации компонентов MACD Full: {e}")
            return False

    @staticmethod
    def _is_custom_timeframe(timeframe: str) -> bool:
        """Проверка является ли таймфрейм кастомным"""
        custom_timeframes = ['45m', '50m', '55m', '3h', '4h']
        return timeframe in custom_timeframes

    async def _load_trading_rules(self, symbol: str):
        """Загрузка правил торговли для символа"""
        try:
            logger.info(f"Загружаем правила торговли для {symbol}")

            # Устанавливаем значения по умолчанию
            self.trading_rules = {
                'min_qty': 0.01,
                'max_qty': 500.0,
                'qty_step': 0.01
            }

            # Пытаемся получить реальные правила
            try:
                params = {
                    'category': 'linear',
                    'symbol': symbol
                }

                # Создаем новую сессию для этого запроса
                import aiohttp
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    headers = self.bybit_client.balance._get_headers("")
                    url = f"{self.bybit_client.balance.base_url}/v5/market/instruments-info"

                    async with session.get(url, params=params, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()

                            if data.get('retCode') == 0:
                                result = data.get('result', {})
                                symbols = result.get('list', [])

                                if symbols:
                                    symbol_info = symbols[0]
                                    lot_size_filter = symbol_info.get('lotSizeFilter', {})

                                    self.trading_rules = {
                                        'min_qty': float(lot_size_filter.get('minOrderQty', 0.01)),
                                        'max_qty': float(lot_size_filter.get('maxOrderQty', 500.0)),
                                        'qty_step': float(lot_size_filter.get('qtyStep', 0.01))
                                    }

                                    logger.info(f"Правила торговли {symbol}:")
                                    logger.info(f"  Мин. количество: {self.trading_rules['min_qty']}")
                                    logger.info(f"  Макс. количество: {self.trading_rules['max_qty']}")
                                    logger.info(f"  Шаг количества: {self.trading_rules['qty_step']}")
                                    return

                            logger.warning(
                                f"Не удалось получить правила для {symbol}, используем значения по умолчанию")
                        else:
                            logger.warning(f"HTTP {response.status}, используем значения по умолчанию")

            except Exception as e:
                logger.warning(f"Ошибка получения правил торговли: {e}, используем значения по умолчанию")

            logger.info(f"Используем правила по умолчанию для {symbol}")

        except Exception as e:
            logger.error(f"Критическая ошибка при загрузке правил торговли: {e}")
            # В любом случае устанавливаем безопасные значения по умолчанию
            self.trading_rules = {
                'min_qty': 0.01,
                'max_qty': 500.0,
                'qty_step': 0.01
            }

    async def _start_strategy_logic(self):
        """Запуск логики MACD Full стратегии"""
        try:
            # ИСПРАВЛЕНО: Добавляем callback только для сигналов входа
            # Поскольку таймфреймы одинаковые, используем только entry callback
            self.macd_indicator.add_entry_callback(self._handle_macd_signal)

            # Запускаем MACD индикатор
            logger.info("🚀 Запускаем MACD индикатор...")
            await self.macd_indicator.start()

            # Определяем начальное состояние позиции
            await self._determine_initial_position_state()

            logger.info(f"🎯 MACD Full стратегия запущена для {self.current_symbol}")
            logger.info(f"📊 Начальное состояние позиции: {self.position_state.value}")
            logger.info(f"📈 Используемый таймфрейм: {self.user_settings.get('entry_timeframe')}")

        except Exception as e:
            logger.error(f"Ошибка запуска логики MACD Full: {e}")
            raise

    async def _stop_strategy_logic(self):
        """Остановка логики стратегии"""
        try:
            if self.macd_indicator:
                logger.info("⏹️ Останавливаем MACD индикатор...")
                await self.macd_indicator.stop()

        except Exception as e:
            logger.error(f"Ошибка остановки логики MACD Full: {e}")

    async def _handle_macd_signal(self, signal: Dict[str, Any]):
        """Обработка сигналов MACD"""
        try:
            if not self.is_active:
                logger.warning("⚠️ Получен сигнал, но стратегия неактивна")
                return

            signal_type = signal.get('type')
            price = signal.get('price')
            crossover_type = signal.get('crossover_type')
            timeframe = signal.get('timeframe')

            logger.info(f"📊 MACD сигнал на {timeframe}: {signal_type} ({crossover_type}) при цене {price}")
            logger.info(f"🔄 Текущее состояние: {self.position_state.value}")

            if signal_type == 'buy':  # Бычье пересечение
                await self._handle_bullish_signal(signal)

            elif signal_type == 'sell':  # Медвежье пересечение
                await self._handle_bearish_signal(signal)

            else:
                logger.warning(f"⚠️ Неизвестный тип сигнала: {signal_type}")

        except Exception as e:
            logger.error(f"Ошибка обработки MACD сигнала: {e}")
            # НЕ останавливаем стратегию при ошибках торговли - продолжаем работу
            logger.warning("⚠️ Стратегия продолжает работу, ожидаем следующий сигнал")

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
            logger.warning("⚠️ Не удалось открыть LONG позицию, остаемся без позиции")
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
            logger.warning("⚠️ Не удалось открыть SHORT позицию, остаемся без позиции")
            self.position_state = PositionState.NO_POSITION

    async def _close_position_with_retry(self, position_type: str) -> bool:
        """Закрытие позиции с повторными попытками"""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                logger.info(f"🔄 Попытка {attempt}/{self.retry_attempts} закрытия {position_type} позиции")

                result = await self.bybit_client.positions.close_position(self.current_symbol)

                if result['success']:
                    logger.info(f"✅ {position_type} позиция успешно закрыта")
                    # Записываем сделку в историю
                    await self._record_trade_close(position_type, result)
                    return True
                else:
                    error_msg = result.get('error', 'Unknown error')
                    logger.warning(f"⚠️ Не удалось закрыть позицию: {error_msg}")

                    # Проверяем специальные случаи
                    if "position" in error_msg.lower() and "not found" in error_msg.lower():
                        logger.warning(f"📊 Позиция уже закрыта или не найдена: {error_msg}")
                        return True  # Считаем успехом если позиция уже закрыта

            except Exception as e:
                logger.error(f"❌ Исключение при закрытии позиции (попытка {attempt}): {e}")

            if attempt < self.retry_attempts:
                logger.info(f"⏳ Ожидание {self.retry_delay}с перед следующей попыткой")
                await asyncio.sleep(self.retry_delay)

        # Все попытки исчерпаны
        logger.error(f"❌ Не удалось закрыть {position_type} позицию за {self.retry_attempts} попыток")
        return False

    async def _open_long_position(self, signal: Dict[str, Any]) -> bool:
        """Открытие лонг позиции"""
        try:
            # Получаем TP/SL настройки
            tp_price, sl_price = self._calculate_tp_sl_prices(signal['price'], 'long')

            result = await self.bybit_client.orders.buy_market(
                symbol=self.current_symbol,
                qty=self.position_size,
                take_profit=tp_price,
                stop_loss=sl_price
            )

            if result['success']:
                logger.info(f"✅ LONG позиция открыта: {result['order_id']}")
                logger.info(f"📊 Размер: {self.position_size}")
                if tp_price:
                    logger.info(f"🎯 TP: {tp_price}, SL: {sl_price}")

                # Записываем сделку в историю
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
        """Открытие шорт позиции"""
        try:
            # Получаем TP/SL настройки
            tp_price, sl_price = self._calculate_tp_sl_prices(signal['price'], 'short')

            result = await self.bybit_client.orders.sell_market(
                symbol=self.current_symbol,
                qty=self.position_size,
                take_profit=tp_price,
                stop_loss=sl_price
            )

            if result['success']:
                logger.info(f"✅ SHORT позиция открыта: {result['order_id']}")
                logger.info(f"📊 Размер: {self.position_size}")
                if tp_price:
                    logger.info(f"🎯 TP: {tp_price}, SL: {sl_price}")

                # Записываем сделку в историю
                await self._record_trade_open('SHORT', signal, result)
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ Ошибка открытия SHORT: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"❌ Исключение при открытии SHORT: {e}")
            return False

    def _calculate_tp_sl_prices(self, entry_price: float, side: str) -> Tuple[Optional[float], Optional[float]]:
        """Расчет цен TP/SL"""
        tp_sl_info = db.get_tp_sl_info(self.telegram_id)

        if not tp_sl_info['enabled']:
            return None, None

        take_profit_points = tp_sl_info.get('take_profit')
        stop_loss_points = tp_sl_info.get('stop_loss')

        if not take_profit_points or not stop_loss_points:
            return None, None

        if side == 'long':
            tp_price = entry_price + take_profit_points
            sl_price = entry_price - stop_loss_points
        else:  # short
            tp_price = entry_price - take_profit_points
            sl_price = entry_price + stop_loss_points

        return tp_price, sl_price

    async def _calculate_position_size(self) -> Optional[str]:
        """
        Расчет размера позиции на основе настроек пользователя
        ИСПРАВЛЕНО: Улучшена обработка ошибок
        """
        try:
            position_info = db.get_position_size_info(self.telegram_id)
            symbol = self.user_settings.get('trading_pair')

            # Получаем текущую цену
            price_result = await self.bybit_client.price.get_price(symbol)
            if not price_result['success']:
                raise Exception(f"Не удалось получить цену {symbol}: {price_result.get('error')}")

            current_price = price_result['price']
            logger.info(f"💲 Текущая цена {symbol}: {current_price}")

            if position_info['type'] == 'fixed_usdt':
                # Фиксированная сумма в USDT
                usdt_amount = position_info['value']
                logger.info(f"💰 Фиксированная сумма: {usdt_amount} USDT")

            elif position_info['type'] == 'percentage':
                # Процент от баланса
                balance_result = await self.bybit_client.balance.get_balance()
                balance = balance_result.get('free_usdt', 0)

                if balance <= 0:
                    raise Exception("Недостаточно средств на балансе")

                usdt_amount = balance * (position_info['value'] / 100)
                logger.info(f"💰 {position_info['value']}% от баланса {balance:.2f} = {usdt_amount:.2f} USDT")

            else:
                raise Exception("Неизвестный тип размера позиции")

            # Применяем плечо
            leverage = self.user_settings.get('leverage', 1)
            total_volume_usdt = usdt_amount * leverage
            logger.info(f"📊 Объем с плечом {leverage}x: {total_volume_usdt} USDT")

            # Рассчитываем количество
            base_asset = symbol.replace('USDT', '')
            quantity = total_volume_usdt / current_price
            logger.info(f"⚖️ Количество {base_asset} (точное): {quantity:.8f}")

            # Округляем согласно правилам торговли
            if self.trading_rules:
                min_qty = self.trading_rules.get('min_qty', 0.01)
                qty_step = self.trading_rules.get('qty_step', 0.01)

                logger.info(f"📏 Правила: мин={min_qty}, шаг={qty_step}")

                # Корректируем по шагу
                corrected_qty = round(quantity / qty_step) * qty_step
                # Дополнительно округляем для избежания ошибок точности
                corrected_qty = round(corrected_qty, 8)

                # Проверяем минимум
                if corrected_qty < min_qty:
                    corrected_qty = min_qty
                    logger.warning(f"⚠️ Количество скорректировано до минимума: {corrected_qty}")

                logger.info(f"🎯 Скорректированное количество: {corrected_qty} {base_asset}")
                return str(corrected_qty)
            else:
                # Fallback: округляем до разумного количества знаков
                rounded_qty = round(quantity, 6)
                if rounded_qty < 0.000001:
                    rounded_qty = 0.000001

                logger.info(f"🎯 Округленное количество (fallback): {rounded_qty} {base_asset}")
                return str(rounded_qty)

        except Exception as e:
            logger.error(f"Ошибка расчета размера позиции: {e}")
            return None

    async def _determine_initial_position_state(self):
        """Определение начального состояния позиции"""
        try:
            logger.info("🔍 Проверяем начальное состояние позиции...")
            positions_result = await self.bybit_client.positions.get_positions(self.current_symbol)

            if positions_result['success'] and positions_result['positions']:
                position = positions_result['positions'][0]
                side = position['side']
                size = position['size']

                if side == 'Buy':
                    self.position_state = PositionState.LONG_POSITION
                    logger.info(f"📈 Обнаружена существующая LONG позиция: {size}")
                elif side == 'Sell':
                    self.position_state = PositionState.SHORT_POSITION
                    logger.info(f"📉 Обнаружена существующая SHORT позиция: {size}")
            else:
                self.position_state = PositionState.NO_POSITION
                logger.info("📊 Открытых позиций не обнаружено")

        except Exception as e:
            logger.error(f"Ошибка определения состояния позиции: {e}")
            self.position_state = PositionState.NO_POSITION
            logger.warning("⚠️ Устанавливаем состояние 'нет позиции' по умолчанию")

    async def _record_trade_open(self, side: str, signal: Dict[str, Any], order_result: Dict[str, Any]):
        """Запись открытия сделки в историю"""
        try:
            if self.strategy_id and self.user_id:
                trade_id = db.create_trade_record(
                    user_id=self.user_id,
                    strategy_id=self.strategy_id,
                    symbol=self.current_symbol,
                    side=side,
                    quantity=self.position_size,
                    order_id=order_result.get('order_id')
                )
                logger.info(f"📝 Записана сделка открытия: ID={trade_id}, сигнал: {signal['type']}")
        except Exception as e:
            logger.error(f"Ошибка записи сделки открытия: {e}")

    async def _record_trade_close(self, side: str, close_result: Dict[str, Any]):
        """Запись закрытия сделки в историю"""
        try:
            # TODO: Реализовать обновление записи сделки при закрытии
            logger.info(f"📝 Сделка {side} закрыта: {close_result.get('order_id')}")
        except Exception as e:
            logger.error(f"Ошибка записи закрытия сделки: {e}")

    def get_position_info(self) -> Dict[str, Any]:
        """Получение информации о текущей позиции"""
        return {
            'position_state': self.position_state.value,
            'symbol': self.current_symbol,
            'position_size': self.position_size
        }
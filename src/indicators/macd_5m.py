# src/indicators/macd_5m.py
import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Union, Awaitable
from binance.client import Client
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from ..utils.logger import logger


class MACD5mIndicator:
    """
    MACD индикатор для 5-минутного таймфрейма
    Использует прямые 5m свечи от Binance
    """

    def __init__(self, symbol: str, limit: int = 200):
        self.symbol = symbol.upper()
        self.limit = limit
        self.klines_data: List[float] = []
        self.macd_data: List[Dict[str, Any]] = []
        self.ws_client: Optional[UMFuturesWebsocketClient] = None

        # MACD параметры
        self.fast_period = 12
        self.slow_period = 26
        self.signal_period = 7

        # Callback функции для сигналов
        self.callbacks: List[
            Union[Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]
        ] = []

        # Флаги состояния
        self.is_running = False

        # Последние значения MACD для отслеживания пересечений
        self.last_macd_line: Optional[float] = None
        self.last_signal_line: Optional[float] = None

        # Счетчики для статистики
        self.total_updates = 0

        # Добавляем поля для синхронизации
        self.last_sync_time = None
        self.sync_interval = 300  # Ресинхронизация каждые 5 минут

        # Для периодического отображения MACD (раз в 60 секунд)
        self.last_macd_display_time = None
        self.macd_display_interval = 60  # Показывать MACD раз в 60 секунд

    def add_callback(self, callback: Union[
        Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]):
        """Добавить callback для сигналов"""
        self.callbacks.append(callback)

    def get_historical_data(self):
        """Получение максимально свежих исторических данных"""
        try:
            client = Client()

            logger.info(f"📈 Загружаем историю {self.symbol} для 5m MACD")

            # Получаем серверное время Binance для синхронизации
            server_time = client.get_server_time()
            logger.info(f"[SYNC] Серверное время Binance: {pd.to_datetime(server_time['serverTime'], unit='ms')}")

            # Получаем исторические 5m свечи с учетом серверного времени
            klines = client.futures_klines(
                symbol=self.symbol,
                interval='5m',
                limit=self.limit
            )

            # Преобразуем в DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
                'taker_buy_quote_volume', 'ignore'
            ])

            # Конвертируем типы данных
            df['close'] = df['close'].astype(float)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')

            # Показываем информацию о последних свечах
            logger.info(f"[HISTORY] Последние 3 свечи:")
            for i in range(3):
                idx = -(3 - i)
                candle = df.iloc[idx]
                logger.info(f"  {candle['timestamp']} - {candle['close_time']}: {candle['close']}")

            # НЕ убираем последнюю свечу - она может быть закрытой
            self.klines_data = df['close'].tolist()
            self.last_sync_time = datetime.now()

            # Показываем последние 5 исторических цен для отладки
            logger.info(f"[DEBUG] Последние 5 исторических цен: {self.klines_data[-5:]}")

            logger.info(f"✅ Загружено {len(self.klines_data)} исторических 5m свечей")

            # Рассчитываем начальный MACD
            self.calculate_macd()

        except Exception as e:
            logger.error(f"❌ Ошибка получения исторических данных: {e}")
            raise

    @staticmethod
    def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        """Расчет EMA с максимальной точностью"""
        prices = np.array(prices, dtype=np.float64)  # Повышенная точность

        if len(prices) < period:
            return np.full_like(prices, np.nan, dtype=np.float64)

        ema = np.full_like(prices, np.nan, dtype=np.float64)
        alpha = np.float64(2.0) / np.float64(period + 1.0)

        # Находим первый не-NaN элемент для инициализации
        first_valid = period - 1
        for i in range(len(prices)):
            if not np.isnan(prices[i]):
                first_valid = max(i, period - 1)
                break

        if first_valid >= len(prices):
            return ema

        # Первое значение EMA = SMA первых period значений
        if first_valid + period <= len(prices):
            valid_window = prices[first_valid - period + 1:first_valid + 1]
            if not np.any(np.isnan(valid_window)):
                ema[first_valid] = np.mean(valid_window, dtype=np.float64)
            elif first_valid < len(prices):
                ema[first_valid] = prices[first_valid]

        # Остальные значения по формуле EMA с повышенной точностью
        for i in range(first_valid + 1, len(prices)):
            if not np.isnan(prices[i]) and not np.isnan(ema[i - 1]):
                ema[i] = alpha * prices[i] + (np.float64(1.0) - alpha) * ema[i - 1]

        return ema

    def calculate_macd(self) -> Optional[Dict[str, Any]]:
        """Расчет MACD точно как в TradingView/Binance"""
        if len(self.klines_data) < 32:  # 26 + 7 - 1
            return None

        prices = np.array(self.klines_data, dtype=np.float64)  # Повышенная точность

        # Рассчитываем EMA12 и EMA26 с максимальной точностью
        ema12 = self.calculate_ema(prices, 12)
        ema26 = self.calculate_ema(prices, 26)

        # MACD Line = EMA12 - EMA26 (без округления)
        macd_line = np.full_like(prices, np.nan, dtype=np.float64)

        # MACD считается только там, где есть оба EMA
        for i in range(len(prices)):
            if not np.isnan(ema12[i]) and not np.isnan(ema26[i]):
                macd_line[i] = ema12[i] - ema26[i]

        # Signal Line = EMA7 от MACD (только от валидных значений MACD)
        first_macd_idx = None
        for i in range(len(macd_line)):
            if not np.isnan(macd_line[i]):
                first_macd_idx = i
                break

        if first_macd_idx is None or len(macd_line) - first_macd_idx < 7:
            return None

        # Берем только валидную часть MACD для расчета Signal
        valid_macd = macd_line[first_macd_idx:]
        signal_ema = self.calculate_ema(valid_macd, 7)

        # Восстанавливаем Signal в полный массив
        signal_line = np.full_like(prices, np.nan, dtype=np.float64)
        signal_line[first_macd_idx:] = signal_ema

        # Получаем последние значения БЕЗ округления
        current_price = float(prices[-1])
        current_macd = float(macd_line[-1]) if not np.isnan(macd_line[-1]) else 0.0
        current_signal = float(signal_line[-1]) if not np.isnan(signal_line[-1]) else 0.0
        current_histogram = current_macd - current_signal

        # Проверяем что значения валидны
        if np.isnan(current_macd) or np.isnan(current_signal):
            return None

        # Создаем данные MACD БЕЗ промежуточного округления
        macd_data = {
            'timestamp': datetime.now(),
            'price': current_price,  # Без округления
            'macd_line': current_macd,  # Без округления
            'signal_line': current_signal,  # Без округления
            'histogram': current_histogram,  # Без округления
            'timeframe': '5m'
        }

        self.macd_data.append(macd_data)

        # Проверяем сигналы
        signal = self.detect_macd_signals(current_macd, current_signal, macd_data)

        # Показываем MACD значения только раз в 60 секунд для отладки
        current_time = datetime.now()
        should_display = False

        if self.last_macd_display_time is None:
            should_display = True
        else:
            time_since_display = (current_time - self.last_macd_display_time).total_seconds()
            if time_since_display >= self.macd_display_interval:
                should_display = True

        if should_display:
            # Округляем ТОЛЬКО для отображения
            display_price = round(current_price, 2)
            display_macd = round(current_macd, 2)
            display_signal = round(current_signal, 2)
            display_histogram = round(current_histogram, 2)

            logger.info(
                f"📊 MACD 5m: Цена: {display_price} | "
                f"MACD: {display_macd} | "
                f"Signal: {display_signal} | "
                f"Hist: {display_histogram}"
            )

            self.last_macd_display_time = current_time

        return macd_data

    def detect_macd_signals(self, current_macd: float, current_signal: float,
                            macd_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Определение сигналов MACD при пересечении линий"""
        if self.last_macd_line is None or self.last_signal_line is None:
            # Сохраняем текущие значения и выходим
            self.last_macd_line = current_macd
            self.last_signal_line = current_signal
            return None

        signal = None

        # ПЕРЕСЕЧЕНИЕ СНИЗУ ВВЕРХ: бычий сигнал
        if (self.last_macd_line < self.last_signal_line and
                current_macd > current_signal):

            signal = {
                'type': 'buy',
                'timeframe': '5m',
                'timestamp': macd_data['timestamp'],
                'price': macd_data['price'],
                'macd_line': current_macd,
                'signal_line': current_signal,
                'histogram': macd_data['histogram'],
                'crossover_type': 'bullish'
            }

        # ПЕРЕСЕЧЕНИЕ СВЕРХУ ВНИЗ: медвежий сигнал
        elif (self.last_macd_line > self.last_signal_line and
              current_macd < current_signal):

            signal = {
                'type': 'sell',
                'timeframe': '5m',
                'timestamp': macd_data['timestamp'],
                'price': macd_data['price'],
                'macd_line': current_macd,
                'signal_line': current_signal,
                'histogram': macd_data['histogram'],
                'crossover_type': 'bearish'
            }

        # Обновляем предыдущие значения
        self.last_macd_line = current_macd
        self.last_signal_line = current_signal

        if signal:
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ MACD 5m! {signal['crossover_type'].upper()} сигнал {signal['type'].upper()}")

            # Вызываем callback'и безопасно
            self._call_callbacks_safe(signal)

        return signal

    async def _call_callbacks(self, signal: Dict[str, Any]):
        """Вызов всех callback функций"""
        for callback in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(signal)
                else:
                    callback(signal)
            except Exception as e:
                logger.error(f"❌ Ошибка в callback: {e}")

    def _call_callbacks_safe(self, signal: Dict[str, Any]):
        """Безопасный вызов callback функций из синхронного контекста"""
        for callback in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    # Для асинхронных callback создаем задачу в текущем event loop
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Если event loop уже запущен, создаем задачу
                            asyncio.create_task(callback(signal))
                        else:
                            # Если event loop не запущен, запускаем корутину
                            asyncio.run(callback(signal))
                    except RuntimeError:
                        # Если нет event loop, создаем новый
                        asyncio.run(callback(signal))
                else:
                    # Для синхронных callback вызываем напрямую
                    callback(signal)
            except Exception as e:
                logger.error(f"❌ Ошибка в callback: {e}")

    def handle_kline_message(self, _, message):
        """Обработка WebSocket сообщений с данными свечей"""
        try:
            data = json.loads(message)

            if 'k' in data:
                kline = data['k']
                close_price = float(kline['c'])
                is_kline_closed = kline['x']  # True если свеча закрылась

                if is_kline_closed:
                    # Свеча закрылась - добавляем новую свечу с этой ценой закрытия
                    self.klines_data.append(close_price)
                    logger.info(
                        f"[НОВАЯ СВЕЧА] Время: {pd.to_datetime(kline['t'], unit='ms')} | "
                        f"Закрытие: {close_price} | Всего свечей: {len(self.klines_data)}"
                    )

                    # Ограничиваем размер массива для производительности
                    if len(self.klines_data) > self.limit + 50:
                        self.klines_data = self.klines_data[-self.limit:]
                        logger.info(f"[ОБРЕЗКА] Массив обрезан до {len(self.klines_data)} свечей")
                else:
                    # Свеча ещё идёт - обновляем последнюю цену
                    if len(self.klines_data) > 0:
                        self.klines_data[-1] = close_price
                    else:
                        # Первая свеча после запуска
                        self.klines_data.append(close_price)

                self.total_updates += 1

                # Пересчитываем MACD с каждым обновлением
                self.calculate_macd()

        except Exception as e:
            logger.error(f"❌ Ошибка обработки WebSocket сообщения: {e}")

    def start_websocket(self):
        """Запуск WebSocket соединения"""
        try:
            self.ws_client = UMFuturesWebsocketClient(
                on_message=self.handle_kline_message
            )

            # Подписываемся на 5m kline данные
            self.ws_client.kline(
                symbol=self.symbol.lower(),
                interval='5m'
            )

            logger.info(f"🚀 WebSocket подключен для {self.symbol} 5m")

        except Exception as e:
            logger.error(f"❌ Ошибка WebSocket подключения: {e}")
            raise

    def stop_websocket(self):
        """Остановка WebSocket соединения"""
        if self.ws_client:
            try:
                self.ws_client.stop()
                logger.info("⏹️ WebSocket 5m соединение закрыто")
            except Exception as e:
                logger.error(f"❌ Ошибка закрытия WebSocket: {e}")

    async def start(self):
        """Запуск индикатора"""
        if self.is_running:
            logger.warning("⚠️ MACD 5m индикатор уже запущен")
            return

        logger.info(f"🚀 Запуск MACD 5m индикатора: {self.symbol}")

        try:
            # Загружаем историю
            self.get_historical_data()

            # Запускаем WebSocket
            self.start_websocket()

            self.is_running = True
            logger.info("✅ MACD 5m индикатор запущен")

        except Exception as e:
            logger.error(f"❌ Ошибка запуска MACD 5m индикатора: {e}")
            await self.stop()
            raise

    async def stop(self):
        """Остановка индикатора"""
        if not self.is_running:
            return

        logger.info("⏹️ Остановка MACD 5m индикатора...")

        try:
            # Останавливаем WebSocket
            self.stop_websocket()

            # Сбрасываем состояние
            self.last_macd_line = None
            self.last_signal_line = None

            self.is_running = False
            logger.info(f"✅ MACD 5m индикатор остановлен (обработано {self.total_updates} обновлений)")

        except Exception as e:
            logger.error(f"❌ Ошибка остановки MACD 5m индикатора: {e}")

    def get_current_macd_values(self) -> Optional[Dict[str, Any]]:
        """Получение текущих значений MACD"""
        if not self.macd_data:
            return None

        return self.macd_data[-1]

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса индикатора"""
        return {
            'symbol': self.symbol,
            'timeframe': '5m',
            'is_running': self.is_running,
            'klines_count': len(self.klines_data),
            'callbacks_count': len(self.callbacks),
            'total_updates': self.total_updates,
            'has_macd_data': len(self.macd_data) > 0
        }
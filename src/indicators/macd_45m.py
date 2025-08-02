# src/indicators/macd_45m.py
import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable, Union, Awaitable
from binance.client import Client
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from ..utils.logger import logger


class MACD45mIndicator:
    """
    MACD индикатор для 45-минутного таймфрейма
    Строит 45m свечи из 15m данных по правильной временной сетке
    """

    def __init__(self, symbol: str, limit: int = 200):
        self.symbol = symbol.upper()
        self.limit = limit
        self.klines_45m: List[float] = []
        self.macd_data: List[Dict[str, Any]] = []
        self.ws_client: Optional[UMFuturesWebsocketClient] = None
        self.current_45m_start: Optional[datetime] = None
        self.last_45m_start: Optional[datetime] = None
        self.current_45m_candle: Optional[Dict[str, Any]] = None

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

        # Для периодического отображения MACD (раз в 60 секунд)
        self.last_macd_display_time = None
        self.macd_display_interval = 60  # Показывать MACD раз в 60 секунд

    def add_callback(self, callback: Union[
        Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]):
        """Добавить callback для сигналов"""
        self.callbacks.append(callback)

    def get_45m_interval_start(self, timestamp: datetime) -> datetime:
        """Получить начало 45м интервала для заданного времени"""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        day_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        minutes_from_start = (timestamp - day_start).total_seconds() / 60
        interval_number = int(minutes_from_start // 45)
        interval_start = day_start + timedelta(minutes=interval_number * 45)

        return interval_start

    def get_historical_data(self):
        """Получение максимально свежих исторических данных"""
        try:
            client = Client()

            logger.info(f"📈 Загружаем историю {self.symbol} для 45m MACD")

            # Получаем серверное время Binance
            server_time = client.get_server_time()
            now = pd.to_datetime(server_time['serverTime'], unit='ms', utc=True)
            logger.info(f"[SYNC] Серверное время Binance: {now}")

            self.current_45m_start = self.get_45m_interval_start(now)
            self.last_45m_start = self.current_45m_start

            # Запрашиваем исторические 15м свечи
            klines_15m = client.futures_klines(
                symbol=self.symbol,
                interval='15m',
                limit=self.limit * 3 + 10
            )

            df = pd.DataFrame(klines_15m, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
                'taker_buy_quote_volume', 'ignore'
            ])

            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)

            # Преобразуем в 45м свечи
            self.convert_15m_to_45m(df)

            # Показываем анализ интервалов
            self.show_interval_analysis(now)

            # Доформировываем текущий интервал
            self.complete_current_interval(client, now)

            logger.info("=" * 60)
            logger.info(f"ЗАГРУЖЕНО: {len(self.klines_45m)} исторических 45м свечей")
            logger.info("=" * 60)

            # Рассчитываем начальный MACD
            self.calculate_macd()

        except Exception as e:
            logger.error(f"❌ Ошибка получения исторических данных: {e}")
            raise

    def show_interval_analysis(self, now: datetime):
        """Показать анализ интервалов"""
        last_complete_interval = self.current_45m_start - timedelta(minutes=45)
        time_in_interval = (now - self.current_45m_start).total_seconds() / 60

        logger.info("=" * 60)
        logger.info("АНАЛИЗ ИНТЕРВАЛОВ:")
        logger.info(f"Текущее UTC время: {now.strftime('%H:%M:%S')}")
        logger.info(
            f"Последний полный 45м интервал: {last_complete_interval.strftime('%H:%M')} - "
            f"{(last_complete_interval + timedelta(minutes=45)).strftime('%H:%M')}"
        )
        logger.info(
            f"Текущий интервал: {self.current_45m_start.strftime('%H:%M')} - "
            f"{(self.current_45m_start + timedelta(minutes=45)).strftime('%H:%M')}"
        )
        logger.info(f"Прошло времени в текущем интервале: {time_in_interval:.1f} минут")

        # Проверяем правильность сетки - показываем несколько интервалов
        logger.info(f"ПРОВЕРКА СЕТКИ 45М:")
        for i in range(-2, 3):
            test_interval = self.current_45m_start + timedelta(minutes=i * 45)
            logger.info(
                f"  Интервал {i}: {test_interval.strftime('%H:%M')} - "
                f"{(test_interval + timedelta(minutes=45)).strftime('%H:%M')}"
            )

        logger.info("=" * 60)

    def convert_15m_to_45m(self, df_15m: pd.DataFrame):
        """Преобразование 15м в 45м"""
        self.klines_45m = []
        grouped_candles = {}

        for _, row in df_15m.iterrows():
            interval_start = self.get_45m_interval_start(row['timestamp'])

            if interval_start not in grouped_candles:
                grouped_candles[interval_start] = []

            grouped_candles[interval_start].append(row)

        # Формируем только полные исторические 45м свечи (исключаем текущий интервал)
        for interval_start in sorted(grouped_candles.keys()):
            candles = grouped_candles[interval_start]

            # Пропускаем текущий интервал - он будет доформирован отдельно
            if interval_start >= self.current_45m_start:
                continue

            # Пропускаем неполные интервалы
            if len(candles) < 3:
                continue

            candle_45m = {
                'timestamp': interval_start,
                'open': candles[0]['open'],
                'high': max(c['high'] for c in candles),
                'low': min(c['low'] for c in candles),
                'close': candles[-1]['close'],
                'volume': sum(c['volume'] for c in candles)
            }

            self.klines_45m.append(candle_45m['close'])

    def complete_current_interval(self, client: Client, now: datetime):
        """Доформирование текущего 45м интервала"""
        try:
            time_in_interval = (now - self.current_45m_start).total_seconds() / 60
            completed_5m_candles = int(time_in_interval // 5)

            logger.info(f"DEBUG: Текущее время в интервале: {time_in_interval:.1f} минут")
            logger.info(f"DEBUG: Завершённых 5м свечей должно быть: {completed_5m_candles}")

            if completed_5m_candles == 0:
                logger.info("Дополнительные 5м свечи: 0 (первая 5м свеча ещё не завершена)")
                # Добавляем пустую цену для текущего интервала
                self.current_45m_candle = {'close': 0.0, 'high': 0.0, 'low': 999999.0, 'open': 0.0, 'volume': 0.0}
                self.klines_45m.append(0.0)
                return

            # Запрашиваем завершённые 5м свечи
            start_time = int(self.current_45m_start.timestamp() * 1000)

            klines_5m = client.futures_klines(
                symbol=self.symbol,
                interval='5m',
                startTime=start_time,
                limit=completed_5m_candles
            )

            logger.info(f"DEBUG: Binance вернул {len(klines_5m)} свечей (запрашивали {completed_5m_candles})")

            if klines_5m:
                # Берём только нужное количество свечей
                klines_to_use = klines_5m[:completed_5m_candles]

                self.current_45m_candle = {
                    'open': float(klines_to_use[0][1]),
                    'high': max(float(k[2]) for k in klines_to_use),
                    'low': min(float(k[3]) for k in klines_to_use),
                    'close': float(klines_to_use[-1][4]),
                    'volume': sum(float(k[5]) for k in klines_to_use)
                }

                self.klines_45m.append(self.current_45m_candle['close'])

                last_completed_time = self.current_45m_start + timedelta(minutes=completed_5m_candles * 5)
                logger.info(f"Дополнительные 5м свечи: {len(klines_to_use)} шт (только завершённые)")
                logger.info(
                    f"Период завершённых данных: {self.current_45m_start.strftime('%H:%M')} - "
                    f"{last_completed_time.strftime('%H:%M')}"
                )
            else:
                logger.info("Дополнительные 5м свечи: 0 (не найдены)")
                self.current_45m_candle = {'close': 0.0, 'high': 0.0, 'low': 999999.0, 'open': 0.0, 'volume': 0.0}
                self.klines_45m.append(0.0)

        except Exception as e:
            logger.error(f"❌ Ошибка доформирования интервала: {e}")

    def update_current_45m_candle(self, price: float, high: float, low: float, volume: float):
        """Обновление текущей 45м свечи"""
        if self.current_45m_candle is None:
            self.current_45m_candle = {
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': volume
            }
        else:
            if self.current_45m_candle['open'] == 0.0:
                self.current_45m_candle['open'] = price

            self.current_45m_candle['high'] = max(self.current_45m_candle['high'], high)
            self.current_45m_candle['low'] = min(self.current_45m_candle['low'], low) if self.current_45m_candle[
                                                                                             'low'] != 999999.0 else low
            self.current_45m_candle['close'] = price
            self.current_45m_candle['volume'] += volume

    def check_45m_interval_change(self, timestamp: datetime) -> bool:
        """Проверка смены 45м интервала"""
        current_interval = self.get_45m_interval_start(timestamp)

        if current_interval != self.last_45m_start:
            # Новый 45м интервал начался!
            logger.info(
                f"[НОВЫЙ 45М ИНТЕРВАЛ] {self.last_45m_start.strftime('%H:%M')} -> "
                f"{current_interval.strftime('%H:%M')}"
            )

            # Фиксируем предыдущую 45м свечу
            if self.current_45m_candle and self.current_45m_candle['close'] != 0.0:
                logger.info(f"[ФИКСАЦИЯ 45М] Close: {self.current_45m_candle['close']}")

            # Начинаем новую 45м свечу
            self.last_45m_start = current_interval
            self.current_45m_start = current_interval
            self.current_45m_candle = None

            # Добавляем новую пустую свечу для нового интервала
            self.klines_45m.append(0.0)

            # Ограничиваем размер массива
            if len(self.klines_45m) > self.limit + 50:
                self.klines_45m = self.klines_45m[-self.limit:]
                logger.info(f"[ОБРЕЗКА] Массив обрезан до {len(self.klines_45m)} свечей")

            return True
        return False

    @staticmethod
    def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        """Расчет EMA с максимальной точностью"""
        prices = np.array(prices, dtype=np.float64)

        if len(prices) < period:
            return np.full_like(prices, np.nan, dtype=np.float64)

        ema = np.full_like(prices, np.nan, dtype=np.float64)
        alpha = np.float64(2.0) / np.float64(period + 1.0)

        first_valid = period - 1
        for i in range(len(prices)):
            if not np.isnan(prices[i]) and prices[i] != 0:
                first_valid = max(i, period - 1)
                break

        if first_valid >= len(prices):
            return ema

        if first_valid + period <= len(prices):
            valid_window = prices[first_valid - period + 1:first_valid + 1]
            if not np.any(np.isnan(valid_window)) and not np.any(valid_window == 0):
                ema[first_valid] = np.mean(valid_window, dtype=np.float64)
            elif first_valid < len(prices):
                ema[first_valid] = prices[first_valid]

        for i in range(first_valid + 1, len(prices)):
            if not np.isnan(prices[i]) and prices[i] != 0 and not np.isnan(ema[i - 1]):
                ema[i] = alpha * prices[i] + (np.float64(1.0) - alpha) * ema[i - 1]

        return ema

    def calculate_macd(self) -> Optional[Dict[str, Any]]:
        """Расчет MACD с максимальной точностью"""
        if len(self.klines_45m) < 32:
            return None

        prices = np.array(self.klines_45m, dtype=np.float64)

        ema12 = self.calculate_ema(prices, 12)
        ema26 = self.calculate_ema(prices, 26)

        macd_line = np.full_like(prices, np.nan, dtype=np.float64)

        for i in range(len(prices)):
            if not np.isnan(ema12[i]) and not np.isnan(ema26[i]):
                macd_line[i] = ema12[i] - ema26[i]

        first_macd_idx = None
        for i in range(len(macd_line)):
            if not np.isnan(macd_line[i]):
                first_macd_idx = i
                break

        if first_macd_idx is None or len(macd_line) - first_macd_idx < 7:
            return None

        valid_macd = macd_line[first_macd_idx:]
        signal_ema = self.calculate_ema(valid_macd, 7)

        signal_line = np.full_like(prices, np.nan, dtype=np.float64)
        signal_line[first_macd_idx:] = signal_ema

        current_price = float(prices[-1])
        current_macd = float(macd_line[-1]) if not np.isnan(macd_line[-1]) else 0.0
        current_signal = float(signal_line[-1]) if not np.isnan(signal_line[-1]) else 0.0
        current_histogram = current_macd - current_signal

        if np.isnan(current_macd) or np.isnan(current_signal):
            return None

        # Сохраняем без округления с еще большей точностью
        macd_data = {
            'timestamp': datetime.now(),
            'price': current_price,
            'macd_line': current_macd,
            'signal_line': current_signal,
            'histogram': current_histogram,
            'timeframe': '45m'
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
            # Округляем только для отображения с точностью TradingView
            display_price = round(current_price, 2)
            display_macd = round(current_macd, 2)
            display_signal = round(current_signal, 2)
            display_histogram = round(current_histogram, 2)

            # КРИТИЧНАЯ ОТЛАДКА - показываем последние 5 цен 45м свечей только при отображении
            logger.info(
                f"[КРИТИЧ] Последние 5 цен 45м: {self.klines_45m[-5:] if len(self.klines_45m) >= 5 else self.klines_45m}")

            logger.info(
                f"📊 MACD 45m: Цена: {display_price} | "
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
                'timeframe': '45m',
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
                'timeframe': '45m',
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
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ MACD 45m! {signal['crossover_type'].upper()} сигнал {signal['type'].upper()}")

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
        """Обработка WebSocket сообщений с 5м данными"""
        try:
            data = json.loads(message)

            if 'k' in data:
                kline = data['k']
                close_price = float(kline['c'])
                high_price = float(kline['h'])
                low_price = float(kline['l'])
                volume = float(kline['v'])
                kline_start_time = pd.to_datetime(int(kline['t']), unit='ms', utc=True)
                is_kline_closed = kline['x']

                # Проверяем смену 45м интервала
                interval_changed = self.check_45m_interval_change(kline_start_time)

                # Обновляем текущую 45м свечу
                self.update_current_45m_candle(close_price, high_price, low_price, volume)

                # Обновляем последнюю цену в массиве
                if len(self.klines_45m) > 0:
                    self.klines_45m[-1] = close_price

                if is_kline_closed:
                    logger.info(f"[5М СВЕЧА ЗАКРЫТА] {kline_start_time.strftime('%H:%M')} | Цена: {close_price}")

                self.total_updates += 1

                # Пересчитываем MACD
                self.calculate_macd()

        except Exception as e:
            logger.error(f"❌ Ошибка WebSocket: {e}")

    def start_websocket(self):
        """Запуск WebSocket"""
        try:
            self.ws_client = UMFuturesWebsocketClient(
                on_message=self.handle_kline_message
            )

            self.ws_client.kline(
                symbol=self.symbol.lower(),
                interval='5m'
            )

            logger.info(f"🚀 WebSocket подключен для {self.symbol} 5m (для 45m агрегации)")

        except Exception as e:
            logger.error(f"❌ Ошибка WebSocket подключения: {e}")
            raise

    def stop_websocket(self):
        """Остановка WebSocket"""
        if self.ws_client:
            try:
                self.ws_client.stop()
                logger.info("⏹️ WebSocket 45m соединение закрыто")
            except Exception as e:
                logger.error(f"❌ Ошибка закрытия WebSocket: {e}")

    async def start(self):
        """Запуск индикатора"""
        if self.is_running:
            logger.warning("⚠️ MACD 45m индикатор уже запущен")
            return

        logger.info(f"🚀 Запуск MACD 45m индикатора: {self.symbol}")
        logger.info("История: 15m свечи -> 45m таймфрейм")
        logger.info("Live обновления: 5m свечи с агрегацией в 45m")

        try:
            # Загружаем историю
            self.get_historical_data()

            # Запускаем WebSocket
            self.start_websocket()

            self.is_running = True
            logger.info("✅ MACD 45m индикатор запущен")

        except Exception as e:
            logger.error(f"❌ Ошибка запуска MACD 45m индикатора: {e}")
            await self.stop()
            raise

    async def stop(self):
        """Остановка индикатора"""
        if not self.is_running:
            return

        logger.info("⏹️ Остановка MACD 45m индикатора...")

        try:
            # Останавливаем WebSocket
            self.stop_websocket()

            # Сбрасываем состояние
            self.last_macd_line = None
            self.last_signal_line = None

            self.is_running = False
            logger.info(f"✅ MACD 45m индикатор остановлен (обработано {self.total_updates} обновлений)")

        except Exception as e:
            logger.error(f"❌ Ошибка остановки MACD 45m индикатора: {e}")

    def get_current_macd_values(self) -> Optional[Dict[str, Any]]:
        """Получение текущих значений MACD"""
        if not self.macd_data:
            return None

        return self.macd_data[-1]

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса индикатора"""
        return {
            'symbol': self.symbol,
            'timeframe': '45m',
            'is_running': self.is_running,
            'klines_count': len(self.klines_45m),
            'callbacks_count': len(self.callbacks),
            'total_updates': self.total_updates,
            'has_macd_data': len(self.macd_data) > 0,
            'current_45m_start': self.current_45m_start.isoformat() if self.current_45m_start else None
        }
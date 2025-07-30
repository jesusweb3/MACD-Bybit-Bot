# src/indicators/macd.py
import pandas as pd
import asyncio
from typing import Dict, Any, List, Optional, Callable, Union, Awaitable
from datetime import datetime, timezone, timedelta
from ..exchange.binance import BinanceClient
from ..utils.logger import logger


class MACDIndicator:
    """
    MACD индикатор с правильной логикой построения 45m свечей

    Поддерживаемые таймфреймы: 5m, 45m
    45m свечи строятся по правильной временной сетке:
    00:00, 00:45, 01:30, 02:15, 03:00, 03:45, 04:30, 05:15, 06:00, 06:45, 07:30, 08:15, 09:00...
    """

    def __init__(self, symbol: str, timeframe: str,
                 fast_period: int = 12, slow_period: int = 26, signal_period: int = 9,
                 min_history: int = 100):
        """
        Args:
            symbol: Торговая пара (BTCUSDT)
            timeframe: Таймфрейм (5m, 45m)
            fast_period: Период быстрой EMA (по умолчанию 12)
            slow_period: Период медленной EMA (по умолчанию 26)
            signal_period: Период сигнальной линии (по умолчанию 9)
            min_history: Минимальное количество свечей для расчета
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.min_history = min_history

        # Клиент для получения данных
        self.binance_client = BinanceClient()

        # История свечей
        self.klines: List[Dict[str, Any]] = []
        self.df: Optional[pd.DataFrame] = None

        # Callback функции для сигналов
        self.callbacks: List[
            Union[Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]] = []

        # Флаги состояния
        self.is_running = False
        self.stream_active = False

        # Для 45m таймфрейма - состояние построения кастомных свечей
        self.is_custom_timeframe = timeframe == '45m'
        if self.is_custom_timeframe:
            self.accumulated_15m_klines: List[Dict[str, Any]] = []
            self.current_45m_start_time: Optional[int] = None
            self.next_45m_end_time: Optional[int] = None

        logger.info(f"MACD инициализирован для {symbol} на {timeframe}")
        if self.is_custom_timeframe:
            logger.info("Режим: Кастомный 45m таймфрейм с правильной временной сеткой")
        logger.info(f"Параметры MACD: {fast_period}, {slow_period}, {signal_period}")

    def add_callback(self, callback: Union[
        Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]):
        """Добавить callback для сигналов"""
        self.callbacks.append(callback)

    @staticmethod
    def _get_45m_grid_start_time(timestamp_ms: int) -> int:
        """
        Получить время начала 45m свечи для данного timestamp по правильной сетке

        45m сетка: 00:00, 00:45, 01:30, 02:15, 03:00, 03:45, 04:30, 05:15, 06:00...
        """
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

        # Получаем начало дня
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)

        # Количество минут с начала дня
        minutes_from_day_start = (dt - day_start).total_seconds() / 60

        # Находим к какому 45m интервалу относится это время
        interval_index = int(minutes_from_day_start // 45)

        # Вычисляем время начала этого 45m интервала
        interval_start_minutes = interval_index * 45
        interval_start_time = day_start + timedelta(minutes=interval_start_minutes)

        return int(interval_start_time.timestamp() * 1000)

    @staticmethod
    def _get_next_45m_end_time(current_start_time_ms: int) -> int:
        """Получить время окончания текущей 45m свечи"""
        return current_start_time_ms + (45 * 60 * 1000)  # +45 минут в миллисекундах

    def _log_45m_timing_info(self):
        """Логирование информации о времени ТЕКУЩЕЙ 45m свечи"""
        if not self.is_custom_timeframe or not self.next_45m_end_time:
            return

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        time_left_ms = self.next_45m_end_time - now_ms

        if time_left_ms > 0:
            time_left_minutes = time_left_ms / (1000 * 60)

            # Время начала и конца ТЕКУЩЕЙ свечи
            start_time = datetime.fromtimestamp(self.current_45m_start_time / 1000, tz=timezone.utc)
            end_time = datetime.fromtimestamp(self.next_45m_end_time / 1000, tz=timezone.utc)

            logger.info(f"⏰ Текущая 45m свеча: {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} UTC")
            logger.info(f"⏰ До завершения: {time_left_minutes:.1f} мин")
        else:
            logger.info("⏰ 45m свеча должна была завершиться - ожидаем новые данные")

    @staticmethod
    def calculate_ema(data: pd.Series, period: int) -> pd.Series:
        """Расчет экспоненциальной скользящей средней"""
        return data.ewm(span=period, adjust=False).mean()

    def calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """Расчет MACD индикатора"""
        if len(df) < self.slow_period:
            return pd.DataFrame()

        result_df = df.copy()

        # Рассчитываем EMA
        fast_ema = self.calculate_ema(df['close'], self.fast_period)
        slow_ema = self.calculate_ema(df['close'], self.slow_period)

        # MACD линия = быстрая EMA - медленная EMA
        result_df['macd_line'] = fast_ema - slow_ema

        # Сигнальная линия = EMA от MACD линии
        result_df['signal_line'] = self.calculate_ema(result_df['macd_line'], self.signal_period)

        # Гистограмма = MACD линия - сигнальная линия
        result_df['histogram'] = result_df['macd_line'] - result_df['signal_line']

        return result_df

    def detect_macd_signals(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """Определение сигналов MACD - ТОЛЬКО при пересечении линий"""
        if len(df) < 2:
            return None

        # Берем последние две строки для определения пересечения
        current = df.iloc[-1]
        previous = df.iloc[-2]

        signal = None

        # ПЕРЕСЕЧЕНИЕ СНИЗУ ВВЕРХ: бычий сигнал
        if (previous['macd_line'] < previous['signal_line'] and
                current['macd_line'] > current['signal_line']):

            signal = {
                'type': 'buy',
                'timeframe': self.timeframe,
                'timestamp': current['timestamp'],
                'price': current['close'],
                'macd_line': current['macd_line'],
                'signal_line': current['signal_line'],
                'histogram': current['histogram'],
                'crossover_type': 'bullish'
            }

        # ПЕРЕСЕЧЕНИЕ СВЕРХУ ВНИЗ: медвежий сигнал
        elif (previous['macd_line'] > previous['signal_line'] and
              current['macd_line'] < current['signal_line']):

            signal = {
                'type': 'sell',
                'timeframe': self.timeframe,
                'timestamp': current['timestamp'],
                'price': current['close'],
                'macd_line': current['macd_line'],
                'signal_line': current['signal_line'],
                'histogram': current['histogram'],
                'crossover_type': 'bearish'
            }

        return signal

    @staticmethod
    def klines_to_dataframe(klines: List[Dict[str, Any]]) -> pd.DataFrame:
        """Конвертация списка свечей в DataFrame"""
        if not klines:
            return pd.DataFrame()

        df = pd.DataFrame(klines)
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df = df.sort_values('timestamp').reset_index(drop=True)

        return df

    @staticmethod
    def _merge_15m_to_45m(klines_15m: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Объединение трех 15m свечей в одну 45m свечу"""
        if len(klines_15m) != 3:
            raise ValueError("Для создания 45m свечи нужно ровно 3 свечи по 15m")

        # Сортируем по времени
        klines_15m.sort(key=lambda x: x['timestamp'])

        merged = {
            'timestamp': klines_15m[0]['timestamp'],
            'open': klines_15m[0]['open'],
            'high': max(k['high'] for k in klines_15m),
            'low': min(k['low'] for k in klines_15m),
            'close': klines_15m[-1]['close'],
            'volume': sum(k['volume'] for k in klines_15m),
            'close_time': klines_15m[-1]['close_time'],
            'quote_volume': sum(k.get('quote_volume', 0) for k in klines_15m),
            'trades_count': sum(k.get('trades_count', 0) for k in klines_15m)
        }

        return merged

    def _build_45m_history_from_15m(self, base_klines_15m: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Построение исторических 45m свечей из 15m по правильной временной сетке
        """
        if not base_klines_15m:
            return []

        # Сортируем по времени
        base_klines_15m.sort(key=lambda x: x['timestamp'])

        logger.info(f"Строим 45m историю из {len(base_klines_15m)} базовых 15m свечей")

        custom_45m_klines = []

        # Группируем 15m свечи по 45m интервалам согласно временной сетке
        grouped_klines = {}

        for kline_15m in base_klines_15m:
            # Определяем к какому 45m интервалу относится эта 15m свеча
            interval_start = self._get_45m_grid_start_time(kline_15m['timestamp'])

            if interval_start not in grouped_klines:
                grouped_klines[interval_start] = []

            grouped_klines[interval_start].append(kline_15m)

        # Создаем 45m свечи только из полных групп (3 свечи по 15m)
        for interval_start in sorted(grouped_klines.keys()):
            klines_group = grouped_klines[interval_start]

            if len(klines_group) == 3:
                # Проверяем что свечи идут подряд по времени (каждая следующая через 15 минут)
                klines_group.sort(key=lambda x: x['timestamp'])
                is_continuous = True

                for i in range(1, len(klines_group)):
                    expected_time = klines_group[i - 1]['timestamp'] + (15 * 60 * 1000)
                    if abs(klines_group[i]['timestamp'] - expected_time) > (2 * 60 * 1000):  # допуск 2 минуты
                        is_continuous = False
                        break

                if is_continuous:
                    merged_45m = self._merge_15m_to_45m(klines_group)
                    custom_45m_klines.append(merged_45m)

                    # Логируем создание свечи
                    start_time = datetime.fromtimestamp(merged_45m['timestamp'] / 1000, tz=timezone.utc)
                    logger.debug(f"Создана 45m свеча: {start_time.strftime('%Y-%m-%d %H:%M')} UTC")
                else:
                    logger.debug(f"Пропущена неполная группа 45m (свечи не непрерывны)")
            else:
                logger.debug(f"Пропущена неполная группа 45m ({len(klines_group)}/3 свечей)")

        logger.info(f"Создано {len(custom_45m_klines)} полных 45m свечей из исторических данных")
        return custom_45m_klines

    async def load_historical_data(self):
        """Загрузка исторических данных"""
        logger.info(f"Загружаем историю для {self.symbol} на {self.timeframe}")

        if self.is_custom_timeframe:
            # Для 45m загружаем 15m свечи и строим кастомные по правильной сетке
            base_limit = self.min_history * 3 + 50  # Запас для построения правильной сетки
            logger.info(f"Загружаем {base_limit} базовых 15m свечей для построения 45m")

            base_klines = await self.binance_client.get_klines(self.symbol, '15m', base_limit)
            if not base_klines:
                raise Exception("Не удалось загрузить базовые данные для 15m")

            self.klines = self._build_45m_history_from_15m(base_klines)

            if len(self.klines) < self.min_history:
                logger.warning(f"Получено {len(self.klines)} 45m свечей, меньше требуемых {self.min_history}")

            # Инициализируем состояние для ТЕКУЩЕЙ 45m свечи (не следующей!)
            if self.klines:
                # Определяем время начала ТЕКУЩЕЙ активной 45m свечи
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                self.current_45m_start_time = self._get_45m_grid_start_time(now_ms)
                self.next_45m_end_time = self._get_next_45m_end_time(self.current_45m_start_time)

                # Логируем информацию о текущей свече
                self._log_45m_timing_info()

        else:
            # Для 5m загружаем напрямую
            logger.info(f"Загружаем {self.min_history} свечей для {self.timeframe}")
            self.klines = await self.binance_client.get_klines(
                self.symbol, self.timeframe, self.min_history
            )

        if not self.klines:
            raise Exception(f"Не удалось загрузить данные для {self.timeframe}")

        # Конвертируем в DataFrame и рассчитываем MACD
        self.df = self.klines_to_dataframe(self.klines)
        self.df = self.calculate_macd(self.df)

        logger.info(f"✅ История загружена: {len(self.df)} свечей {self.timeframe}")

    async def kline_callback(self, kline: Dict[str, Any]):
        """Callback для новых свечей"""
        try:
            if self.is_custom_timeframe:
                await self._process_45m_kline(kline)
            else:
                await self._process_standard_kline(kline)
        except Exception as e:
            logger.error(f"Ошибка в kline_callback: {e}")

    async def _process_standard_kline(self, kline: Dict[str, Any]):
        """Обработка обычной свечи (5m)"""
        # Добавляем новую свечу
        self.klines.append(kline)
        self.df = self.klines_to_dataframe(self.klines[-self.min_history:])
        self.df = self.calculate_macd(self.df)

        signal = self.detect_macd_signals(self.df)

        if signal:
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ! Сигнал: {signal['type']} на {self.timeframe}")
            logger.info(f"   Тип пересечения: {signal['crossover_type']}")
            logger.info(
                f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

            # Вызываем callback'и
            for callback in self.callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal)
                    else:
                        callback(signal)
                except Exception as e:
                    logger.error(f"Ошибка в callback: {e}")

    async def _process_45m_kline(self, base_kline_15m: Dict[str, Any]):
        """Обработка 45m кастомной свечи из 15m базовой"""
        # Логируем получение 15m свечи
        kline_time = datetime.fromtimestamp(base_kline_15m['timestamp'] / 1000, tz=timezone.utc)
        logger.debug(f"Получена 15m свеча: {kline_time.strftime('%H:%M:%S')} UTC")

        # Определяем к какому 45m интервалу относится эта 15m свеча
        kline_45m_start = self._get_45m_grid_start_time(base_kline_15m['timestamp'])

        # Если это свеча для нового 45m интервала
        if self.current_45m_start_time is None or kline_45m_start != self.current_45m_start_time:
            # Завершаем предыдущий интервал если он был
            if self.accumulated_15m_klines and len(self.accumulated_15m_klines) == 3:
                await self._complete_45m_kline()

            # Начинаем новый 45m интервал
            self.current_45m_start_time = kline_45m_start
            self.next_45m_end_time = self._get_next_45m_end_time(kline_45m_start)
            self.accumulated_15m_klines = []

            logger.info(f"🆕 Начат новый 45m интервал")
            self._log_45m_timing_info()

        # Добавляем 15m свечу к текущему 45m интервалу
        self.accumulated_15m_klines.append(base_kline_15m)
        logger.debug(f"Накоплено {len(self.accumulated_15m_klines)}/3 свечей для 45m")

        # Если накопили 3 свечи - завершаем 45m свечу
        if len(self.accumulated_15m_klines) == 3:
            await self._complete_45m_kline()

    async def _complete_45m_kline(self):
        """Завершение и обработка 45m свечи"""
        if len(self.accumulated_15m_klines) != 3:
            logger.warning(f"Попытка завершить 45m свечу с {len(self.accumulated_15m_klines)} из 3 свечей")
            return

        # Создаем 45m свечу
        custom_45m_kline = self._merge_15m_to_45m(self.accumulated_15m_klines)

        # Логируем завершение свечи
        start_time = datetime.fromtimestamp(custom_45m_kline['timestamp'] / 1000, tz=timezone.utc)
        end_time = datetime.fromtimestamp(custom_45m_kline['close_time'] / 1000, tz=timezone.utc)
        logger.info(
            f"✅ Завершена 45m свеча: {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} UTC, цена: {custom_45m_kline['close']}")

        # Обновляем время для следующей свечи
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        self.current_45m_start_time = self._get_45m_grid_start_time(now_ms)
        self.next_45m_end_time = self._get_next_45m_end_time(self.current_45m_start_time)

        # Добавляем к истории
        self.klines.append(custom_45m_kline)
        self.df = self.klines_to_dataframe(self.klines[-self.min_history:])
        self.df = self.calculate_macd(self.df)

        # Проверяем сигналы
        signal = self.detect_macd_signals(self.df)

        if signal:
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ! Сигнал: {signal['type']} на 45m")
            logger.info(f"   Тип пересечения: {signal['crossover_type']}")
            logger.info(
                f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

            # Вызываем callback'и
            for callback in self.callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal)
                    else:
                        callback(signal)
                except Exception as e:
                    logger.error(f"Ошибка в callback: {e}")

        # Очищаем накопленные свечи
        self.accumulated_15m_klines = []

    async def start(self):
        """Запуск индикатора"""
        if self.is_running:
            logger.warning("MACD индикатор уже запущен")
            return

        logger.info(f"🚀 Запускаем MACD индикатор для {self.symbol} на {self.timeframe}")

        try:
            # Загружаем историю
            await self.load_historical_data()

            # Запускаем WebSocket поток
            logger.info("🔄 Запускаем WebSocket поток...")

            # Синхронная обертка для async callback
            def callback_wrapper(kline: Dict[str, Any]) -> None:
                asyncio.create_task(self.kline_callback(kline))

            # Определяем базовый таймфрейм для подписки
            base_timeframe = '15m' if self.is_custom_timeframe else self.timeframe

            # Запускаем поток
            await self.binance_client.start_kline_stream(self.symbol, base_timeframe, callback_wrapper)
            self.stream_active = True
            self.is_running = True

            logger.info("✅ MACD индикатор запущен и готов к работе")

            # Логируем информацию о 45m если нужно
            if self.is_custom_timeframe:
                logger.info("📊 MACD индикатор готов к работе с 45m таймфреймом")
                self._log_45m_timing_info()

        except Exception as e:
            logger.error(f"❌ Ошибка запуска MACD индикатора: {e}")
            await self.stop()
            raise

    async def stop(self):
        """Остановка индикатора"""
        if not self.is_running:
            return

        logger.info("⏹️ Останавливаем MACD индикатор...")

        try:
            # Определяем базовый таймфрейм
            base_timeframe = '15m' if self.is_custom_timeframe else self.timeframe

            if self.stream_active:
                await self.binance_client.stop_kline_stream(self.symbol, base_timeframe)
                self.stream_active = False

            # Очищаем состояние 45m
            if self.is_custom_timeframe:
                self.accumulated_15m_klines = []
                self.current_45m_start_time = None
                self.next_45m_end_time = None

            self.is_running = False
            logger.info("✅ MACD индикатор остановлен")

        except Exception as e:
            logger.error(f"Ошибка остановки MACD индикатора: {e}")

    async def close(self):
        """Закрытие индикатора и освобождение ресурсов"""
        await self.stop()
        await self.binance_client.close()
        logger.info("🔒 MACD индикатор закрыт")

    def get_current_macd_values(self) -> Optional[Dict[str, Any]]:
        """Получение текущих значений MACD"""
        if self.df is None or len(self.df) == 0:
            return None

        current = self.df.iloc[-1]

        result = {
            'timestamp': current['timestamp'],
            'price': current['close'],
            'macd_line': current['macd_line'],
            'signal_line': current['signal_line'],
            'histogram': current['histogram'],
            'timeframe': self.timeframe
        }

        # Добавляем информацию о 45m если нужно
        if self.is_custom_timeframe and self.next_45m_end_time:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            time_left_ms = self.next_45m_end_time - now_ms
            result['time_to_next_45m_ms'] = max(0, time_left_ms)

        return result

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса индикатора"""
        status = {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'is_custom_timeframe': self.is_custom_timeframe,
            'is_running': self.is_running,
            'stream_active': self.stream_active,
            'data_length': len(self.df) if self.df is not None else 0,
            'callbacks_count': len(self.callbacks)
        }

        # Добавляем состояние 45m если есть
        if self.is_custom_timeframe:
            status['accumulated_15m_count'] = len(self.accumulated_15m_klines)
            if self.next_45m_end_time:
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                time_left_ms = self.next_45m_end_time - now_ms
                status['time_to_next_45m_minutes'] = max(0, time_left_ms / (1000 * 60))

        return status
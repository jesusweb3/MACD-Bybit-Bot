# src/indicators/macd.py
import pandas as pd
import asyncio
from typing import Dict, Any, List, Optional, Callable, Union, Awaitable
from datetime import datetime, timezone, timedelta
from ..exchange.binance import BinanceClient
from ..utils.logger import logger


class MACDIndicator:
    """
    MACD индикатор с агрессивной real-time логикой

    Поддерживаемые таймфреймы: 5m, 45m
    Обновления: каждую минуту с пересчетом MACD и проверкой сигналов
    """

    def __init__(self, symbol: str, timeframe: str,
                 fast_period: int = 12, slow_period: int = 26, signal_period: int = 7,
                 min_history: int = 7500):
        """
        Args:
            symbol: Торговая пара (BTCUSDT)
            timeframe: Целевой таймфрейм для MACD (5m, 45m)
            fast_period: Период быстрой EMA (по умолчанию 12)
            slow_period: Период медленной EMA (по умолчанию 26)
            signal_period: Период сигнальной линии (по умолчанию 7)
            min_history: Минимальное количество свечей для расчета
        """
        self.symbol = symbol
        self.timeframe = timeframe  # Целевой таймфрейм (5m или 45m)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.min_history = min_history

        # Клиент для получения данных (всегда минутные)
        self.binance_client = BinanceClient()

        # История целевых свечей (5m или 45m)
        self.target_klines: List[Dict[str, Any]] = []
        self.df: Optional[pd.DataFrame] = None

        # Текущая формируемая свеча целевого таймфрейма
        self.current_target_candle: Optional[Dict[str, Any]] = None
        self.current_target_start_time: Optional[int] = None

        # Callback функции для сигналов
        self.callbacks: List[
            Union[Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]] = []

        # Флаги состояния
        self.is_running = False
        self.stream_active = False

        # Последние значения MACD для отслеживания пересечений
        self.last_macd_line: Optional[float] = None
        self.last_signal_line: Optional[float] = None

        # Счетчики для статистики
        self.total_candles_processed = 0

        logger.info(
            f"🔧 MACD индикатор инициализирован: {symbol} {timeframe} (EMA: {fast_period}/{slow_period}, Signal: {signal_period})")

    def add_callback(self, callback: Union[
        Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]):
        """Добавить callback для сигналов"""
        self.callbacks.append(callback)

    def _get_timeframe_minutes(self) -> int:
        """Получить количество минут в таймфрейме"""
        if self.timeframe == "5m":
            return 5
        elif self.timeframe == "45m":
            return 45
        else:
            raise ValueError(f"Неподдерживаемый таймфрейм: {self.timeframe}")

    def _get_target_candle_start_time(self, timestamp_ms: int) -> int:
        """Получить время начала целевой свечи для данного timestamp с правильной сеткой"""
        if self.timeframe == "5m":
            # Для 5m: округляем до ближайших 5 минут (00, 05, 10, 15, 20...)
            dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            rounded_minute = (dt.minute // 5) * 5
            start_time = dt.replace(minute=rounded_minute, second=0, microsecond=0)
            return int(start_time.timestamp() * 1000)

        elif self.timeframe == "45m":
            # Для 45m: используем существующую правильную логику сетки
            return self._get_45m_grid_start_time(timestamp_ms)

        else:
            raise ValueError(f"Неподдерживаемый таймфрейм: {self.timeframe}")

    def _get_45m_grid_start_time(self, timestamp_ms: int) -> int:
        """Получить время начала 45m свечи по правильной сетке"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        minutes_from_day_start = (dt - day_start).total_seconds() / 60
        interval_index = int(minutes_from_day_start // 45)
        interval_start_minutes = interval_index * 45
        interval_start_time = day_start + timedelta(minutes=interval_start_minutes)
        return int(interval_start_time.timestamp() * 1000)

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
        """Определение сигналов MACD при пересечении линий"""
        if len(df) < 2:
            return None

        current = df.iloc[-1]
        current_macd = current['macd_line']
        current_signal = current['signal_line']

        # Проверяем есть ли предыдущие значения
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
                'timeframe': self.timeframe,
                'timestamp': current['timestamp'],
                'price': current['close'],
                'macd_line': current_macd,
                'signal_line': current_signal,
                'histogram': current['histogram'],
                'crossover_type': 'bullish'
            }

        # ПЕРЕСЕЧЕНИЕ СВЕРХУ ВНИЗ: медвежий сигнал
        elif (self.last_macd_line > self.last_signal_line and
              current_macd < current_signal):

            signal = {
                'type': 'sell',
                'timeframe': self.timeframe,
                'timestamp': current['timestamp'],
                'price': current['close'],
                'macd_line': current_macd,
                'signal_line': current_signal,
                'histogram': current['histogram'],
                'crossover_type': 'bearish'
            }

        # Обновляем предыдущие значения
        self.last_macd_line = current_macd
        self.last_signal_line = current_signal

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

    def _build_45m_candles_from_15m(self, klines_15m: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Построение 45m свечей из 15m по правильной временной сетке"""
        if not klines_15m:
            return []

        klines_15m.sort(key=lambda x: x['timestamp'])
        logger.info(f"📊 Строим 45m свечи из {len(klines_15m)} свечей 15m")

        custom_45m_klines = []
        grouped_klines = {}

        # Группируем 15m свечи по 45m интервалам согласно временной сетке
        for kline_15m in klines_15m:
            interval_start = self._get_45m_grid_start_time(kline_15m['timestamp'])

            if interval_start not in grouped_klines:
                grouped_klines[interval_start] = []

            grouped_klines[interval_start].append(kline_15m)

        # Создаем 45m свечи только из полных групп (3 свечи по 15m)
        for interval_start in sorted(grouped_klines.keys()):
            klines_group = grouped_klines[interval_start]

            if len(klines_group) == 3:
                klines_group.sort(key=lambda x: x['timestamp'])
                is_continuous = True

                for i in range(1, len(klines_group)):
                    expected_time = klines_group[i - 1]['timestamp'] + (15 * 60 * 1000)
                    if abs(klines_group[i]['timestamp'] - expected_time) > (2 * 60 * 1000):
                        is_continuous = False
                        break

                if is_continuous:
                    merged_45m = self._merge_15m_to_45m_candles(klines_group)
                    custom_45m_klines.append(merged_45m)

        logger.info(f"✅ Создано {len(custom_45m_klines)} полных 45m свечей")
        return custom_45m_klines

    @staticmethod
    def _merge_15m_to_45m_candles(klines_15m: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Объединение трех 15m свечей в одну 45m свечу"""
        if len(klines_15m) != 3:
            raise ValueError("Для создания 45m свечи нужно ровно 3 свечи по 15m")

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

    @staticmethod
    def _merge_1m_candles(klines_1m: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Объединение минутных свечей в одну целевую свечу"""
        if not klines_1m:
            raise ValueError("Нет свечей для объединения")

        klines_1m.sort(key=lambda x: x['timestamp'])

        merged = {
            'timestamp': klines_1m[0]['timestamp'],
            'open': klines_1m[0]['open'],
            'high': max(k['high'] for k in klines_1m),
            'low': min(k['low'] for k in klines_1m),
            'close': klines_1m[-1]['close'],
            'volume': sum(k['volume'] for k in klines_1m),
            'close_time': klines_1m[-1]['close_time'],
            'quote_volume': sum(k.get('quote_volume', 0) for k in klines_1m),
            'trades_count': sum(k.get('trades_count', 0) for k in klines_1m)
        }

        return merged

    async def load_historical_data(self):
        """Загрузка исторических данных с корректной инициализацией текущей свечи"""
        logger.info(f"📈 Загружаем историю {self.symbol} для {self.timeframe} MACD")

        # Загружаем исторические данные
        if self.timeframe == '5m':
            historical_klines = await self.binance_client.get_klines(self.symbol, '5m', self.min_history)
        elif self.timeframe == '45m':
            # Для 45m используем 15m и строим кастомные
            base_limit = self.min_history * 3 + 50
            base_klines_15m = await self.binance_client.get_klines(self.symbol, '15m', base_limit)
            if not base_klines_15m:
                raise Exception("Не удалось загрузить 15m данные для 45m")
            historical_klines = self._build_45m_candles_from_15m(base_klines_15m)
        else:
            raise Exception(f"Неподдерживаемый таймфрейм: {self.timeframe}")

        if not historical_klines:
            raise Exception(f"Не удалось загрузить исторические данные для {self.timeframe}")

        self.target_klines = historical_klines

        if len(self.target_klines) < self.min_history:
            logger.warning(
                f"⚠️ Получено {len(self.target_klines)} {self.timeframe} свечей, меньше требуемых {self.min_history}")

        # Правильная инициализация текущей свечи
        await self._initialize_current_candle_correctly()

        # Конвертируем в DataFrame и рассчитываем MACD
        self.df = self.klines_to_dataframe(self.target_klines)
        self.df = self.calculate_macd(self.df)

        logger.info(f"✅ История загружена: {len(self.df)} свечей {self.timeframe}")

    async def _initialize_current_candle_correctly(self):
        """Правильная инициализация текущей свечи с точным количеством запросов"""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # Получаем время последней ЗАКРЫТОЙ минутной свечи
        current_time = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        # Последняя закрытая свеча была минуту назад
        last_closed_minute = current_time.replace(second=0, microsecond=0) - timedelta(minutes=1)
        last_closed_ms = int(last_closed_minute.timestamp() * 1000)

        # К какому целевому интервалу относится последняя закрытая свеча
        self.current_target_start_time = self._get_target_candle_start_time(last_closed_ms)

        # Рассчитываем сколько минут прошло в текущем интервале
        candle_start_time = datetime.fromtimestamp(self.current_target_start_time / 1000, tz=timezone.utc)
        elapsed_seconds = (last_closed_minute - candle_start_time).total_seconds()
        elapsed_minutes = int(elapsed_seconds / 60) + 1  # +1 потому что включаем последнюю закрытую

        interval_minutes = self._get_timeframe_minutes()

        if 0 < elapsed_minutes < interval_minutes:
            # Запрашиваем ТОЧНО нужное количество
            logger.info(f"🔄 Собираем {elapsed_minutes} пропущенных минут в текущем {self.timeframe} интервале")
            await self._collect_missing_minutes_for_current_candle(elapsed_minutes)
        else:
            self.current_target_candle = None

    async def _collect_missing_minutes_for_current_candle(self, elapsed_minutes: int):
        """Запрашиваем ТОЧНО нужное количество свечей"""
        try:
            # Запрашиваем ровно столько, сколько нужно
            recent_1m_klines = await self.binance_client.get_klines(
                self.symbol, '1m', elapsed_minutes
            )

            if not recent_1m_klines:
                self.current_target_candle = None
                return

            # Фильтруем только те минуты, которые относятся к текущему интервалу
            current_interval_minutes = []

            for kline_1m in recent_1m_klines:
                kline_start = self._get_target_candle_start_time(kline_1m['timestamp'])
                if kline_start == self.current_target_start_time:
                    current_interval_minutes.append(kline_1m)

            if current_interval_minutes:
                # Сортируем по времени
                current_interval_minutes.sort(key=lambda x: x['timestamp'])

                # Строим текущую свечу из этих минут
                self.current_target_candle = self._merge_1m_candles(current_interval_minutes)
                # Устанавливаем правильное время начала интервала
                self.current_target_candle['timestamp'] = self.current_target_start_time

                logger.info(f"✅ Собрана текущая {self.timeframe} свеча из {len(current_interval_minutes)} минут")

            else:
                self.current_target_candle = None

        except Exception as e:
            logger.error(f"❌ Ошибка сбора пропущенных минут для {self.timeframe}: {e}")
            self.current_target_candle = None

    async def kline_callback(self, kline_1m: Dict[str, Any]):
        """Callback для новых минутных свечей"""
        try:
            await self._process_1m_kline(kline_1m)
        except Exception as e:
            logger.error(f"❌ Ошибка в kline_callback: {e}")

    async def _process_1m_kline(self, kline_1m: Dict[str, Any]):
        """Правильный порядок - сначала MACD, потом завершение интервала"""
        from ..utils.helpers import format_utc_to_msk

        self.total_candles_processed += 1
        kline_time_msk = format_utc_to_msk(kline_1m['timestamp'])

        # Определяем к какой целевой свече относится эта закрытая минутная свеча
        target_start_time = self._get_target_candle_start_time(kline_1m['timestamp'])

        # Если это новый целевой интервал - начинаем его
        if self.current_target_start_time != target_start_time:
            self._start_new_target_candle(target_start_time, kline_1m)
        else:
            # Обновляем текущую целевую свечу
            self._update_current_target_candle(kline_1m)

        # СНАЧАЛА показываем значения MACD
        await self._recalculate_macd_and_check_signals_every_minute(kline_time_msk)

        # ПОТОМ проверяем нужно ли завершить интервал
        if self._is_last_minute_of_interval(kline_1m['timestamp']):
            await self._complete_target_candle_with_signal()
            # Сбрасываем текущую свечу после завершения
            self.current_target_candle = None
            self.current_target_start_time = None

    def _is_last_minute_of_interval(self, timestamp_ms: int) -> bool:
        """Проверка является ли минутная свеча последней в целевом интервале"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

        if self.timeframe == "5m":
            # Для 5m последние минуты: 04, 09, 14, 19, 24, 29, 34, 39, 44, 49, 54, 59
            return dt.minute % 5 == 4

        elif self.timeframe == "45m":
            # Для 45m нужно проверить по сетке
            target_start = self._get_45m_grid_start_time(timestamp_ms)
            target_end = target_start + (45 * 60 * 1000)  # +45 минут
            next_minute = timestamp_ms + (60 * 1000)  # следующая минута

            # Если следующая минута выходит за границы интервала - значит текущая последняя
            return next_minute >= target_end

        return False

    async def _complete_target_candle_with_signal(self):
        """Завершение свечи + сразу показываем начало нового интервала"""
        if self.current_target_candle is None:
            return

        from ..utils.helpers import format_utc_to_msk

        # Логируем завершение текущего интервала
        start_time_msk = format_utc_to_msk(self.current_target_candle['timestamp'], "%H:%M")
        end_time_ms = self.current_target_candle['timestamp'] + (self._get_timeframe_minutes() * 60 * 1000)
        end_time_msk = format_utc_to_msk(end_time_ms, "%H:%M")

        logger.info(
            f"✅ Завершен {self.timeframe} интервал: {start_time_msk}-{end_time_msk} МСК, цена: {self.current_target_candle['close']}")

        # НОВОЕ: Сразу логируем начало следующего интервала
        next_start_time_ms = end_time_ms
        next_end_time_ms = next_start_time_ms + (self._get_timeframe_minutes() * 60 * 1000)
        next_start_msk = format_utc_to_msk(next_start_time_ms, "%H:%M")
        next_end_msk = format_utc_to_msk(next_end_time_ms, "%H:%M")

        logger.info(f"🆕 Начат новый {self.timeframe} интервал: {next_start_msk}-{next_end_msk} МСК")

        # Добавляем в историю
        self.target_klines.append(self.current_target_candle.copy())

        # Ограничиваем размер истории
        if len(self.target_klines) > self.min_history * 2:
            self.target_klines = self.target_klines[-self.min_history:]

        # Проверяем сигналы на завершенной свече
        await self._check_signals_on_completed_candle()

    async def _check_signals_on_completed_candle(self):
        """Проверка сигналов на завершенной свече"""
        # Создаем DataFrame только из завершенных свечей
        temp_df = self.klines_to_dataframe(self.target_klines)
        temp_df = self.calculate_macd(temp_df)

        if len(temp_df) < self.slow_period:
            return

        # Проверяем сигналы
        signal = self.detect_macd_signals(temp_df)

        if signal:
            # НАЙДЕНО ПЕРЕСЕЧЕНИЕ
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ MACD! {signal['crossover_type'].upper()} сигнал {signal['type'].upper()}")
            logger.info(
                f"   📊 Цена: {signal['price']:.2f} | MACD: {signal['macd_line']:.6f} | Signal: {signal['signal_line']:.6f} | Hist: {signal['histogram']:.6f}")
            logger.info(f"   ⏰ Время: {self._format_utc_to_msk(signal['timestamp'])} МСК | TF: {self.timeframe}")

            # Вызываем callback'и
            for callback in self.callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal)
                    else:
                        callback(signal)
                except Exception as e:
                    logger.error(f"❌ Ошибка в callback: {e}")

    def _start_new_target_candle(self, target_start_time: int, first_kline_1m: Dict[str, Any]):
        """Начинаем новую свечу БЕЗ лога (лог уже был при завершении предыдущей)"""
        self.current_target_start_time = target_start_time
        self.current_target_candle = {
            'timestamp': target_start_time,
            'open': first_kline_1m['open'],
            'high': first_kline_1m['high'],
            'low': first_kline_1m['low'],
            'close': first_kline_1m['close'],
            'volume': first_kline_1m['volume'],
            'close_time': first_kline_1m['close_time'],
            'quote_volume': first_kline_1m.get('quote_volume', 0),
            'trades_count': first_kline_1m.get('trades_count', 0)
        }

        # УБРАЛИ ЛОГ - он уже был показан при завершении предыдущего интервала

    def _update_current_target_candle(self, kline_1m: Dict[str, Any]):
        """Обновление текущей целевой свечи новой минутной свечей"""
        if self.current_target_candle is None:
            return

        # Обновляем OHLCV
        self.current_target_candle['high'] = max(self.current_target_candle['high'], kline_1m['high'])
        self.current_target_candle['low'] = min(self.current_target_candle['low'], kline_1m['low'])
        self.current_target_candle['close'] = kline_1m['close']
        self.current_target_candle['volume'] += kline_1m['volume']
        self.current_target_candle['close_time'] = kline_1m['close_time']
        self.current_target_candle['quote_volume'] += kline_1m.get('quote_volume', 0)
        self.current_target_candle['trades_count'] += kline_1m.get('trades_count', 0)

    async def _recalculate_macd_and_check_signals_every_minute(self, kline_time_msk: str):
        """Пересчет MACD и проверка сигналов КАЖДУЮ МИНУТУ"""
        if self.current_target_candle is None:
            return

        # Создаем временный список с текущей формируемой свечой
        temp_klines = self.target_klines + [self.current_target_candle]

        # Берем последние свечи для расчета
        recent_klines = temp_klines[-self.min_history:]

        # Конвертируем в DataFrame и рассчитываем MACD
        temp_df = self.klines_to_dataframe(recent_klines)
        temp_df = self.calculate_macd(temp_df)

        if len(temp_df) < self.slow_period:
            return

        # Получаем текущие значения MACD
        current = temp_df.iloc[-1]
        current_macd = current['macd_line']
        current_signal = current['signal_line']
        current_histogram = current['histogram']
        current_price = current['close']

        # Проверяем сигналы КАЖДУЮ МИНУТУ
        signal = self.detect_macd_signals(temp_df)

        if signal:
            # НАЙДЕНО ПЕРЕСЕЧЕНИЕ
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ MACD! {signal['crossover_type'].upper()} сигнал {signal['type'].upper()}")
            logger.info(
                f"   📊 Цена: {current_price:.2f} | MACD: {current_macd:.6f} | Signal: {current_signal:.6f} | Hist: {current_histogram:.6f}")
            logger.info(f"   ⏰ Время: {kline_time_msk} МСК | TF: {self.timeframe}")

            # Вызываем callback'и
            for callback in self.callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal)
                    else:
                        callback(signal)
                except Exception as e:
                    logger.error(f"❌ Ошибка в callback: {e}")
        else:
            # ПЕРЕСЕЧЕНИЯ НЕТ - логируем текущие значения
            logger.info(
                f"📊 СВЕЧА ПОЛУЧЕНА - ЗНАЧЕНИЯ MACD: Цена: {current_price:.2f} | MACD: {current_macd:.6f} | Signal: {current_signal:.6f} | Hist: {current_histogram:.6f} | ПЕРЕСЕЧЕНИЯ НЕТУ")

    def _format_utc_to_msk(self, timestamp: int, format_str: str = "%H:%M:%S") -> str:
        """Вспомогательная функция для форматирования времени"""
        from ..utils.helpers import format_utc_to_msk
        return format_utc_to_msk(timestamp, format_str)

    async def start(self):
        """Запуск индикатора"""
        if self.is_running:
            logger.warning("MACD индикатор уже запущен")
            return

        logger.info(f"🚀 Запуск Real-time MACD: {self.symbol} {self.timeframe}")

        try:
            # Загружаем историю
            await self.load_historical_data()

            # Запускаем WebSocket поток для минутных данных
            def callback_wrapper(kline: Dict[str, Any]) -> None:
                asyncio.create_task(self.kline_callback(kline))

            # Подписываемся на минутные данные
            await self.binance_client.start_kline_stream(self.symbol, '1m', callback_wrapper)
            self.stream_active = True

            self.is_running = True

            logger.info("✅ Real-time MACD индикатор запущен")

        except Exception as e:
            logger.error(f"❌ Ошибка запуска Real-time MACD: {e}")
            await self.stop()
            raise

    async def stop(self):
        """Остановка индикатора"""
        if not self.is_running:
            return

        logger.info("⏹️ Остановка Real-time MACD индикатора...")

        try:
            if self.stream_active:
                await self.binance_client.stop_kline_stream(self.symbol, '1m')
                self.stream_active = False

            # Сбрасываем состояние
            self.current_target_candle = None
            self.current_target_start_time = None
            self.last_macd_line = None
            self.last_signal_line = None

            self.is_running = False
            logger.info(f"✅ MACD индикатор остановлен (обработано {self.total_candles_processed} минутных свечей)")

        except Exception as e:
            logger.error(f"❌ Ошибка остановки MACD индикатора: {e}")

    async def close(self):
        """Закрытие индикатора и освобождение ресурсов"""
        await self.stop()
        await self.binance_client.close()

    def get_current_macd_values(self) -> Optional[Dict[str, Any]]:
        """Получение текущих значений MACD"""
        if self.current_target_candle is None:
            return None

        # Рассчитываем MACD для текущего состояния
        temp_klines = self.target_klines + [self.current_target_candle]
        temp_df = self.klines_to_dataframe(temp_klines[-self.min_history:])
        temp_df = self.calculate_macd(temp_df)

        if len(temp_df) == 0:
            return None

        current = temp_df.iloc[-1]

        return {
            'timestamp': current['timestamp'],
            'price': current['close'],
            'macd_line': current['macd_line'],
            'signal_line': current['signal_line'],
            'histogram': current['histogram'],
            'timeframe': self.timeframe,
            'is_realtime': True
        }

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса индикатора"""
        status = {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'is_running': self.is_running,
            'stream_active': self.stream_active,
            'target_candles_count': len(self.target_klines),
            'has_current_candle': self.current_target_candle is not None,
            'callbacks_count': len(self.callbacks),
            'total_candles_processed': self.total_candles_processed
        }

        if self.current_target_candle:
            current_time = datetime.fromtimestamp(self.current_target_candle['timestamp'] / 1000, tz=timezone.utc)
            status['current_candle_start'] = current_time.strftime('%H:%M:%S UTC')
            status['current_price'] = self.current_target_candle['close']

        return status
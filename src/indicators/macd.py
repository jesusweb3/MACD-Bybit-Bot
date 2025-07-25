# src/indicators/macd.py
import pandas as pd
import asyncio
from typing import Dict, Any, List, Optional, Callable, Union, Awaitable
from datetime import datetime, timezone, timedelta
from ..exchange.binance import BinanceClient
from ..utils.logger import logger


class MACDIndicator:
    """
    MACD индикатор с поддержкой двух таймфреймов
    - Таймфрейм входа: для определения входа в позицию
    - Таймфрейм выхода: для определения выхода из позиции
    """

    def __init__(self, symbol: str, entry_timeframe: str, exit_timeframe: str,
                 fast_period: int = 12, slow_period: int = 26, signal_period: int = 9,
                 min_history: int = 100):
        """
        Args:
            symbol: Торговая пара (BTCUSDT)
            entry_timeframe: Таймфрейм для входа (45m, 1h и т.д.)
            exit_timeframe: Таймфрейм для выхода (15m, 30m и т.д.)
            fast_period: Период быстрой EMA (по умолчанию 12)
            slow_period: Период медленной EMA (по умолчанию 26)
            signal_period: Период сигнальной линии (по умолчанию 9)
            min_history: Минимальное количество свечей для расчета
        """
        self.symbol = symbol
        self.entry_timeframe = entry_timeframe
        self.exit_timeframe = exit_timeframe
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.min_history = min_history

        # Определяем нужно ли использовать два разных таймфрейма
        self.dual_timeframe = entry_timeframe != exit_timeframe

        # Клиент для получения данных
        self.binance_client = BinanceClient()

        # История свечей для каждого таймфрейма
        self.entry_klines: List[Dict[str, Any]] = []
        self.exit_klines: List[Dict[str, Any]] = []

        # DataFrame для расчетов MACD
        self.entry_df: Optional[pd.DataFrame] = None
        self.exit_df: Optional[pd.DataFrame] = None

        # Callback функции для сигналов
        self.entry_callbacks: List[
            Union[Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]] = []
        self.exit_callbacks: List[
            Union[Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]] = []

        # Флаги состояния
        self.is_running = False
        self.entry_stream_active = False
        self.exit_stream_active = False

        # Кеш для накопления кастомных свечей
        self.custom_klines_cache: Dict[str, List[Dict[str, Any]]] = {}

        # Конфигурация кастомных таймфреймов
        self.custom_timeframes = {
            '45m': {'base': '15m', 'count': 3},  # 3 свечи по 15м
            '50m': {'base': '5m', 'count': 10},  # 10 свечей по 5м
            '55m': {'base': '5m', 'count': 11},  # 11 свечей по 5м
            '3h': {'base': '1h', 'count': 3},  # 3 свечи по 1ч
            '4h': {'base': '1h', 'count': 4}  # 4 свечи по 1ч
        }

        logger.info(f"MACD инициализирован для {symbol}")
        logger.info(f"Таймфрейм входа: {entry_timeframe}")
        logger.info(f"Таймфрейм выхода: {exit_timeframe}")
        logger.info(f"Режим: {'Dual TF' if self.dual_timeframe else 'Single TF'}")
        logger.info(f"Параметры MACD: {fast_period}, {slow_period}, {signal_period}")

    def add_entry_callback(self, callback: Union[
        Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]):
        """Добавить callback для сигналов входа"""
        self.entry_callbacks.append(callback)

    def add_exit_callback(self, callback: Union[
        Callable[[Dict[str, Any]], None], Callable[[Dict[str, Any]], Awaitable[None]]]):
        """Добавить callback для сигналов выхода"""
        self.exit_callbacks.append(callback)

    def _is_custom_timeframe(self, timeframe: str) -> bool:
        """Проверка является ли таймфрейм кастомным"""
        return timeframe in self.custom_timeframes

    @staticmethod
    def _get_timeframe_minutes(timeframe: str) -> int:
        """Получение количества минут в таймфрейме"""
        if timeframe.endswith('m'):
            return int(timeframe[:-1])
        elif timeframe.endswith('h'):
            return int(timeframe[:-1]) * 60
        return 0

    def _get_custom_interval_start_times(self, custom_tf: str) -> List[datetime]:
        """
        Получение правильных времен начала кастомных интервалов

        Args:
            custom_tf: Кастомный таймфрейм (45m, 50m, 55m)

        Returns:
            Список времен начала интервалов в течение дня
        """
        custom_minutes = self._get_timeframe_minutes(custom_tf)

        # Начинаем с полуночи UTC
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        start_times = []
        current_time = day_start

        # Генерируем все интервалы в течение дня
        while current_time.day == day_start.day:
            start_times.append(current_time)
            current_time += timedelta(minutes=custom_minutes)

        return start_times

    def _find_current_custom_interval(self, current_time: datetime, custom_tf: str) -> tuple[datetime, datetime]:
        """
        Определение текущего кастомного интервала

        Args:
            current_time: Текущее время
            custom_tf: Кастомный таймфрейм

        Returns:
            Кортеж (начало_интервала, конец_интервала)
        """
        custom_minutes = self._get_timeframe_minutes(custom_tf)

        # Получаем все интервалы дня
        start_times = self._get_custom_interval_start_times(custom_tf)

        # Находим подходящий интервал
        for i, start_time in enumerate(start_times):
            end_time = start_time + timedelta(minutes=custom_minutes)

            if start_time <= current_time < end_time:
                return start_time, end_time

        # Если не нашли в текущем дне, возможно это начало следующего дня
        next_day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return next_day_start, next_day_start + timedelta(minutes=custom_minutes)

    def _should_complete_custom_kline(self, kline_time: datetime, custom_tf: str) -> bool:
        """
        Проверка должна ли завершиться кастомная свеча

        Args:
            kline_time: Время закрытия базовой свечи
            custom_tf: Кастомный таймфрейм

        Returns:
            True если кастомная свеча должна завершиться
        """
        interval_start, interval_end = self._find_current_custom_interval(kline_time, custom_tf)

        # Кастомная свеча завершается, если базовая свеча закрывается в конце интервала
        # Учитываем небольшую погрешность (30 секунд)
        time_diff = abs((kline_time - interval_end).total_seconds())

        should_complete = time_diff <= 30  # 30 секунд погрешность

        if should_complete:
            logger.info(f"🕒 Завершение кастомной свечи {custom_tf}")
            logger.info(f"   Интервал: {interval_start.strftime('%H:%M')} - {interval_end.strftime('%H:%M')}")
            logger.info(f"   Время базовой свечи: {kline_time.strftime('%H:%M:%S')}")

        return should_complete

    @staticmethod
    def calculate_ema(data: pd.Series, period: int) -> pd.Series:
        """Расчет экспоненциальной скользящей средней"""
        return data.ewm(span=period, adjust=False).mean()

    def calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Расчет MACD индикатора

        Returns:
            DataFrame с колонками: macd_line, signal_line, histogram
        """
        if len(df) < self.slow_period:
            return pd.DataFrame()

        # Копируем DataFrame
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

    def detect_macd_signals(self, df: pd.DataFrame, timeframe_type: str) -> Optional[Dict[str, Any]]:
        """
        Определение сигналов MACD - ТОЛЬКО при пересечении линий

        Args:
            df: DataFrame с данными MACD
            timeframe_type: 'entry' или 'exit'

        Returns:
            Словарь с сигналом или None (только при пересечении!)
        """
        if len(df) < 2:
            return None

        # Берем последние две строки для определения пересечения
        current = df.iloc[-1]
        previous = df.iloc[-2]

        signal = None

        # ПЕРЕСЕЧЕНИЕ СНИЗУ ВВЕРХ: бычий сигнал
        # Предыдущая: MACD был НИЖЕ сигнальной линии
        # Текущая: MACD стал ВЫШЕ сигнальной линии
        if (previous['macd_line'] < previous['signal_line'] and
                current['macd_line'] > current['signal_line']):

            signal = {
                'type': 'buy' if timeframe_type == 'entry' else 'exit_short',
                'timeframe': self.entry_timeframe if timeframe_type == 'entry' else self.exit_timeframe,
                'timeframe_type': timeframe_type,
                'timestamp': current['timestamp'],
                'price': current['close'],
                'macd_line': current['macd_line'],
                'signal_line': current['signal_line'],
                'histogram': current['histogram'],
                'crossover_type': 'bullish'
            }

        # ПЕРЕСЕЧЕНИЕ СВЕРХУ ВНИЗ: медвежий сигнал
        # Предыдущая: MACD был ВЫШЕ сигнальной линии
        # Текущая: MACD стал НИЖЕ сигнальной линии
        elif (previous['macd_line'] > previous['signal_line'] and
              current['macd_line'] < current['signal_line']):

            signal = {
                'type': 'sell' if timeframe_type == 'entry' else 'exit_long',
                'timeframe': self.entry_timeframe if timeframe_type == 'entry' else self.exit_timeframe,
                'timeframe_type': timeframe_type,
                'timestamp': current['timestamp'],
                'price': current['close'],
                'macd_line': current['macd_line'],
                'signal_line': current['signal_line'],
                'histogram': current['histogram'],
                'crossover_type': 'bearish'
            }

        # Если нет пересечения - возвращаем None
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

    async def load_historical_data(self):
        """Загрузка исторических данных для обоих таймфреймов"""
        logger.info(f"Загружаем историю для {self.symbol}")

        if self._is_custom_timeframe(self.entry_timeframe):
            # Для кастомного таймфрейма загружаем базовые свечи
            config = self.custom_timeframes[self.entry_timeframe]
            base_timeframe = config['base']

            logger.info(
                f"Загружаем {self.min_history * config['count']} базовых свечей {base_timeframe} для {self.entry_timeframe}")
            base_klines = await self.binance_client.get_klines(
                self.symbol, base_timeframe, self.min_history * config['count']
            )

            if not base_klines:
                raise Exception(f"Не удалось загрузить базовые данные для {base_timeframe}")

            # Строим кастомные свечи из базовых
            self.entry_klines = self._build_historical_custom_klines(base_klines, self.entry_timeframe)

        else:
            # Обычный таймфрейм
            logger.info(f"Загружаем {self.min_history} свечей для входа ({self.entry_timeframe})")
            self.entry_klines = await self.binance_client.get_klines(
                self.symbol, self.entry_timeframe, self.min_history
            )

        if not self.entry_klines:
            raise Exception(f"Не удалось загрузить данные для {self.entry_timeframe}")

        # Если таймфреймы разные, загружаем данные для выхода
        if self.dual_timeframe:
            if self._is_custom_timeframe(self.exit_timeframe):
                # Аналогично для exit таймфрейма
                config = self.custom_timeframes[self.exit_timeframe]
                base_timeframe = config['base']

                base_klines = await self.binance_client.get_klines(
                    self.symbol, base_timeframe, self.min_history * config['count']
                )

                if not base_klines:
                    raise Exception(f"Не удалось загрузить базовые данные для {base_timeframe}")

                self.exit_klines = self._build_historical_custom_klines(base_klines, self.exit_timeframe)
            else:
                logger.info(f"Загружаем {self.min_history} свечей для выхода ({self.exit_timeframe})")
                self.exit_klines = await self.binance_client.get_klines(
                    self.symbol, self.exit_timeframe, self.min_history
                )

            if not self.exit_klines:
                raise Exception(f"Не удалось загрузить данные для {self.exit_timeframe}")
        else:
            # Если таймфреймы одинаковые, используем те же данные
            self.exit_klines = self.entry_klines.copy()

        # Конвертируем в DataFrame
        self.entry_df = MACDIndicator.klines_to_dataframe(self.entry_klines)
        self.exit_df = MACDIndicator.klines_to_dataframe(self.exit_klines)

        # Рассчитываем начальные MACD
        self.entry_df = self.calculate_macd(self.entry_df)
        self.exit_df = self.calculate_macd(self.exit_df)

        logger.info(f"✅ История загружена: вход={len(self.entry_df)}, выход={len(self.exit_df)}")

    def _build_historical_custom_klines(self, base_klines: List[Dict[str, Any]], custom_tf: str) -> List[
        Dict[str, Any]]:
        """Построение кастомных свечей из исторических базовых свечей"""
        if not base_klines:
            return []

        config = self.custom_timeframes[custom_tf]
        custom_minutes = self._get_timeframe_minutes(custom_tf)

        custom_klines = []
        current_group = []

        for kline in base_klines:
            kline_time = datetime.fromtimestamp(kline['timestamp'] / 1000, tz=timezone.utc)

            # Определяем к какому кастомному интервалу относится эта свеча
            interval_start, interval_end = self._find_current_custom_interval(kline_time, custom_tf)

            # Если это новый интервал и у нас есть накопленные свечи - завершаем предыдущий
            if current_group:
                last_kline_time = datetime.fromtimestamp(current_group[-1]['timestamp'] / 1000, tz=timezone.utc)
                last_interval_start, _ = self._find_current_custom_interval(last_kline_time, custom_tf)

                if interval_start != last_interval_start:
                    # Новый интервал - завершаем предыдущий
                    if len(current_group) > 0:
                        merged = self._merge_klines(current_group)
                        if merged:
                            custom_klines.append(merged)
                    current_group = []

            # Добавляем свечу в текущую группу
            current_group.append(kline)

        # Завершаем последнюю группу
        if current_group:
            merged = self._merge_klines(current_group)
            if merged:
                custom_klines.append(merged)

        logger.info(f"Построено {len(custom_klines)} кастомных свечей {custom_tf} из {len(base_klines)} базовых")
        return custom_klines

    @staticmethod
    def _merge_klines(klines: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Объединение нескольких свечей в одну кастомную"""
        if not klines:
            return {}

        # Сортируем по времени
        klines.sort(key=lambda x: x['timestamp'])

        merged = {
            'timestamp': klines[0]['timestamp'],
            'open': klines[0]['open'],
            'high': max(k['high'] for k in klines),
            'low': min(k['low'] for k in klines),
            'close': klines[-1]['close'],
            'volume': sum(k['volume'] for k in klines),
            'close_time': klines[-1]['close_time'],
            'quote_volume': sum(k.get('quote_volume', 0) for k in klines),
            'trades_count': sum(k.get('trades_count', 0) for k in klines)
        }

        return merged

    async def entry_kline_callback(self, kline: Dict[str, Any]):
        """Callback для новых свечей таймфрейма входа"""
        try:
            if self._is_custom_timeframe(self.entry_timeframe):
                # Обрабатываем кастомный таймфрейм
                await self._process_custom_kline_entry(kline)
            else:
                # Обрабатываем обычный таймфрейм
                await self._process_standard_kline_entry(kline)

        except Exception as e:
            logger.error(f"Ошибка в entry_kline_callback: {e}")

    async def _process_standard_kline_entry(self, kline: Dict[str, Any]):
        """Обработка обычной свечи для входа"""
        # Добавляем новую свечу
        self.entry_klines.append(kline)

        # Обновляем DataFrame
        self.entry_df = MACDIndicator.klines_to_dataframe(self.entry_klines[-self.min_history:])
        self.entry_df = self.calculate_macd(self.entry_df)

        # Проверяем сигналы ТОЛЬКО при пересечении
        signal = self.detect_macd_signals(self.entry_df, 'entry')

        if signal:
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ! Сигнал входа: {signal['type']} на {signal['timeframe']}")
            logger.info(f"   Тип пересечения: {signal['crossover_type']}")
            logger.info(
                f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

            # Вызываем все callback'и для входа
            for callback in self.entry_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal)
                    else:
                        callback(signal)
                except Exception as e:
                    logger.error(f"Ошибка в entry callback: {e}")

    async def _process_custom_kline_entry(self, base_kline: Dict[str, Any]):
        """Обработка базовой свечи для кастомного таймфрейма входа"""
        cache_key = f"{self.symbol}_{self.entry_timeframe}_entry"

        # Инициализируем кеш если нужно
        if cache_key not in self.custom_klines_cache:
            self.custom_klines_cache[cache_key] = []

        # Добавляем базовую свечу в кеш
        self.custom_klines_cache[cache_key].append(base_kline)

        # Проверяем нужно ли завершить кастомную свечу
        base_kline_time = datetime.fromtimestamp(base_kline['close_time'] / 1000, tz=timezone.utc)

        if self._should_complete_custom_kline(base_kline_time, self.entry_timeframe):
            # Завершаем кастомную свечу
            cached_klines = self.custom_klines_cache[cache_key]

            if cached_klines:
                # Формируем кастомную свечу
                custom_kline = self._merge_klines(cached_klines)

                if custom_kline:
                    # Добавляем к истории
                    self.entry_klines.append(custom_kline)

                    # Обновляем DataFrame
                    self.entry_df = MACDIndicator.klines_to_dataframe(self.entry_klines[-self.min_history:])
                    self.entry_df = self.calculate_macd(self.entry_df)

                    # Проверяем сигналы
                    signal = self.detect_macd_signals(self.entry_df, 'entry')

                    if signal:
                        logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ! Сигнал входа: {signal['type']} на {signal['timeframe']}")
                        logger.info(f"   Тип пересечения: {signal['crossover_type']}")
                        logger.info(
                            f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

                        # Вызываем все callback'и для входа
                        for callback in self.entry_callbacks:
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(signal)
                                else:
                                    callback(signal)
                            except Exception as e:
                                logger.error(f"Ошибка в entry callback: {e}")

                # Очищаем кеш для следующего интервала
                self.custom_klines_cache[cache_key] = []

    async def exit_kline_callback(self, kline: Dict[str, Any]):
        """Callback для новых свечей таймфрейма выхода"""
        try:
            # Для Single TF режима не обрабатываем exit callback отдельно
            if not self.dual_timeframe:
                return

            if self._is_custom_timeframe(self.exit_timeframe):
                # Обрабатываем кастомный таймфрейм
                await self._process_custom_kline_exit(kline)
            else:
                # Обрабатываем обычный таймфрейм
                await self._process_standard_kline_exit(kline)

        except Exception as e:
            logger.error(f"Ошибка в exit_kline_callback: {e}")

    async def _process_standard_kline_exit(self, kline: Dict[str, Any]):
        """Обработка обычной свечи для выхода"""
        # Добавляем новую свечу
        self.exit_klines.append(kline)

        # Обновляем DataFrame
        self.exit_df = MACDIndicator.klines_to_dataframe(self.exit_klines[-self.min_history:])
        self.exit_df = self.calculate_macd(self.exit_df)

        # Проверяем сигналы ТОЛЬКО при пересечении
        signal = self.detect_macd_signals(self.exit_df, 'exit')

        if signal:
            logger.info(f"🚪 ПЕРЕСЕЧЕНИЕ! Сигнал выхода: {signal['type']} на {signal['timeframe']}")
            logger.info(f"   Тип пересечения: {signal['crossover_type']}")
            logger.info(
                f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

            # Вызываем все callback'и для выхода
            for callback in self.exit_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal)
                    else:
                        callback(signal)
                except Exception as e:
                    logger.error(f"Ошибка в exit callback: {e}")

    async def _process_custom_kline_exit(self, base_kline: Dict[str, Any]):
        """Обработка базовой свечи для кастомного таймфрейма выхода"""
        cache_key = f"{self.symbol}_{self.exit_timeframe}_exit"

        # Инициализируем кеш если нужно
        if cache_key not in self.custom_klines_cache:
            self.custom_klines_cache[cache_key] = []

        # Добавляем базовую свечу в кеш
        self.custom_klines_cache[cache_key].append(base_kline)

        # Проверяем нужно ли завершить кастомную свечу
        base_kline_time = datetime.fromtimestamp(base_kline['close_time'] / 1000, tz=timezone.utc)

        if self._should_complete_custom_kline(base_kline_time, self.exit_timeframe):
            # Завершаем кастомную свечу
            cached_klines = self.custom_klines_cache[cache_key]

            if cached_klines:
                # Формируем кастомную свечу
                custom_kline = self._merge_klines(cached_klines)

                if custom_kline:
                    # Добавляем к истории
                    self.exit_klines.append(custom_kline)

                    # Обновляем DataFrame
                    self.exit_df = MACDIndicator.klines_to_dataframe(self.exit_klines[-self.min_history:])
                    self.exit_df = self.calculate_macd(self.exit_df)

                    # Проверяем сигналы
                    signal = self.detect_macd_signals(self.exit_df, 'exit')

                    if signal:
                        logger.info(f"🚪 ПЕРЕСЕЧЕНИЕ! Сигнал выхода: {signal['type']} на {signal['timeframe']}")
                        logger.info(f"   Тип пересечения: {signal['crossover_type']}")
                        logger.info(
                            f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

                        # Вызываем все callback'и для выхода
                        for callback in self.exit_callbacks:
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(signal)
                                else:
                                    callback(signal)
                            except Exception as e:
                                logger.error(f"Ошибка в exit callback: {e}")

                # Очищаем кеш для следующего интервала
                self.custom_klines_cache[cache_key] = []

    async def start(self):
        """Запуск индикатора"""
        if self.is_running:
            logger.warning("MACD индикатор уже запущен")
            return

        logger.info(f"🚀 Запускаем MACD индикатор для {self.symbol}")

        try:
            # Загружаем историю
            await self.load_historical_data()

            # Запускаем WebSocket потоки
            logger.info("🔄 Запускаем WebSocket потоки...")

            # Создаем синхронные обертки для async callback'ов
            def entry_wrapper(kline: Dict[str, Any]) -> None:
                asyncio.create_task(self.entry_kline_callback(kline))

            def exit_wrapper(kline: Dict[str, Any]) -> None:
                asyncio.create_task(self.exit_kline_callback(kline))

            # Определяем какой базовый таймфрейм нужен для entry
            if self._is_custom_timeframe(self.entry_timeframe):
                base_entry_tf = self.custom_timeframes[self.entry_timeframe]['base']
            else:
                base_entry_tf = self.entry_timeframe

            # Поток для входа
            await self.binance_client.start_kline_stream(
                self.symbol, base_entry_tf, entry_wrapper
            )
            self.entry_stream_active = True

            # Поток для выхода (только если таймфреймы разные)
            if self.dual_timeframe:
                if self._is_custom_timeframe(self.exit_timeframe):
                    base_exit_tf = self.custom_timeframes[self.exit_timeframe]['base']
                else:
                    base_exit_tf = self.exit_timeframe

                # Запускаем только если базовые таймфреймы разные
                if base_exit_tf != base_entry_tf:
                    await self.binance_client.start_kline_stream(
                        self.symbol, base_exit_tf, exit_wrapper
                    )

                self.exit_stream_active = True
            else:
                # Если таймфреймы одинаковые, exit_stream считается активным
                # но используем тот же поток что и для entry
                self.exit_stream_active = True

            self.is_running = True
            logger.info("✅ MACD индикатор запущен и готов к работе")

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
            # Определяем базовые таймфреймы
            if self._is_custom_timeframe(self.entry_timeframe):
                base_entry_tf = self.custom_timeframes[self.entry_timeframe]['base']
            else:
                base_entry_tf = self.entry_timeframe

            if self.dual_timeframe:
                if self._is_custom_timeframe(self.exit_timeframe):
                    base_exit_tf = self.custom_timeframes[self.exit_timeframe]['base']
                else:
                    base_exit_tf = self.exit_timeframe
            else:
                base_exit_tf = base_entry_tf

            # Останавливаем потоки
            if self.entry_stream_active:
                await self.binance_client.stop_kline_stream(self.symbol, base_entry_tf)
                self.entry_stream_active = False

            if self.dual_timeframe and self.exit_stream_active and base_exit_tf != base_entry_tf:
                await self.binance_client.stop_kline_stream(self.symbol, base_exit_tf)
                self.exit_stream_active = False

            # Очищаем кеши
            self.custom_klines_cache.clear()

            self.is_running = False
            logger.info("✅ MACD индикатор остановлен")

        except Exception as e:
            logger.error(f"Ошибка остановки MACD индикатора: {e}")

    async def close(self):
        """Закрытие индикатора и освобождение ресурсов"""
        await self.stop()
        await self.binance_client.close()
        logger.info("🔒 MACD индикатор закрыт")

    def get_current_macd_values(self, timeframe_type: str = 'entry') -> Optional[Dict[str, Any]]:
        """
        Получение текущих значений MACD

        Args:
            timeframe_type: 'entry' или 'exit'

        Returns:
            Словарь с текущими значениями или None
        """
        df = self.entry_df if timeframe_type == 'entry' else self.exit_df

        if df is None or len(df) == 0:
            return None

        current = df.iloc[-1]

        return {
            'timestamp': current['timestamp'],
            'price': current['close'],
            'macd_line': current['macd_line'],
            'signal_line': current['signal_line'],
            'histogram': current['histogram'],
            'timeframe': self.entry_timeframe if timeframe_type == 'entry' else self.exit_timeframe
        }

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса индикатора"""
        return {
            'symbol': self.symbol,
            'entry_timeframe': self.entry_timeframe,
            'exit_timeframe': self.exit_timeframe,
            'dual_timeframe': self.dual_timeframe,
            'is_running': self.is_running,
            'entry_stream_active': self.entry_stream_active,
            'exit_stream_active': self.exit_stream_active,
            'entry_data_length': len(self.entry_df) if self.entry_df is not None else 0,
            'exit_data_length': len(self.exit_df) if self.exit_df is not None else 0,
            'entry_callbacks': len(self.entry_callbacks),
            'exit_callbacks': len(self.exit_callbacks)
        }
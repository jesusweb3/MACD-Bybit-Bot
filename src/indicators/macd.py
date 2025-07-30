# src/indicators/macd.py
import pandas as pd
import asyncio
from typing import Dict, Any, List, Optional, Callable, Union, Awaitable
from ..exchange.binance import BinanceClient
from ..utils.logger import logger


class MACDIndicator:
    """
    MACD индикатор с поддержкой двух таймфреймов
    - Таймфрейм входа: для определения входа в позицию
    - Таймфрейм выхода: для определения выхода из позиции

    Поддерживаемые таймфреймы: 5m, 45m
    """

    def __init__(self, symbol: str, entry_timeframe: str, exit_timeframe: str,
                 fast_period: int = 12, slow_period: int = 26, signal_period: int = 7,
                 min_history: int = 100):
        """
        Args:
            symbol: Торговая пара (BTCUSDT)
            entry_timeframe: Таймфрейм для входа (5m, 45m)
            exit_timeframe: Таймфрейм для выхода (5m, 45m)
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

        # Состояние для кастомного таймфрейма 45m
        self.custom_45m_state: Optional[Dict[str, Any]] = None

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
        """Проверка является ли таймфрейм кастомным (только 45m)"""
        return timeframe == '45m'

    def _init_custom_45m_state(self, state_key: str):
        """Инициализация состояния для 45m таймфрейма"""
        if self.custom_45m_state is None:
            self.custom_45m_state = {
                'timeframe': '45m',
                'base_timeframe': '15m',
                'required_count': 3,
                'accumulated_klines': [],
                'current_count': 0,
                'state_key': state_key
            }
            logger.info(f"Инициализировано состояние для 45m: 3 x 15m")

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

    def _build_45m_klines_from_15m(self, base_klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Построение 45m свечей из 15m базовых свечей
        """
        if not base_klines:
            return []

        custom_klines = []
        current_batch = []
        required_count = 3  # 3 x 15m = 45m

        logger.info(f"Строим 45m свечи из {len(base_klines)} базовых 15m свечей")

        for i, kline in enumerate(base_klines):
            current_batch.append(kline)

            # Если накопили нужное количество - формируем кастомную свечу
            if len(current_batch) == required_count:
                merged = self._merge_klines(current_batch)
                if merged:
                    custom_klines.append(merged)
                    logger.debug(f"Создана 45m свеча {len(custom_klines)} из 15m свечей {i - required_count + 1}-{i}")

                current_batch = []

        # Если остались неполные данные - НЕ создаем неполную свечу
        if current_batch:
            logger.info(f"Осталось {len(current_batch)} неполных 15m свечей (не используются)")

        logger.info(f"Создано {len(custom_klines)} полных 45m свечей")
        return custom_klines

    async def load_historical_data(self):
        """Загрузка исторических данных для обоих таймфреймов"""
        logger.info(f"Загружаем историю для {self.symbol}")

        # Загружаем данные для entry таймфрейма
        if self.entry_timeframe == '45m':
            # Для 45m загружаем 15m свечи и строим кастомные
            base_limit = self.min_history * 3  # 3 x 15m = 45m
            logger.info(f"Загружаем {base_limit} базовых 15m свечей для 45m")
            base_klines = await self.binance_client.get_klines(self.symbol, '15m', base_limit)

            if not base_klines:
                raise Exception("Не удалось загрузить базовые данные для 15m")

            self.entry_klines = self._build_45m_klines_from_15m(base_klines)
        else:
            # Для 5m загружаем напрямую
            logger.info(f"Загружаем {self.min_history} свечей для входа (5m)")
            self.entry_klines = await self.binance_client.get_klines(
                self.symbol, self.entry_timeframe, self.min_history
            )

        if not self.entry_klines:
            raise Exception(f"Не удалось загрузить данные для {self.entry_timeframe}")

        # Загружаем данные для exit таймфрейма (если он отличается)
        if self.dual_timeframe:
            if self.exit_timeframe == '45m':
                # Для 45m загружаем 15m свечи и строим кастомные
                base_limit = self.min_history * 3
                base_klines = await self.binance_client.get_klines(self.symbol, '15m', base_limit)
                if not base_klines:
                    raise Exception("Не удалось загрузить базовые данные для 15m")

                self.exit_klines = self._build_45m_klines_from_15m(base_klines)
            else:
                # Для 5m загружаем напрямую
                logger.info(f"Загружаем {self.min_history} свечей для выхода (5m)")
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

    async def entry_kline_callback(self, kline: Dict[str, Any]):
        """Callback для новых свечей таймфрейма входа"""
        try:
            if self.entry_timeframe == '45m':
                await self._process_45m_kline(kline, 'entry')
            else:
                await self._process_standard_kline(kline, 'entry')
        except Exception as e:
            logger.error(f"Ошибка в entry_kline_callback: {e}")

    async def exit_kline_callback(self, kline: Dict[str, Any]):
        """Callback для новых свечей таймфрейма выхода"""
        try:
            # Для Single TF режима не обрабатываем exit callback отдельно
            if not self.dual_timeframe:
                return

            if self.exit_timeframe == '45m':
                await self._process_45m_kline(kline, 'exit')
            else:
                await self._process_standard_kline(kline, 'exit')
        except Exception as e:
            logger.error(f"Ошибка в exit_kline_callback: {e}")

    async def _process_standard_kline(self, kline: Dict[str, Any], timeframe_type: str):
        """Обработка обычной свечи (5m)"""
        # Добавляем новую свечу
        if timeframe_type == 'entry':
            self.entry_klines.append(kline)
            self.entry_df = MACDIndicator.klines_to_dataframe(self.entry_klines[-self.min_history:])
            self.entry_df = self.calculate_macd(self.entry_df)

            signal = self.detect_macd_signals(self.entry_df, 'entry')
            callbacks = self.entry_callbacks
        else:
            self.exit_klines.append(kline)
            self.exit_df = MACDIndicator.klines_to_dataframe(self.exit_klines[-self.min_history:])
            self.exit_df = self.calculate_macd(self.exit_df)

            signal = self.detect_macd_signals(self.exit_df, 'exit')
            callbacks = self.exit_callbacks

        if signal:
            timeframe = signal['timeframe']
            logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ! Сигнал {timeframe_type}: {signal['type']} на {timeframe}")
            logger.info(f"   Тип пересечения: {signal['crossover_type']}")
            logger.info(
                f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

            # Вызываем callback'и
            for callback in callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(signal)
                    else:
                        callback(signal)
                except Exception as e:
                    logger.error(f"Ошибка в {timeframe_type} callback: {e}")

    async def _process_45m_kline(self, base_kline: Dict[str, Any], timeframe_type: str):
        """Обработка 45m кастомной свечи из 15m базовой"""
        state_key = f"{self.symbol}_45m_{timeframe_type}"

        # Инициализируем состояние если нужно
        self._init_custom_45m_state(state_key)

        state = self.custom_45m_state

        # Добавляем базовую свечу
        state['accumulated_klines'].append(base_kline)
        state['current_count'] += 1

        logger.debug(f"Накоплено {state['current_count']}/3 базовых 15m свечей для 45m")

        # Проверяем завершена ли кастомная свеча
        if state['current_count'] >= 3:
            # Берем точно 3 свечи
            klines_for_custom = state['accumulated_klines'][:3]

            # Формируем кастомную свечу
            custom_kline = self._merge_klines(klines_for_custom)

            if custom_kline:
                logger.info(f"✅ Сформирована 45m свеча")

                # Добавляем к истории
                if timeframe_type == 'entry':
                    self.entry_klines.append(custom_kline)
                    self.entry_df = MACDIndicator.klines_to_dataframe(self.entry_klines[-self.min_history:])
                    self.entry_df = self.calculate_macd(self.entry_df)

                    signal = self.detect_macd_signals(self.entry_df, 'entry')
                    callbacks = self.entry_callbacks
                else:
                    self.exit_klines.append(custom_kline)
                    self.exit_df = MACDIndicator.klines_to_dataframe(self.exit_klines[-self.min_history:])
                    self.exit_df = self.calculate_macd(self.exit_df)

                    signal = self.detect_macd_signals(self.exit_df, 'exit')
                    callbacks = self.exit_callbacks

                # Проверяем сигналы
                if signal:
                    logger.info(f"🎯 ПЕРЕСЕЧЕНИЕ! Сигнал {timeframe_type}: {signal['type']} на 45m")
                    logger.info(f"   Тип пересечения: {signal['crossover_type']}")
                    logger.info(
                        f"   Цена: {signal['price']}, MACD: {signal['macd_line']:.6f} → Signal: {signal['signal_line']:.6f}")

                    # Вызываем callback'и
                    for callback in callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(signal)
                            else:
                                callback(signal)
                        except Exception as e:
                            logger.error(f"Ошибка в {timeframe_type} callback: {e}")

            # Сбрасываем состояние для следующей кастомной свечи
            state['accumulated_klines'] = []
            state['current_count'] = 0

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

            # Определяем базовый таймфрейм для entry
            base_entry_tf = '15m' if self.entry_timeframe == '45m' else self.entry_timeframe

            # Поток для входа
            await self.binance_client.start_kline_stream(self.symbol, base_entry_tf, entry_wrapper)
            self.entry_stream_active = True

            # Поток для выхода (только если таймфреймы разные)
            if self.dual_timeframe:
                base_exit_tf = '15m' if self.exit_timeframe == '45m' else self.exit_timeframe

                # Запускаем только если базовые таймфреймы разные
                if base_exit_tf != base_entry_tf:
                    await self.binance_client.start_kline_stream(self.symbol, base_exit_tf, exit_wrapper)

                self.exit_stream_active = True
            else:
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
            # Определяем базовые таймфреймы для остановки потоков
            base_entry_tf = '15m' if self.entry_timeframe == '45m' else self.entry_timeframe

            if self.dual_timeframe:
                base_exit_tf = '15m' if self.exit_timeframe == '45m' else self.exit_timeframe
            else:
                base_exit_tf = base_entry_tf

            # Останавливаем потоки
            if self.entry_stream_active:
                await self.binance_client.stop_kline_stream(self.symbol, base_entry_tf)
                self.entry_stream_active = False

            if self.dual_timeframe and self.exit_stream_active and base_exit_tf != base_entry_tf:
                await self.binance_client.stop_kline_stream(self.symbol, base_exit_tf)
                self.exit_stream_active = False

            # Очищаем состояние
            self.custom_45m_state = None

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
        """Получение текущих значений MACD"""
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
        status = {
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

        # Добавляем состояние 45m если есть
        if self.custom_45m_state:
            status['custom_45m_state'] = f"{self.custom_45m_state['current_count']}/3"

        return status
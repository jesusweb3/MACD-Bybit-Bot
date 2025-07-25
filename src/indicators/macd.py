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

        # Загружаем данные для таймфрейма входа
        logger.info(f"Загружаем {self.min_history} свечей для входа ({self.entry_timeframe})")
        self.entry_klines = await self.binance_client.get_klines(
            self.symbol, self.entry_timeframe, self.min_history
        )

        if not self.entry_klines:
            raise Exception(f"Не удалось загрузить данные для {self.entry_timeframe}")

        # Если таймфреймы разные, загружаем данные для выхода
        if self.dual_timeframe:
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

    async def entry_kline_callback(self, kline: Dict[str, Any]):
        """Callback для новых свечей таймфрейма входа"""
        try:
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

        except Exception as e:
            logger.error(f"Ошибка в entry_kline_callback: {e}")

    async def exit_kline_callback(self, kline: Dict[str, Any]):
        """Callback для новых свечей таймфрейма выхода"""
        try:
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

        except Exception as e:
            logger.error(f"Ошибка в exit_kline_callback: {e}")

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

            # Поток для входа
            await self.binance_client.start_kline_stream(
                self.symbol, self.entry_timeframe, entry_wrapper
            )
            self.entry_stream_active = True

            # Поток для выхода (только если таймфреймы разные)
            if self.dual_timeframe:
                await self.binance_client.start_kline_stream(
                    self.symbol, self.exit_timeframe, exit_wrapper
                )
                self.exit_stream_active = True
            else:
                # Если таймфреймы одинаковые, используем один callback для обоих
                self.exit_stream_active = True

                # Создаем объединенный синхронный callback
                def combined_wrapper(kline: Dict[str, Any]) -> None:
                    asyncio.create_task(self.entry_kline_callback(kline))
                    asyncio.create_task(self.exit_kline_callback(kline))

                # Перезапускаем поток с объединенным callback
                await self.binance_client.stop_kline_stream(self.symbol, self.entry_timeframe)
                await self.binance_client.start_kline_stream(
                    self.symbol, self.entry_timeframe, combined_wrapper
                )

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
            # Останавливаем потоки
            if self.entry_stream_active:
                await self.binance_client.stop_kline_stream(self.symbol, self.entry_timeframe)
                self.entry_stream_active = False

            if self.dual_timeframe and self.exit_stream_active:
                await self.binance_client.stop_kline_stream(self.symbol, self.exit_timeframe)
                self.exit_stream_active = False

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
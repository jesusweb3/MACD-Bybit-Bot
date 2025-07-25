# src/exchange/binance.py
import aiohttp
import asyncio
import json
import websockets.asyncio.client
import websockets.exceptions
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timezone, timedelta
from ..utils.logger import logger


class BinanceClient:
    """Клиент для Binance Futures API и WebSocket с поддержкой кастомных таймфреймов"""

    def __init__(self):
        self.base_url = "https://fapi.binance.com"
        self.ws_url = "wss://fstream.binance.com/ws"
        self.timeout = aiohttp.ClientTimeout(total=10)
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_connection: Optional[Any] = None
        self.ws_callbacks: Dict[str, Callable] = {}
        self.is_ws_running = False

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

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP сессии"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self.session

    async def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Выполнение HTTP запроса к Binance API"""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"

        try:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Binance API error {response.status}: {error_text}")

                data: Dict[str, Any] = await response.json()
                return data

        except Exception as e:
            logger.error(f"Ошибка HTTP запроса {endpoint}: {e}")
            raise

    def _is_custom_timeframe(self, timeframe: str) -> bool:
        """Проверка является ли таймфрейм кастомным"""
        return timeframe in self.custom_timeframes

    def _convert_timeframe(self, timeframe: str) -> str:
        """Конвертация таймфрейма в формат Binance"""
        if self._is_custom_timeframe(timeframe):
            return self.custom_timeframes[timeframe]['base']

        timeframe_map = {
            '5m': '5m',
            '15m': '15m',
            '1h': '1h',
            '2h': '2h'
        }
        return timeframe_map.get(timeframe, timeframe)

    @staticmethod
    def _get_timeframe_minutes(timeframe: str) -> int:
        """Получение количества минут в таймфрейме"""
        if timeframe.endswith('m'):
            return int(timeframe[:-1])
        elif timeframe.endswith('h'):
            return int(timeframe[:-1]) * 60
        return 0

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

    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Получение исторических свечей через REST API
        Поддерживает кастомные таймфреймы
        """
        try:
            if self._is_custom_timeframe(interval):
                return await self._get_custom_klines(symbol, interval, limit)
            else:
                return await self._get_standard_klines(symbol, interval, limit)

        except Exception as e:
            logger.error(f"Ошибка получения свечей {symbol} {interval}: {e}")
            return []

    async def _get_standard_klines(self, symbol: str, interval: str, limit: int) -> List[Dict[str, Any]]:
        """Получение стандартных свечей"""
        binance_interval = self._convert_timeframe(interval)
        logger.info(f"Запрашиваем {limit} стандартных свечей {symbol} {binance_interval}")

        params = {
            'symbol': symbol,
            'interval': binance_interval,
            'limit': min(limit, 1500)
        }

        response = await self._make_request('/fapi/v1/klines', params)

        klines = []
        for kline_data in response:
            kline = {
                'timestamp': int(kline_data[0]),
                'open': float(kline_data[1]),
                'high': float(kline_data[2]),
                'low': float(kline_data[3]),
                'close': float(kline_data[4]),
                'volume': float(kline_data[5]),
                'close_time': int(kline_data[6]),
                'quote_volume': float(kline_data[7]),
                'trades_count': int(kline_data[8])
            }
            klines.append(kline)

        logger.info(f"Получено {len(klines)} стандартных свечей для {symbol}")
        return klines

    async def _get_custom_klines(self, symbol: str, interval: str, limit: int) -> List[Dict[str, Any]]:
        """Получение кастомных свечей"""
        config = self.custom_timeframes[interval]
        base_interval = config['base']

        # Для кастомных свечей нужно больше базовых свечей
        base_limit = limit * config['count'] * 2  # С запасом

        logger.info(
            f"Запрашиваем {base_limit} базовых свечей {base_interval} для формирования {limit} кастомных {interval}")

        # Получаем базовые свечи
        base_klines = await self._get_standard_klines(symbol, base_interval, min(base_limit, 1500))

        if not base_klines:
            return []

        # Формируем кастомные свечи
        custom_klines = self._build_custom_klines(base_klines, interval)

        # Возвращаем последние limit свечей
        result = custom_klines[-limit:] if len(custom_klines) > limit else custom_klines

        logger.info(f"Сформировано {len(result)} кастомных свечей {interval} для {symbol}")
        return result

    def _build_custom_klines(self, base_klines: List[Dict[str, Any]], custom_interval: str) -> List[Dict[str, Any]]:
        """Построение кастомных свечей из базовых с учетом суточного сброса"""
        if not base_klines:
            return []

        custom_minutes = self._get_timeframe_minutes(custom_interval)

        custom_klines = []

        # Группируем свечи по дням
        daily_groups = self._group_klines_by_day(base_klines)

        for day_klines in daily_groups:
            # Обрабатываем свечи одного дня
            day_customs = self._build_day_custom_klines(day_klines, custom_minutes)
            custom_klines.extend(day_customs)

        return custom_klines

    @staticmethod
    def _group_klines_by_day(klines: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Группировка свечей по дням UTC"""
        daily_groups = []
        current_day_klines = []
        current_day = None

        for kline in klines:
            kline_dt = datetime.fromtimestamp(kline['timestamp'] / 1000, tz=timezone.utc)
            kline_day = kline_dt.date()

            if current_day is None:
                current_day = kline_day

            if kline_day != current_day:
                # Новый день - сохраняем предыдущий
                if current_day_klines:
                    daily_groups.append(current_day_klines)
                current_day_klines = [kline]
                current_day = kline_day
            else:
                current_day_klines.append(kline)

        # Добавляем последний день
        if current_day_klines:
            daily_groups.append(current_day_klines)

        return daily_groups

    @staticmethod
    def _build_day_custom_klines(day_klines: List[Dict[str, Any]], custom_minutes: int) -> List[Dict[str, Any]]:
        """Построение кастомных свечей для одного дня"""
        if not day_klines:
            return []

        custom_klines = []

        # Получаем расписание свечей для этого дня
        first_kline_dt = datetime.fromtimestamp(day_klines[0]['timestamp'] / 1000, tz=timezone.utc)
        day_start = first_kline_dt.replace(hour=0, minute=0, second=0, microsecond=0)

        schedule = []
        current_time = day_start
        day_end = day_start + timedelta(days=1)

        while current_time < day_end:
            schedule.append(current_time)
            next_time = current_time + timedelta(minutes=custom_minutes)
            if next_time >= day_end:
                break
            current_time = next_time

        # Индекс текущей свечи в расписании
        schedule_index = 0
        current_batch = []

        for kline in day_klines:
            kline_dt = datetime.fromtimestamp(kline['timestamp'] / 1000, tz=timezone.utc)

            # Найдем к какой кастомной свече относится эта базовая свеча
            while schedule_index < len(schedule) - 1:
                current_schedule_time = schedule[schedule_index]
                next_schedule_time = schedule[schedule_index + 1] if schedule_index + 1 < len(schedule) else day_end

                if current_schedule_time <= kline_dt < next_schedule_time:
                    current_batch.append(kline)
                    break
                else:
                    # Завершаем текущую кастомную свечу
                    if current_batch:
                        merged = BinanceClient._merge_klines(current_batch)
                        if merged:
                            custom_klines.append(merged)
                        current_batch = []
                    schedule_index += 1
            else:
                # Последняя свеча дня (может быть короче)
                current_batch.append(kline)

        # Завершаем последнюю свечу дня
        if current_batch:
            merged = BinanceClient._merge_klines(current_batch)
            if merged:
                custom_klines.append(merged)

        return custom_klines

    async def start_kline_stream(self, symbol: str, interval: str, callback: Callable[[Dict[str, Any]], None]):
        """
        Запуск WebSocket потока для получения закрытых свечей
        Поддерживает кастомные таймфреймы
        """
        try:
            if self._is_custom_timeframe(interval):
                await self._start_custom_kline_stream(symbol, interval, callback)
            else:
                await self._start_standard_kline_stream(symbol, interval, callback)

        except Exception as e:
            logger.error(f"Ошибка запуска потока свечей {symbol} {interval}: {e}")

    async def _start_standard_kline_stream(self, symbol: str, interval: str, callback: Callable):
        """Запуск стандартного потока свечей"""
        binance_interval = self._convert_timeframe(interval)
        stream_name = f"{symbol.lower()}@kline_{binance_interval}"

        self.ws_callbacks[stream_name] = callback

        if not self.is_ws_running:
            await self._start_websocket()

        await self._subscribe_stream(stream_name)
        logger.info(f"Запущен стандартный поток свечей: {stream_name}")

    async def _start_custom_kline_stream(self, symbol: str, interval: str, callback: Callable):
        """Запуск кастомного потока свечей"""
        config = self.custom_timeframes[interval]
        base_interval = config['base']

        # Создаем ключ для кеша
        cache_key = f"{symbol}_{interval}"
        self.custom_klines_cache[cache_key] = []

        # Создаем обертку для callback
        async def custom_callback(base_kline: Dict[str, Any]):
            await self._process_custom_kline(cache_key, base_kline, interval, callback)

        # Запускаем поток базовых свечей
        await self._start_standard_kline_stream(symbol, base_interval, custom_callback)
        logger.info(f"Запущен кастомный поток свечей: {symbol} {interval} (базовый: {base_interval})")

    async def _process_custom_kline(self, cache_key: str, base_kline: Dict[str, Any],
                                    custom_interval: str, callback: Callable):
        """Обработка базовой свечи для формирования кастомной"""
        try:
            # Добавляем базовую свечу в кеш
            self.custom_klines_cache[cache_key].append(base_kline)

            # Проверяем нужно ли формировать кастомную свечу
            custom_kline = self._check_custom_kline_completion(cache_key, custom_interval)

            if custom_kline:
                # Вызываем callback с кастомной свечей
                if asyncio.iscoroutinefunction(callback):
                    await callback(custom_kline)
                else:
                    callback(custom_kline)

        except Exception as e:
            logger.error(f"Ошибка обработки кастомной свечи {cache_key}: {e}")

    def _check_custom_kline_completion(self, cache_key: str, custom_interval: str) -> Optional[Dict[str, Any]]:
        """Проверка завершения кастомной свечи"""
        cached_klines = self.custom_klines_cache.get(cache_key, [])
        if not cached_klines:
            return None

        config = self.custom_timeframes[custom_interval]
        count = config['count']

        # Проверяем количество накопленных свечей
        if len(cached_klines) >= count:
            # Формируем кастомную свечу
            custom_kline = self._merge_klines(cached_klines[:count])

            # Удаляем использованные свечи из кеша
            self.custom_klines_cache[cache_key] = cached_klines[count:]

            return custom_kline

        # Проверяем сброс по времени (новый день)
        last_kline = cached_klines[-1]
        last_dt = datetime.fromtimestamp(last_kline['timestamp'] / 1000, tz=timezone.utc)

        # Если наступил новый день - формируем свечу из накопленного
        if last_dt.hour == 0 and last_dt.minute == 0 and len(cached_klines) > 0:
            custom_kline = self._merge_klines(cached_klines)
            self.custom_klines_cache[cache_key] = []
            return custom_kline

        return None

    async def _start_websocket(self):
        """Запуск WebSocket соединения"""
        try:
            self.ws_connection = await websockets.asyncio.client.connect(self.ws_url)
            self.is_ws_running = True

            asyncio.create_task(self._handle_websocket_messages())
            logger.info("WebSocket соединение установлено")

        except Exception as e:
            logger.error(f"Ошибка установки WebSocket соединения: {e}")
            self.is_ws_running = False

    async def _subscribe_stream(self, stream_name: str):
        """Подписка на WebSocket поток"""
        try:
            if not self.ws_connection:
                raise Exception("WebSocket соединение не установлено")

            subscribe_message = {
                "method": "SUBSCRIBE",
                "params": [stream_name],
                "id": 1
            }

            await self.ws_connection.send(json.dumps(subscribe_message))
            logger.info(f"Подписались на поток: {stream_name}")

        except Exception as e:
            logger.error(f"Ошибка подписки на поток {stream_name}: {e}")

    async def _handle_websocket_messages(self):
        """Обработка WebSocket сообщений"""
        try:
            while self.is_ws_running and self.ws_connection:
                try:
                    message = await asyncio.wait_for(self.ws_connection.recv(), timeout=30.0)
                    data = json.loads(message)

                    if 'k' in data:
                        await self._process_kline_message(data)

                except asyncio.TimeoutError:
                    if self.ws_connection:
                        await self.ws_connection.ping()

                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket соединение закрыто")
                    break

        except Exception as e:
            logger.error(f"Ошибка обработки WebSocket сообщений: {e}")
        finally:
            self.is_ws_running = False

    async def _process_kline_message(self, data: Dict[str, Any]):
        """Обработка сообщения с данными свечи"""
        try:
            kline_data = data['k']

            # Обрабатываем только закрытые свечи
            if not kline_data['x']:
                return

            symbol = kline_data['s']
            interval = kline_data['i']
            stream_name = f"{symbol.lower()}@kline_{interval}"

            kline = {
                'symbol': symbol,
                'interval': interval,
                'timestamp': int(kline_data['t']),
                'open': float(kline_data['o']),
                'high': float(kline_data['h']),
                'low': float(kline_data['l']),
                'close': float(kline_data['c']),
                'volume': float(kline_data['v']),
                'close_time': int(kline_data['T']),
                'is_closed': kline_data['x']
            }

            if stream_name in self.ws_callbacks:
                callback = self.ws_callbacks[stream_name]
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(kline)
                    else:
                        callback(kline)
                except Exception as e:
                    logger.error(f"Ошибка в callback для {stream_name}: {e}")

        except Exception as e:
            logger.error(f"Ошибка обработки kline сообщения: {e}")

    async def stop_kline_stream(self, symbol: str, interval: str):
        """Остановка потока свечей"""
        try:
            if self._is_custom_timeframe(interval):
                # Для кастомного таймфрейма останавливаем базовый поток
                base_interval = self.custom_timeframes[interval]['base']
                binance_interval = self._convert_timeframe(base_interval)

                # Очищаем кеш
                cache_key = f"{symbol}_{interval}"
                if cache_key in self.custom_klines_cache:
                    del self.custom_klines_cache[cache_key]
            else:
                binance_interval = self._convert_timeframe(interval)

            stream_name = f"{symbol.lower()}@kline_{binance_interval}"

            if self.ws_connection:
                unsubscribe_message = {
                    "method": "UNSUBSCRIBE",
                    "params": [stream_name],
                    "id": 2
                }
                await self.ws_connection.send(json.dumps(unsubscribe_message))

            if stream_name in self.ws_callbacks:
                del self.ws_callbacks[stream_name]

            logger.info(f"Остановлен поток свечей: {stream_name}")

        except Exception as e:
            logger.error(f"Ошибка остановки потока {symbol} {interval}: {e}")

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Получение информации о торговой паре"""
        try:
            response = await self._make_request('/fapi/v1/exchangeInfo')

            for symbol_info in response.get('symbols', []):
                if symbol_info['symbol'] == symbol:
                    return {
                        'symbol': symbol_info['symbol'],
                        'status': symbol_info['status'],
                        'base_asset': symbol_info['baseAsset'],
                        'quote_asset': symbol_info['quoteAsset'],
                        'price_precision': symbol_info['pricePrecision'],
                        'quantity_precision': symbol_info['quantityPrecision']
                    }

            return {}

        except Exception as e:
            logger.error(f"Ошибка получения информации о {symbol}: {e}")
            return {}

    async def test_connection(self) -> bool:
        """Тест подключения к Binance API"""
        try:
            await self._make_request('/fapi/v1/ping')
            logger.info("Подключение к Binance API успешно")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Binance API: {e}")
            return False

    async def close(self):
        """Закрытие всех соединений"""
        try:
            self.is_ws_running = False
            if self.ws_connection:
                await self.ws_connection.close()
                self.ws_connection = None

            if self.session and not self.session.closed:
                await self.session.close()

            self.ws_callbacks.clear()
            self.custom_klines_cache.clear()
            logger.info("Binance клиент закрыт")

        except Exception as e:
            logger.error(f"Ошибка закрытия Binance клиента: {e}")


# Пример использования с кастомными таймфреймами
async def example_custom_kline_callback(kline: Dict[str, Any]) -> None:
    """Пример callback для кастомных свечей"""
    logger.info(f"Кастомная свеча {kline['symbol']}: "
                f"O:{kline['open']} H:{kline['high']} L:{kline['low']} C:{kline['close']} "
                f"V:{kline['volume']}")


__all__ = ['BinanceClient']
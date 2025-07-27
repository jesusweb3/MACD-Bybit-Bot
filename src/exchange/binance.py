# src/exchange/binance.py
import aiohttp
import asyncio
import json
import websockets.asyncio.client
import websockets.exceptions
from typing import Dict, Any, List, Optional, Callable

from ..utils.logger import logger


class BinanceClient:
    """Упрощенный клиент для Binance Futures API и WebSocket"""

    def __init__(self):
        self.base_url = "https://fapi.binance.com"
        self.ws_url = "wss://fstream.binance.com/ws"
        self.timeout = aiohttp.ClientTimeout(total=10)
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_connection: Optional[Any] = None
        self.ws_callbacks: Dict[str, Callable] = {}
        self.is_ws_running = False

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

    def _convert_timeframe(self, timeframe: str) -> str:
        """
        Конвертация таймфрейма в формат Binance
        УПРОЩЕНО: теперь только стандартные таймфреймы
        """
        timeframe_map = {
            '5m': '5m',
            '15m': '15m',
            '1h': '1h',
            '2h': '2h'
        }
        return timeframe_map.get(timeframe, timeframe)

    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Получение исторических свечей через REST API
        УПРОЩЕНО: только стандартные таймфреймы
        """
        try:
            binance_interval = self._convert_timeframe(interval)
            logger.info(f"Запрашиваем {limit} свечей {symbol} {binance_interval}")

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

            logger.info(f"Получено {len(klines)} свечей для {symbol}")
            return klines

        except Exception as e:
            logger.error(f"Ошибка получения свечей {symbol} {interval}: {e}")
            return []

    async def start_kline_stream(self, symbol: str, interval: str, callback: Callable[[Dict[str, Any]], None]):
        """
        Запуск WebSocket потока для получения закрытых свечей
        УПРОЩЕНО: только стандартные таймфреймы
        """
        try:
            binance_interval = self._convert_timeframe(interval)
            stream_name = f"{symbol.lower()}@kline_{binance_interval}"

            self.ws_callbacks[stream_name] = callback

            if not self.is_ws_running:
                await self._start_websocket()

            await self._subscribe_stream(stream_name)
            logger.info(f"Запущен поток свечей: {stream_name}")

        except Exception as e:
            logger.error(f"Ошибка запуска потока свечей {symbol} {interval}: {e}")

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
            logger.info("Binance клиент закрыт")

        except Exception as e:
            logger.error(f"Ошибка закрытия Binance клиента: {e}")


__all__ = ['BinanceClient']
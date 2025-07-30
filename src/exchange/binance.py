# src/exchange/binance.py
import aiohttp
import asyncio
import json
import websockets.asyncio.client
import websockets.exceptions
from typing import Dict, Any, List, Optional, Callable

from ..utils.logger import logger


class BinanceClient:
    """
    Binance Futures API и WebSocket клиент для real-time режима

    Изменения:
    - Оптимизация для работы с минутными данными
    - Улучшенная обработка WebSocket соединений
    - Поддержка real-time режима для MACD стратегий
    """

    def __init__(self):
        self.base_url = "https://fapi.binance.com"
        self.ws_url = "wss://fstream.binance.com/ws"
        self.timeout = aiohttp.ClientTimeout(total=15)  # Увеличили timeout для стабильности
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_connection: Optional[Any] = None
        self.ws_callbacks: Dict[str, Callable] = {}
        self.is_ws_running = False

        # Real-time статистика
        self.messages_received = 0
        self.connection_restarts = 0
        self.last_message_time: Optional[float] = None

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
        Теперь поддерживаем 1m для real-time режима
        """
        # Маппинг поддерживаемых таймфреймов
        timeframe_map = {
            '1m': '1m',  # Основной для real-time
            '5m': '5m',
            '15m': '15m'
        }

        converted = timeframe_map.get(timeframe, timeframe)

        if converted not in ['1m', '5m', '15m']:
            logger.warning(f"Неподдерживаемый таймфрейм: {timeframe}, используем 1m")
            return '1m'

        return converted

    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Получение исторических свечей через REST API
        Оптимизировано для real-time режима с поддержкой 1m
        """
        try:
            binance_interval = self._convert_timeframe(interval)
            logger.info(f"Запрашиваем {limit} свечей {symbol} {binance_interval} для real-time режима")

            params = {
                'symbol': symbol,
                'interval': binance_interval,
                'limit': min(limit, 1500)  # Binance лимит
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

            logger.info(f"✅ Получено {len(klines)} свечей для {symbol} (real-time режим)")
            return klines

        except Exception as e:
            logger.error(f"Ошибка получения свечей {symbol} {interval}: {e}")
            return []

    async def start_kline_stream(self, symbol: str, interval: str, callback: Callable[[Dict[str, Any]], None]):
        """
        Запуск WebSocket потока для получения real-time свечей
        Оптимизирован для минутных данных
        """
        try:
            binance_interval = self._convert_timeframe(interval)
            stream_name = f"{symbol.lower()}@kline_{binance_interval}"

            self.ws_callbacks[stream_name] = callback

            if not self.is_ws_running:
                await self._start_websocket()

            await self._subscribe_stream(stream_name)
            logger.info(f"🚀 Запущен real-time поток: {stream_name}")

        except Exception as e:
            logger.error(f"Ошибка запуска real-time потока {symbol} {interval}: {e}")
            raise

    async def _start_websocket(self):
        """Запуск WebSocket соединения с улучшенной стабильностью"""
        try:
            logger.info("🔗 Устанавливаем WebSocket соединение для real-time режима...")

            self.ws_connection = await websockets.asyncio.client.connect(
                self.ws_url,
                ping_interval=20,  # Ping каждые 20 секунд
                ping_timeout=10,  # Timeout для ping
                close_timeout=10  # Timeout для закрытия
            )

            self.is_ws_running = True
            logger.info("✅ WebSocket соединение установлено")

            # Запускаем обработчик сообщений
            asyncio.create_task(self._handle_websocket_messages())

        except Exception as e:
            logger.error(f"❌ Ошибка установки WebSocket соединения: {e}")
            self.is_ws_running = False
            raise

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
            logger.info(f"📡 Подписались на real-time поток: {stream_name}")

        except Exception as e:
            logger.error(f"Ошибка подписки на поток {stream_name}: {e}")
            raise

    async def _handle_websocket_messages(self):
        """Обработка WebSocket сообщений с улучшенной стабильностью"""
        reconnect_attempts = 0
        max_reconnect_attempts = 5

        while self.is_ws_running:
            try:
                if not self.ws_connection:
                    logger.warning("WebSocket соединение потеряно, попытка переподключения...")
                    await self._reconnect_websocket()
                    reconnect_attempts += 1

                    if reconnect_attempts >= max_reconnect_attempts:
                        logger.error(
                            f"Превышено максимальное количество попыток переподключения ({max_reconnect_attempts})")
                        break

                    continue

                try:
                    # Ожидаем сообщение с timeout
                    message = await asyncio.wait_for(self.ws_connection.recv(), timeout=60.0)

                    # Сбрасываем счетчик при успешном получении сообщения
                    reconnect_attempts = 0
                    self.messages_received += 1
                    self.last_message_time = asyncio.get_event_loop().time()

                    data = json.loads(message)

                    # Обрабатываем данные свечей
                    if 'k' in data:
                        await self._process_kline_message(data)

                    # Логируем статистику каждые 100 сообщений
                    if self.messages_received % 100 == 0:
                        logger.debug(f"📊 Real-time статистика: {self.messages_received} сообщений получено")

                except asyncio.TimeoutError:
                    # Отправляем ping для проверки соединения
                    if self.ws_connection:
                        try:
                            await self.ws_connection.ping()
                            logger.debug("📡 WebSocket ping отправлен")
                        except:
                            logger.warning("WebSocket ping failed, соединение потеряно")
                            self.ws_connection = None

                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket соединение закрыто удаленной стороной")
                    self.ws_connection = None

                except json.JSONDecodeError as e:
                    logger.warning(f"Ошибка парсинга JSON сообщения: {e}")
                    continue

            except Exception as e:
                logger.error(f"Ошибка в цикле обработки WebSocket сообщений: {e}")
                await asyncio.sleep(5)  # Пауза перед следующей попыткой

        logger.info("WebSocket обработчик сообщений завершен")

    async def _reconnect_websocket(self):
        """Переподключение WebSocket с задержкой"""
        try:
            self.connection_restarts += 1
            logger.info(f"🔄 Переподключение WebSocket (попытка #{self.connection_restarts})...")

            # Небольшая задержка перед переподключением
            await asyncio.sleep(2)

            # Закрываем старое соединение если есть
            if self.ws_connection:
                try:
                    await self.ws_connection.close()
                except:
                    pass
                self.ws_connection = None

            # Устанавливаем новое соединение
            await self._start_websocket()

            # Переподписываемся на все потоки
            for stream_name in list(self.ws_callbacks.keys()):
                await self._subscribe_stream(stream_name)

            logger.info("✅ WebSocket переподключение успешно")

        except Exception as e:
            logger.error(f"❌ Ошибка переподключения WebSocket: {e}")

    async def _process_kline_message(self, data: Dict[str, Any]):
        """Обработка сообщения с данными свечи (оптимизировано для real-time)"""
        try:
            kline_data = data['k']

            # В real-time режиме обрабатываем только закрытые свечи
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

            # Логируем получение минутных свечей в debug режиме
            if interval == '1m':
                logger.debug(f"📊 Real-time 1m свеча: {symbol} цена={kline['close']}")

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

            logger.info(f"⏹️ Остановлен real-time поток: {stream_name}")

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
            logger.info("✅ Подключение к Binance API успешно (real-time режим)")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Binance API: {e}")
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики WebSocket соединения"""
        return {
            'messages_received': self.messages_received,
            'connection_restarts': self.connection_restarts,
            'is_connected': self.is_ws_running and self.ws_connection is not None,
            'active_streams': len(self.ws_callbacks),
            'last_message_time': self.last_message_time
        }

    async def close(self):
        """Закрытие всех соединений"""
        try:
            logger.info("🔒 Закрываем Binance клиент (real-time режим)...")

            self.is_ws_running = False

            if self.ws_connection:
                try:
                    await self.ws_connection.close()
                except:
                    pass
                self.ws_connection = None

            if self.session and not self.session.closed:
                await self.session.close()

            self.ws_callbacks.clear()

            # Логируем финальную статистику
            stats = self.get_statistics()
            logger.info(
                f"📊 Finalized stats: {stats['messages_received']} messages, {stats['connection_restarts']} reconnects")
            logger.info("✅ Binance клиент закрыт")

        except Exception as e:
            logger.error(f"Ошибка закрытия Binance клиента: {e}")


__all__ = ['BinanceClient']
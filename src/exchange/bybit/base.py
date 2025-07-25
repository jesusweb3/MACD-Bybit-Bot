# src/exchange/bybit/base.py
import aiohttp
import hashlib
import hmac
import json
import time
from typing import Dict, Optional, Any
from ...utils.logger import logger


class BybitBase:
    """Базовый класс для всех Bybit модулей"""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.bybit.com"
        self.timeout = aiohttp.ClientTimeout(total=10)
        self.session: Optional[aiohttp.ClientSession] = None
        self._server_time_offset = 0  # Добавляем offset для синхронизации

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Безопасное преобразование в float"""
        try:
            if value is None or value == '' or value == 'null':
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP сессии"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self.session

    async def _get_server_time_offset(self) -> None:
        """Получение offset серверного времени для синхронизации"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/v5/market/time"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('retCode') == 0:
                        server_time = int(data['result']['timeSecond']) * 1000
                        local_time = int(time.time() * 1000)
                        self._server_time_offset = server_time - local_time
                        logger.debug(f"Синхронизация времени: offset = {self._server_time_offset}ms")
                        return
                    else:
                        logger.debug(f"Bybit time API вернул ошибку: {data.get('retMsg', 'Unknown')}")
                else:
                    logger.debug(f"Ошибка HTTP при получении времени: {response.status}")
        except Exception as e:
            # Логируем только в debug режиме, чтобы не засорять логи
            logger.debug(f"Не удалось синхронизировать время с сервером: {e}")

        # Устанавливаем offset в 0 если синхронизация не удалась
        self._server_time_offset = 0

    def _get_synchronized_timestamp(self) -> str:
        """Получение синхронизированного timestamp"""
        local_time = int(time.time() * 1000)
        return str(local_time + self._server_time_offset)

    def _generate_signature(self, timestamp: str, params: str) -> str:
        """Генерация подписи для Bybit API"""
        recv_window = "10000"  # Увеличиваем окно до 10 секунд
        param_str = timestamp + self.api_key + recv_window + params
        return hmac.new(
            self.secret_key.encode('utf-8'),
            param_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _get_headers(self, params: str = "") -> Dict[str, str]:
        """Создание заголовков с подписью"""
        timestamp = self._get_synchronized_timestamp()
        signature = self._generate_signature(timestamp, params)

        return {
            'X-BAPI-API-KEY': self.api_key,
            'X-BAPI-SIGN': signature,
            'X-BAPI-SIGN-TYPE': '2',
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': '10000',  # Увеличиваем окно
            'Content-Type': 'application/json'
        }

    async def _make_request(
            self,
            method: str,
            endpoint: str,
            params: Optional[Dict[str, Any]] = None,
            retry_count: int = 0
    ) -> Dict[str, Any]:
        """Выполнение HTTP запроса к Bybit API с retry логикой"""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"

        if params is None:
            params = {}

        # Синхронизируем время при первом запросе или после ошибок времени
        if retry_count == 0 and self._server_time_offset == 0:
            await self._get_server_time_offset()

        try:
            if method.upper() == 'GET':
                query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                headers = self._get_headers(query_string)

                async with session.get(url, params=params, headers=headers) as response:
                    data: Dict[str, Any] = await response.json()

                    # Проверяем ошибки времени
                    if self._is_timestamp_error(data) and retry_count < 2:
                        logger.debug(f"Ошибка времени, пересинхронизация (попытка {retry_count + 1})")
                        await self._get_server_time_offset()
                        return await self._make_request(method, endpoint, params, retry_count + 1)

                    return data

            elif method.upper() == 'POST':
                json_data = json.dumps(params, separators=(',', ':'))
                headers = self._get_headers(json_data)

                async with session.post(url, data=json_data, headers=headers) as response:
                    data: Dict[str, Any] = await response.json()

                    # Проверяем ошибки времени
                    if self._is_timestamp_error(data) and retry_count < 2:
                        logger.debug(f"Ошибка времени, пересинхронизация (попытка {retry_count + 1})")
                        await self._get_server_time_offset()
                        return await self._make_request(method, endpoint, params, retry_count + 1)

                    return data

        except Exception as e:
            logger.error(f"Ошибка HTTP запроса {method} {endpoint}: {e}")
            raise

    def _is_timestamp_error(self, response: Dict[str, Any]) -> bool:
        """Проверка является ли ошибка связанной с временем"""
        if response.get('retCode') != 0:
            error_msg = response.get('retMsg', '').lower()
            return 'timestamp' in error_msg or 'recv_window' in error_msg
        return False

    @staticmethod
    def _check_response(response: Dict[str, Any]) -> None:
        """Проверка ответа API на ошибки"""
        if response.get('retCode') != 0:
            error_msg = response.get('retMsg', 'Unknown error')
            raise Exception(f"Bybit API error: {error_msg}")

    async def close(self):
        """Закрытие HTTP сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
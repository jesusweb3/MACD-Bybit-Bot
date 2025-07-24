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

    def _generate_signature(self, timestamp: str, params: str) -> str:
        """Генерация подписи для Bybit API"""
        param_str = timestamp + self.api_key + "5000" + params
        return hmac.new(
            self.secret_key.encode('utf-8'),
            param_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _get_headers(self, params: str = "") -> Dict[str, str]:
        """Создание заголовков с подписью"""
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, params)

        return {
            'X-BAPI-API-KEY': self.api_key,
            'X-BAPI-SIGN': signature,
            'X-BAPI-SIGN-TYPE': '2',
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': '5000',
            'Content-Type': 'application/json'
        }

    async def _make_request(
            self,
            method: str,
            endpoint: str,
            params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Выполнение HTTP запроса к Bybit API"""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"

        if params is None:
            params = {}

        try:
            if method.upper() == 'GET':
                query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                headers = self._get_headers(query_string)

                async with session.get(url, params=params, headers=headers) as response:
                    data: Dict[str, Any] = await response.json()
                    return data

            elif method.upper() == 'POST':
                json_data = json.dumps(params, separators=(',', ':'))
                headers = self._get_headers(json_data)

                async with session.post(url, data=json_data, headers=headers) as response:
                    data: Dict[str, Any] = await response.json()
                    return data

        except Exception as e:
            logger.error(f"Ошибка HTTP запроса {method} {endpoint}: {e}")
            raise

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
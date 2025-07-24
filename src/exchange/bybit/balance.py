# src/exchange/bybit/balance.py
from typing import Dict, Any
from .base import BybitBase
from ...utils.logger import logger


class BybitBalance(BybitBase):
    """Модуль для работы с балансом Bybit"""

    async def get_balance(self) -> Dict[str, Any]:
        """Получение баланса фьючерсного аккаунта"""
        try:
            logger.info("Запрашиваем баланс аккаунта")

            params = {'accountType': 'UNIFIED'}
            response = await self._make_request('GET', '/v5/account/wallet-balance', params)

            # Проверка ответа API
            BybitBase._check_response(response)

            # Парсинг баланса
            result = response.get('result', {})
            account_list = result.get('list', [])

            if not account_list:
                return {'total_usdt': 0.0, 'free_usdt': 0.0, 'used_usdt': 0.0}

            # Ищем USDT в первом аккаунте
            account = account_list[0]
            coins = account.get('coin', [])

            # Используем общий баланс аккаунта для USDT
            total_available = BybitBase._safe_float(account.get('totalAvailableBalance'))

            usdt_data = None
            for coin in coins:
                if coin.get('coin') == 'USDT':
                    usdt_data = coin
                    break

            if not usdt_data:
                return {'total_usdt': 0.0, 'free_usdt': 0.0, 'used_usdt': 0.0}

            # Используем правильные поля для USDT
            usdt_wallet = BybitBase._safe_float(usdt_data.get('walletBalance'))

            return {
                'total_usdt': usdt_wallet,
                'free_usdt': total_available,
                'used_usdt': usdt_wallet - total_available if usdt_wallet >= total_available else 0.0
            }

        except Exception as e:
            logger.error(f"Ошибка получения баланса: {e}")
            return {'total_usdt': 0.0, 'free_usdt': 0.0, 'used_usdt': 0.0}

    async def test_connection(self) -> bool:
        """Тест подключения к API через получение баланса"""
        try:
            await self.get_balance()
            logger.info("Подключение к Bybit API успешно")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Bybit API: {e}")
            return False
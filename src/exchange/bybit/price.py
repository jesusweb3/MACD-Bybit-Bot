# src/exchange/bybit/price.py
from typing import Dict, Any
from .base import BybitBase
from ...utils.logger import logger


class BybitPrice(BybitBase):
    """Модуль для получения цены"""

    async def get_price(self, symbol: str) -> Dict[str, Any]:
        """
        Получение текущей цены фьючерса
        """
        try:
            params = {
                'category': 'linear',
                'symbol': symbol
            }

            response = await self._make_request('GET', '/v5/market/tickers', params)

            BybitBase._check_response(response)

            result = response.get('result', {})
            tickers = result.get('list', [])

            if not tickers:
                return {
                    'success': False,
                    'error': f'Цена для {symbol} не найдена'
                }

            ticker = tickers[0]
            price = BybitBase._safe_float(ticker.get('lastPrice', 0))

            return {
                'success': True,
                'symbol': symbol,
                'price': price
            }

        except Exception as e:
            logger.error(f"Ошибка получения цены {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
# src/exchange/bybit/leverage.py
from typing import Dict, Any
from .base import BybitBase
from ...utils.logger import logger


class BybitLeverage(BybitBase):
    """Модуль для изменения кредитного плеча"""

    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """
        Изменение кредитного плеча для торговой пары
        """
        try:
            leverage_str = str(leverage)
            logger.info(f"Изменяем плечо для {symbol} на {leverage}x")

            params = {
                'category': 'linear',
                'symbol': symbol,
                'buyLeverage': leverage_str,
                'sellLeverage': leverage_str
            }

            response = await self._make_request('POST', '/v5/position/set-leverage', params)

            BybitBase._check_response(response)

            logger.info(f"Плечо успешно изменено для {symbol} на {leverage}x")
            return {
                'success': True,
                'symbol': symbol,
                'leverage': leverage
            }

        except Exception as e:
            error_msg = str(e)

            # Если плечо уже установлено - это успех
            if "leverage not modified" in error_msg.lower():
                logger.info(f"Плечо для {symbol} уже установлено на {leverage}x")
                return {
                    'success': True,
                    'symbol': symbol,
                    'leverage': leverage,
                    'already_set': True
                }

            logger.error(f"Ошибка изменения плеча для {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
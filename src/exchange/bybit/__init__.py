# src/exchange/bybit/__init__.py
from .balance import BybitBalance
from .leverage import BybitLeverage
from .price import BybitPrice
from .orders import BybitOrders
from .positions import BybitPositions


# Основной клиент объединяющий все модули
class BybitClient:
    """Главный клиент Bybit объединяющий все модули"""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key

        # Инициализируем модули
        self.balance = BybitBalance(api_key, secret_key)
        self.leverage = BybitLeverage(api_key, secret_key)
        self.price = BybitPrice(api_key, secret_key)
        self.orders = BybitOrders(api_key, secret_key)
        self.positions = BybitPositions(api_key, secret_key)

        from ...utils.logger import logger
        logger.info("Bybit клиент инициализирован для Mainnet")

    async def close(self):
        """Закрытие всех модулей"""
        await self.balance.close()
        await self.leverage.close()
        await self.price.close()
        await self.orders.close()
        await self.positions.close()


# Экспортируем для удобства
__all__ = ['BybitClient', 'BybitBalance', 'BybitLeverage', 'BybitPrice', 'BybitOrders', 'BybitPositions']
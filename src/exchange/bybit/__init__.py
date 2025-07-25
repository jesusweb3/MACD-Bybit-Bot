# src/exchange/bybit/__init__.py
import aiohttp
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

        # Общая HTTP сессия для всех модулей
        self._session: aiohttp.ClientSession = None

        # Инициализируем модули
        self.balance = BybitBalance(api_key, secret_key)
        self.leverage = BybitLeverage(api_key, secret_key)
        self.price = BybitPrice(api_key, secret_key)
        self.orders = BybitOrders(api_key, secret_key)
        self.positions = BybitPositions(api_key, secret_key)

        from ...utils.logger import logger
        logger.info("Bybit клиент инициализирован для Mainnet")

    async def _get_shared_session(self) -> aiohttp.ClientSession:
        """Получение общей HTTP сессии для всех модулей"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _ensure_modules_use_shared_session(self):
        """Убеждаемся что все модули используют общую сессию"""
        shared_session = await self._get_shared_session()

        # Закрываем индивидуальные сессии модулей если они есть
        modules = [self.balance, self.leverage, self.price, self.orders, self.positions]

        for module in modules:
            if hasattr(module, 'session') and module.session and not module.session.closed:
                await module.session.close()

            # Устанавливаем общую сессию
            module.session = shared_session

    async def __aenter__(self):
        """Async context manager entry"""
        await self._ensure_modules_use_shared_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def close(self):
        """Закрытие всех модулей и общей сессии"""
        try:
            # Сначала вызываем close() у всех модулей (но не закрываем сессии)
            modules = [self.balance, self.leverage, self.price, self.orders, self.positions]

            for module in modules:
                # Очищаем ссылку на сессию в модуле, чтобы избежать двойного закрытия
                if hasattr(module, 'session'):
                    module.session = None

            # Закрываем общую сессию только один раз
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

            from ...utils.logger import logger
            logger.debug("Bybit клиент корректно закрыт")

        except Exception as e:
            from ...utils.logger import logger
            logger.error(f"Ошибка при закрытии Bybit клиента: {e}")


# Экспортируем для удобства
__all__ = ['BybitClient', 'BybitBalance', 'BybitLeverage', 'BybitPrice', 'BybitOrders', 'BybitPositions']
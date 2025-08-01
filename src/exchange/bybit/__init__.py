# src/exchange/bybit/__init__.py
import aiohttp
from .balance import BybitBalance
from .leverage import BybitLeverage
from .price import BybitPrice
from .orders import BybitOrders
from .positions import BybitPositions
from .symbol_info import BybitSymbolInfo


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
        self.symbol_info = BybitSymbolInfo(api_key, secret_key)  # Новый модуль

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
        modules = [self.balance, self.leverage, self.price, self.orders, self.positions, self.symbol_info]

        for module in modules:
            # ИСПРАВЛЕНО: Реально закрываем индивидуальные сессии перед заменой
            if hasattr(module, 'session') and module.session and not module.session.closed:
                try:
                    await module.session.close()
                except Exception as e:
                    from ...utils.logger import logger
                    logger.debug(f"Ошибка закрытия индивидуальной сессии модуля: {e}")

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
            modules = [self.balance, self.leverage, self.price, self.orders, self.positions, self.symbol_info]

            # ИСПРАВЛЕНО: Правильное закрытие всех сессий
            for module in modules:
                if hasattr(module, 'session') and module.session:
                    try:
                        # Проверяем не закрыта ли уже сессия
                        if not module.session.closed:
                            await module.session.close()
                    except Exception as e:
                        from ...utils.logger import logger
                        logger.debug(f"Ошибка закрытия сессии модуля {module.__class__.__name__}: {e}")
                    finally:
                        # Обнуляем ссылку в любом случае
                        module.session = None

            # Закрываем общую сессию
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                except Exception as e:
                    from ...utils.logger import logger
                    logger.debug(f"Ошибка закрытия общей сессии Bybit: {e}")
                finally:
                    self._session = None

            from ...utils.logger import logger
            logger.debug("Bybit клиент корректно закрыт")

        except Exception as e:
            from ...utils.logger import logger
            logger.error(f"Ошибка при закрытии Bybit клиента: {e}")


# Экспортируем для удобства
__all__ = ['BybitClient', 'BybitBalance', 'BybitLeverage', 'BybitPrice', 'BybitOrders', 'BybitPositions', 'BybitSymbolInfo']
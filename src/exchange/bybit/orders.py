# src/exchange/bybit/orders.py
from typing import Dict, Any
from .base import BybitBase
from ...utils.logger import logger


class BybitOrders(BybitBase):
    """Модуль для размещения маркет ордеров"""

    async def place_market_order(self, symbol: str, side: str, qty: str,
                                 take_profit: float = None, stop_loss: float = None) -> Dict[str, Any]:
        """
        Размещение маркет ордера с опциональными TP/SL
        """
        try:
            tp_sl_info = ""
            if take_profit:
                tp_sl_info += f" TP={take_profit}"
            if stop_loss:
                tp_sl_info += f" SL={stop_loss}"

            logger.info(f"Размещаем маркет ордер {side} {qty} {symbol}{tp_sl_info}")

            params = {
                'category': 'linear',
                'symbol': symbol,
                'side': side,
                'orderType': 'Market',
                'qty': qty
            }

            # Добавляем TP/SL если указаны
            if take_profit:
                params['takeProfit'] = str(take_profit)
            if stop_loss:
                params['stopLoss'] = str(stop_loss)

            response = await self._make_request('POST', '/v5/order/create', params)

            BybitBase._check_response(response)

            result = response.get('result', {})
            order_id = result.get('orderId')
            order_link_id = result.get('orderLinkId')

            logger.info(f"Маркет ордер размещен: {order_id}")

            return {
                'success': True,
                'order_id': order_id,
                'order_link_id': order_link_id,
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'take_profit': take_profit,
                'stop_loss': stop_loss
            }

        except Exception as e:
            logger.error(f"Ошибка размещения маркет ордера {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def buy_market(self, symbol: str, qty: str, take_profit: float = None, stop_loss: float = None) -> Dict[
        str, Any]:
        """
        Маркет покупка с опциональными TP/SL
        """
        return await self.place_market_order(symbol, "Buy", qty, take_profit, stop_loss)

    async def sell_market(self, symbol: str, qty: str, take_profit: float = None, stop_loss: float = None) -> Dict[
        str, Any]:
        """
        Маркет продажа с опциональными TP/SL

        Args:
            symbol: Торговая пара
            qty: Количество
            take_profit: Цена тейк-профита
            stop_loss: Цена стоп-лосса
        """
        return await self.place_market_order(symbol, "Sell", qty, take_profit, stop_loss)

    async def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        Проверка статуса ордера
        """
        try:
            params = {
                'category': 'linear',
                'symbol': symbol,
                'orderId': order_id
            }

            response = await self._make_request('GET', '/v5/order/realtime', params)

            BybitBase._check_response(response)

            result = response.get('result', {})
            orders = result.get('list', [])

            if not orders:
                return {
                    'success': False,
                    'error': f'Ордер {order_id} не найден'
                }

            order = orders[0]

            return {
                'success': True,
                'order_id': order.get('orderId'),
                'status': order.get('orderStatus'),
                'side': order.get('side'),
                'qty': order.get('qty'),
                'cum_exec_qty': order.get('cumExecQty'),  # Исполненное количество
                'avg_price': BybitBase._safe_float(order.get('avgPrice', 0))
            }

        except Exception as e:
            logger.error(f"Ошибка получения статуса ордера {order_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
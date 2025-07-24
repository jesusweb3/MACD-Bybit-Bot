# src/exchange/bybit/positions.py
from typing import Dict, Any, List
from .base import BybitBase
from ...utils.logger import logger


class BybitPositions(BybitBase):
    """Модуль для управления позициями"""

    async def get_positions(self, symbol: str = None) -> Dict[str, Any]:
        """
        Получение открытых позиций
        """
        try:
            params = {'category': 'linear'}

            if symbol:
                params['symbol'] = symbol
            else:
                # Для получения всех позиций нужен settleCoin
                params['settleCoin'] = 'USDT'

            response = await self._make_request('GET', '/v5/position/list', params)

            BybitBase._check_response(response)

            result = response.get('result', {})
            positions = result.get('list', [])

            # Фильтруем только открытые позиции
            open_positions = []
            for pos in positions:
                size = BybitBase._safe_float(pos.get('size', 0))
                if size > 0:  # Позиция открыта
                    open_positions.append({
                        'symbol': pos.get('symbol'),
                        'side': pos.get('side'),
                        'size': size,
                        'entry_price': BybitBase._safe_float(pos.get('avgPrice', 0)),
                        'mark_price': BybitBase._safe_float(pos.get('markPrice', 0)),
                        'unrealized_pnl': BybitBase._safe_float(pos.get('unrealisedPnl', 0)),
                        'leverage': BybitBase._safe_float(pos.get('leverage', 0)),
                        'take_profit': BybitBase._safe_float(pos.get('takeProfit', 0)),
                        'stop_loss': BybitBase._safe_float(pos.get('stopLoss', 0))
                    })

            return {
                'success': True,
                'positions': open_positions,
                'count': len(open_positions)
            }

        except Exception as e:
            logger.error(f"Ошибка получения позиций: {e}")
            return {
                'success': False,
                'error': str(e),
                'positions': []
            }

    async def close_position(self, symbol: str) -> Dict[str, Any]:
        """
        Закрытие позиции маркет ордером
        """
        try:
            # Сначала получаем информацию о позиции
            positions_result = await self.get_positions(symbol)

            if not positions_result['success']:
                return {
                    'success': False,
                    'error': 'Не удалось получить позицию'
                }

            if not positions_result['positions']:
                return {
                    'success': False,
                    'error': f'Открытая позиция для {symbol} не найдена'
                }

            position = positions_result['positions'][0]

            # Определяем направление закрытия (противоположное текущей позиции)
            current_side = position['side']
            close_side = "Sell" if current_side == "Buy" else "Buy"
            position_size = str(position['size'])

            logger.info(f"Закрываем позицию {symbol}: {current_side} {position_size}")

            # Размещаем маркет ордер на закрытие
            params = {
                'category': 'linear',
                'symbol': symbol,
                'side': close_side,
                'orderType': 'Market',
                'qty': position_size,
                'reduceOnly': True  # Только для закрытия позиции
            }

            response = await self._make_request('POST', '/v5/order/create', params)

            BybitBase._check_response(response)

            result = response.get('result', {})
            order_id = result.get('orderId')

            logger.info(f"Ордер на закрытие размещен: {order_id}")

            return {
                'success': True,
                'order_id': order_id,
                'symbol': symbol,
                'closed_side': current_side,
                'closed_size': position_size
            }

        except Exception as e:
            logger.error(f"Ошибка закрытия позиции {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def has_open_position(self, symbol: str) -> bool:
        """
        Проверка наличия открытой позиции
        """
        try:
            result = await self.get_positions(symbol)
            return result['success'] and result['count'] > 0
        except:
            return False

    async def get_position_pnl(self, symbol: str) -> Dict[str, Any]:
        """
        Получение P&L по позиции
        """
        try:
            result = await self.get_positions(symbol)

            if not result['success'] or not result['positions']:
                return {
                    'success': False,
                    'error': f'Позиция {symbol} не найдена'
                }

            position = result['positions'][0]

            return {
                'success': True,
                'symbol': symbol,
                'unrealized_pnl': position['unrealized_pnl'],
                'entry_price': position['entry_price'],
                'mark_price': position['mark_price'],
                'size': position['size'],
                'side': position['side']
            }

        except Exception as e:
            logger.error(f"Ошибка получения P&L для {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
# src/exchange/bybit/symbol_info.py
from typing import Dict, Any, Optional
from .base import BybitBase
from ...utils.logger import logger


class BybitSymbolInfo(BybitBase):
    """Модуль для получения информации о торговых символах"""

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """
        Получение полной информации о торговом символе
        """
        try:
            logger.info(f"Получаем информацию о символе {symbol}")

            params = {
                'category': 'linear',
                'symbol': symbol
            }

            response = await self._make_request('GET', '/v5/market/instruments-info', params)
            BybitBase._check_response(response)

            result = response.get('result', {})
            instruments = result.get('list', [])

            if not instruments:
                return {
                    'success': False,
                    'error': f'Символ {symbol} не найден'
                }

            instrument = instruments[0]

            # Извлекаем важную информацию о символе
            symbol_info = {
                'success': True,
                'symbol': instrument.get('symbol'),
                'status': instrument.get('status'),
                'base_coin': instrument.get('baseCoin'),
                'quote_coin': instrument.get('quoteCoin'),
                'price_scale': self._safe_float(instrument.get('priceScale')),
                'min_price': self._safe_float(instrument.get('priceFilter', {}).get('minPrice')),
                'max_price': self._safe_float(instrument.get('priceFilter', {}).get('maxPrice')),
                'tick_size': self._safe_float(instrument.get('priceFilter', {}).get('tickSize')),

                # Важно для количества
                'min_order_qty': self._safe_float(instrument.get('lotSizeFilter', {}).get('minOrderQty')),
                'max_order_qty': self._safe_float(instrument.get('lotSizeFilter', {}).get('maxOrderQty')),
                'qty_step': self._safe_float(instrument.get('lotSizeFilter', {}).get('qtyStep')),
                'post_only_max_order_qty': self._safe_float(
                    instrument.get('lotSizeFilter', {}).get('postOnlyMaxOrderQty')),

                # Дополнительная информация
                'leverage_filter': instrument.get('leverageFilter', {}),
                'unified_margin_trade': instrument.get('unifiedMarginTrade'),
                'funding_interval': instrument.get('fundingInterval'),
                'settle_coin': instrument.get('settleCoin')
            }

            # ИСПРАВЛЕНО: Объединенный лог вместо нескольких
            logger.info(f"✅ Информация о {symbol} получена: Минимальное количество: {symbol_info['min_order_qty']}, Шаг количества: {symbol_info['qty_step']}, Размер тика цены: {symbol_info['tick_size']}")

            return symbol_info

        except Exception as e:
            logger.error(f"Ошибка получения информации о символе {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def get_quantity_precision(self, symbol: str) -> Dict[str, Any]:
        """
        Получение точности количества для символа
        """
        try:
            symbol_info = await self.get_symbol_info(symbol)

            if not symbol_info['success']:
                return symbol_info

            min_qty = symbol_info['min_order_qty']
            qty_step = symbol_info['qty_step']

            # Определяем точность на основе шага
            precision = self._calculate_precision_from_step(qty_step)

            return {
                'success': True,
                'symbol': symbol,
                'min_qty': min_qty,
                'qty_step': qty_step,
                'precision': precision
            }

        except Exception as e:
            logger.error(f"Ошибка получения точности для {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _calculate_precision_from_step(self, step: float) -> int:
        """Вычисление количества знаков после запятой на основе шага"""
        if step >= 1:
            return 0

        # Преобразуем в строку и считаем знаки после запятой
        step_str = f"{step:.10f}".rstrip('0')
        if '.' not in step_str:
            return 0

        return len(step_str.split('.')[1])

    async def format_quantity_for_symbol(self, symbol: str, quantity: float) -> Dict[str, Any]:
        """
        Форматирование количества для конкретного символа на основе данных биржи
        """
        try:
            # Получаем реальные данные от биржи
            precision_info = await self.get_quantity_precision(symbol)

            if not precision_info['success']:
                return precision_info

            min_qty = precision_info['min_qty']
            qty_step = precision_info['qty_step']
            precision = precision_info['precision']

            # Округляем до нужной точности
            rounded_qty = round(quantity, precision)

            # Проверяем минимальное количество
            if rounded_qty < min_qty:
                logger.warning(f"⚠️ Количество {rounded_qty} меньше минимального {min_qty}, устанавливаем минимум")
                rounded_qty = min_qty

            # Округляем до ближайшего шага
            if qty_step > 0:
                rounded_qty = round(rounded_qty / qty_step) * qty_step
                # Повторно округляем до точности после операции с шагом
                rounded_qty = round(rounded_qty, precision)

            # Форматируем как строку
            if precision == 0:
                formatted = str(int(rounded_qty))
            else:
                formatted = f"{rounded_qty:.{precision}f}"
                # Убираем лишние нули справа, но оставляем минимум нужной точности
                formatted = formatted.rstrip('0').rstrip('.')
                if not formatted or formatted == '.' or float(formatted) < min_qty:
                    formatted = f"{min_qty:.{precision}f}"

            return {
                'success': True,
                'symbol': symbol,
                'original_quantity': quantity,
                'formatted_quantity': formatted,
                'min_qty': min_qty,
                'qty_step': qty_step,
                'precision': precision
            }

        except Exception as e:
            logger.error(f"Ошибка форматирования количества для {symbol}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def get_all_linear_symbols(self) -> Dict[str, Any]:
        """
        Получение списка всех доступных линейных символов
        """
        try:
            logger.info("Получаем список всех линейных символов")

            params = {
                'category': 'linear'
            }

            response = await self._make_request('GET', '/v5/market/instruments-info', params)
            BybitBase._check_response(response)

            result = response.get('result', {})
            instruments = result.get('list', [])

            symbols = []
            for instrument in instruments:
                if instrument.get('status') == 'Trading':  # Только активные для торговли
                    symbols.append({
                        'symbol': instrument.get('symbol'),
                        'base_coin': instrument.get('baseCoin'),
                        'quote_coin': instrument.get('quoteCoin'),
                        'min_order_qty': self._safe_float(instrument.get('lotSizeFilter', {}).get('minOrderQty')),
                        'qty_step': self._safe_float(instrument.get('lotSizeFilter', {}).get('qtyStep')),
                    })

            logger.info(f"✅ Найдено {len(symbols)} активных символов")

            return {
                'success': True,
                'symbols': symbols,
                'count': len(symbols)
            }

        except Exception as e:
            logger.error(f"Ошибка получения списка символов: {e}")
            return {
                'success': False,
                'error': str(e)
            }
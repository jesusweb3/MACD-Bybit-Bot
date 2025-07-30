# src/bot/utils/trade_utils.py
from typing import Dict, Any
from ...database.database import db
from ...utils.logger import logger
from ...exchange.bybit import BybitClient


class TradeBotStatus:
    """Статусы торгового бота"""
    WAITING = "waiting"  # Ожидает запуска
    TRADING = "trading"  # Активная торговля
    STOPPED = "stopped"  # Остановлен
    ERROR = "error"  # Ошибка


class TradeBotUtils:
    """Утилиты для торгового бота"""

    @staticmethod
    def check_settings_completeness(telegram_id: int) -> Dict[str, Any]:
        """
        Проверка полноты настроек пользователя

        Returns:
            Dict с информацией о настройках
        """
        user_settings = db.get_user_settings(telegram_id)

        if not user_settings:
            return {
                'complete': False,
                'missing_count': 8,
                'total_count': 8,
                'missing_settings': [
                    'API ключи', 'Торговая пара', 'Плечо', 'Размер позиции',
                    'TP/SL', 'ТФ входа', 'ТФ выхода', 'Время работы'
                ]
            }

        missing_settings = []

        # Проверяем API ключи
        if not (user_settings.get('bybit_api_key') and user_settings.get('bybit_secret_key')):
            missing_settings.append('API ключи')

        # Проверяем торговую пару
        if not user_settings.get('trading_pair'):
            missing_settings.append('Торговая пара')

        # Проверяем плечо
        if not user_settings.get('leverage'):
            missing_settings.append('Плечо')

        # Проверяем размер позиции
        position_size_info = db.get_position_size_info(telegram_id)
        if not position_size_info.get('value') or position_size_info.get('value') <= 0:
            missing_settings.append('Размер позиции')

        # Проверяем TP/SL (опционально, но если включено - должно быть настроено)
        tp_sl_info = db.get_tp_sl_info(telegram_id)
        if tp_sl_info['enabled'] and not (tp_sl_info['take_profit'] and tp_sl_info['stop_loss']):
            missing_settings.append('TP/SL')

        # Проверяем таймфреймы - ТОЛЬКО 5m и 45m
        entry_tf = user_settings.get('entry_timeframe')
        if not entry_tf or entry_tf not in ['5m', '45m']:
            missing_settings.append('ТФ входа')

        exit_tf = user_settings.get('exit_timeframe')
        if not exit_tf or exit_tf not in ['5m', '45m']:
            missing_settings.append('ТФ выхода')

        # Проверяем время работы
        if not user_settings.get('bot_duration_hours'):
            missing_settings.append('Время работы')

        total_count = 8
        missing_count = len(missing_settings)
        complete = missing_count == 0

        return {
            'complete': complete,
            'missing_count': missing_count,
            'total_count': total_count,
            'missing_settings': missing_settings,
            'progress': total_count - missing_count
        }

    @staticmethod
    def get_trade_menu_text(telegram_id: int) -> str:
        """Генерация текста для главного торгового меню"""
        from ...strategies import strategy_manager

        # Проверяем настройки
        settings_info = TradeBotUtils.check_settings_completeness(telegram_id)

        # Проверяем активную стратегию
        is_strategy_active = strategy_manager.is_strategy_active(telegram_id)

        if is_strategy_active:
            # Если стратегия активна - показываем красивый статус
            strategy_status = strategy_manager.get_strategy_status(telegram_id)
            strategy_name = strategy_status.get('strategy_name', 'Unknown')
            position_state = strategy_status.get('position_state', 'Unknown')

            # Получаем настройки пользователя для отображения
            user_settings = db.get_user_settings(telegram_id)
            trading_pair = user_settings.get('trading_pair', 'Unknown') if user_settings else 'Unknown'
            leverage = user_settings.get('leverage', 'Unknown') if user_settings else 'Unknown'
            entry_tf = user_settings.get('entry_timeframe', 'Unknown') if user_settings else 'Unknown'
            exit_tf = user_settings.get('exit_timeframe', 'Unknown') if user_settings else 'Unknown'

            # Размер позиции
            position_size_info = db.get_position_size_info(telegram_id)
            position_size = position_size_info.get('display', 'Unknown')

            # TP/SL статус
            tp_sl_info = db.get_tp_sl_info(telegram_id)
            tp_sl_status = tp_sl_info.get('display', 'Unknown')

            # Красивое название стратегии
            strategy_display_names = {
                'macd_full': 'MACD Full (Long + Short)',
                'macd_long': 'MACD Long Only',
                'macd_short': 'MACD Short Only'
            }
            strategy_display = strategy_display_names.get(strategy_name, strategy_name)

            # Статус позиции с эмодзи
            position_display = {
                'no_position': 'Ожидание сигнала',
                'long_position': 'LONG позиция',
                'short_position': 'SHORT позиция'
            }.get(position_state, position_state)

            text = (
                f"🤖 <b>Торговый бот MACD</b>\n\n"
                f"📊 <b>Статус:</b> 🚀 Стратегия запущена!\n\n"
                f"🎯 <b>Стратегия:</b> {strategy_display}\n"
                f"💰 <b>Пара:</b> {trading_pair}\n"
                f"⚡ <b>Плечо:</b> {leverage}x\n"
                f"📊 <b>Размер:</b> {position_size}\n"
                f"⚙️ <b>TP/SL:</b> {tp_sl_status}\n"
                f"⏱️ <b>Вход:</b> {entry_tf} | <b>Выход:</b> {exit_tf}"
            )

        else:
            # Если стратегия не активна - показываем статус настроек
            if settings_info['complete']:
                settings_status = "✅ Настройки завершены"
                settings_emoji = "🟢"
                bot_status = "⏳ Ожидает запуска"
            else:
                settings_status = f"❌ Не завершены ({settings_info['progress']}/{settings_info['total_count']})"
                settings_emoji = "🔴"
                bot_status = "⚙️ Ожидает настройки"

            text = (
                f"🤖 <b>Торговый бот MACD</b>\n\n"
                f"📊 <b>Статус:</b> {bot_status}\n"
                f"{settings_emoji} <b>Настройки:</b> {settings_status}\n\n"
            )

            if settings_info['complete']:
                # Когда настройки завершены - показываем сообщение о готовности
                text += f"🎯 <b>Готов к торговле!</b> Выберите стратегию для запуска."
            else:
                # Когда настройки не завершены - показываем что нужно доделать
                text += (
                    f"⚠️ <b>Завершите настройки:</b> "
                )

                # Показываем первые 3 недостающие настройки
                missing_short = settings_info['missing_settings'][:3]
                text += ", ".join(missing_short)

                if len(settings_info['missing_settings']) > 3:
                    remaining = len(settings_info['missing_settings']) - 3
                    text += f" и ещё {remaining}"

        return text

    @staticmethod
    def get_strategy_menu_text() -> str:
        """Текст меню выбора стратегии"""
        from ...strategies import strategy_manager

        available = strategy_manager.get_available_strategies()
        active_count = strategy_manager.get_active_strategies_count()

        text = f"🎯 <b>Выбор стратегии MACD</b>\n\n"

        if active_count > 0:
            text += f"⚠️ <i>Активных стратегий: {active_count}</i>\n\n"

        text += "💡 Доступные стратегии:\n"
        text += f"{'✅' if available.get('macd_full') else '🚧'} MACD Full - всегда в позиции\n"
        text += f"{'✅' if available.get('macd_long') else '🚧'} MACD Long - только покупки\n"
        text += f"{'✅' if available.get('macd_short') else '🚧'} MACD Short - только продажи\n\n"
        text += "🔽 <b>Выберите стратегию для запуска:</b>"

        return text

    @staticmethod
    def get_strategy_confirm_text(strategy_name: str, telegram_id: int) -> str:
        """Текст подтверждения выбранной стратегии"""
        from ...strategies import strategy_manager

        strategy_names = {
            'macd_full': 'MACD Full (Long + Short)',
            'macd_long': 'MACD Long Only',
            'macd_short': 'MACD Short Only'
        }

        strategy_display = strategy_names.get(strategy_name, strategy_name)

        # Получаем настройки пользователя
        user_settings = db.get_user_settings(telegram_id)

        if not user_settings:
            return "❌ Ошибка: настройки не найдены"

        # Информация о настройках
        trading_pair = user_settings.get('trading_pair', 'Не установлена')
        leverage = user_settings.get('leverage', 'Не установлено')
        entry_tf = user_settings.get('entry_timeframe', 'Не установлен')
        exit_tf = user_settings.get('exit_timeframe', 'Не установлен')
        duration = user_settings.get('bot_duration_hours', 'Не установлено')

        # Размер позиции
        position_size_info = db.get_position_size_info(telegram_id)
        position_size = position_size_info.get('display', 'Не установлен')

        # TP/SL
        tp_sl_info = db.get_tp_sl_info(telegram_id)
        tp_sl_status = tp_sl_info.get('display', 'Не настроено')

        # Проверяем доступность стратегии
        available_strategies = strategy_manager.get_available_strategies()
        is_available = available_strategies.get(strategy_name, False)

        if not is_available:
            return (
                f"🚧 <b>Стратегия в разработке</b>\n\n"
                f"🎯 <b>Стратегия:</b> {strategy_display}\n\n"
                f"⚠️ <b>Эта стратегия еще не реализована</b>\n"
                f"📅 <i>Скоро будет доступна!</i>\n\n"
                f"💡 <i>Попробуйте MACD Full стратегию</i>"
            )

        text = (
            f"🚀 <b>Подтверждение запуска</b>\n\n"
            f"🎯 <b>Стратегия:</b> {strategy_display}\n\n"
            f"<b>📋 Параметры торговли:</b>\n"
            f"💰 Пара: {trading_pair}\n"
            f"⚡ Плечо: {leverage}x\n"
            f"📊 Размер: {position_size}\n"
            f"⚙️ TP/SL: {tp_sl_status}\n"
            f"⏱️ Вход: {entry_tf} | Выход: {exit_tf}\n"
            f"🕒 Работа: {duration}ч\n\n"
            f"❗ <b>Внимание:</b> После запуска бот будет торговать автоматически!\n"
            f"Убедитесь, что все параметры настроены корректно."
        )

        return text

    @staticmethod
    def get_statistics_text(telegram_id: int) -> str:
        """Текст статистики торговли с реальными данными"""
        from ...strategies import strategy_manager
        from datetime import datetime

        # Получаем историю сделок из БД
        trades = db.get_user_trades_history(telegram_id, limit=100)

        # Рассчитываем статистику
        total_trades = len(trades)
        total_pnl = 0.0
        profitable_trades = 0
        losing_trades = 0

        for trade in trades:
            if trade['status'] == 'closed' and trade['pnl'] is not None:
                total_pnl += trade['pnl']
                if trade['pnl'] > 0:
                    profitable_trades += 1
                elif trade['pnl'] < 0:
                    losing_trades += 1

        closed_trades = profitable_trades + losing_trades
        win_rate = (profitable_trades / closed_trades * 100) if closed_trades > 0 else 0

        # Получаем настройки пользователя для торговой пары
        user_settings = db.get_user_settings(telegram_id)
        trading_pair = user_settings.get('trading_pair') if user_settings else None

        # Проверяем активную стратегию и текущую позицию
        current_position = TradeBotUtils._get_current_position(telegram_id, trading_pair)

        # Статус стратегии
        is_active = strategy_manager.is_strategy_active(telegram_id)
        strategy_status_text = ""

        if is_active:
            strategy_status = strategy_manager.get_strategy_status(telegram_id)
            strategy_status_text = (
                f"\n🟢 <b>Активная стратегия:</b> {strategy_status.get('strategy_name', 'Unknown')}\n"
                f"📊 <b>Состояние:</b> {strategy_status.get('position_state', 'Unknown')}"
            )

        # Форматируем P&L с помощью helpers
        from ...utils.helpers import format_pnl, format_percentage
        pnl_formatted = format_pnl(total_pnl, with_currency=False)
        win_rate_formatted = format_percentage(win_rate, 1)

        # Время обновления
        update_time = datetime.now().strftime("%H:%M:%S")

        return (
            f"📊 <b>Статистика торговли</b>\n\n"
            f"{pnl_formatted} USDT\n"
            f"🔢 <b>Всего сделок:</b> {total_trades}\n"
            f"✅ <b>Закрытых сделок:</b> {closed_trades}\n"
            f"📈 <b>Прибыльных:</b> {profitable_trades} ({win_rate_formatted})\n"
            f"📉 <b>Убыточных:</b> {losing_trades}\n\n"
            f"📊 <b>Текущая позиция:</b> {current_position}"
            f"{strategy_status_text}\n\n"
            f"🔄 <i>Обновлено: {update_time}</i>"
        )

    @staticmethod
    def _get_current_position(telegram_id: int, trading_pair: str = None) -> str:
        """
        Получение текущей позиции пользователя

        Args:
            telegram_id: ID пользователя
            trading_pair: Торговая пара

        Returns:
            Строка с описанием позиции
        """
        from ...strategies import strategy_manager

        try:
            # Проверяем есть ли активная стратегия
            if strategy_manager.is_strategy_active(telegram_id):
                strategy_status = strategy_manager.get_strategy_status(telegram_id)
                position_state = strategy_status.get('position_state', 'Unknown')
                symbol = strategy_status.get('symbol', 'Unknown')

                if position_state == 'no_position':
                    return "нет"
                elif position_state == 'long_position':
                    return f"LONG {symbol}"
                elif position_state == 'short_position':
                    return f"SHORT {symbol}"
                else:
                    return f"{position_state} {symbol}"

            # Проверяем есть ли настройки API
            user_settings = db.get_user_settings(telegram_id)
            if not user_settings or not user_settings.get('bybit_api_key') or not user_settings.get('bybit_secret_key'):
                return "API ключи не настроены"

            if not trading_pair:
                return "торговая пара не установлена"

            # Если нет активной стратегии, но есть API - можем проверить позицию
            # В будущем здесь будет реальный запрос к Bybit API
            return "нет активной стратегии"

        except Exception as e:
            logger.error(f"Ошибка получения позиции для {telegram_id}: {e}")
            return "ошибка получения данных"

    @staticmethod
    def check_timeframes_for_full_strategy(telegram_id: int) -> bool:
        """
        Проверка одинаковых таймфреймов для MACD Full стратегии

        Returns:
            True если таймфреймы одинаковые, False если разные
        """
        user_settings = db.get_user_settings(telegram_id)
        if not user_settings:
            return False

        entry_tf = user_settings.get('entry_timeframe')
        exit_tf = user_settings.get('exit_timeframe')

        # Проверяем что оба таймфрейма поддерживаются
        if entry_tf not in ['5m', '45m'] or exit_tf not in ['5m', '45m']:
            return False

        return entry_tf == exit_tf and entry_tf is not None

    @staticmethod
    async def get_balance_text(telegram_id: int) -> str:
        """Получение реального баланса счёта через Bybit API"""
        from ...strategies import strategy_manager
        from datetime import datetime

        # Проверяем API настройки
        user_settings = db.get_user_settings(telegram_id)

        if not user_settings or not user_settings.get('bybit_api_key') or not user_settings.get('bybit_secret_key'):
            return (
                f"💰 <b>Баланс счёта Bybit</b>\n\n"
                f"❌ <b>API ключи не настроены</b>\n\n"
                f"🔧 <i>Настройте API ключи в разделе настроек\n"
                f"для отображения реального баланса</i>"
            )

        # Создаем Bybit клиент для получения баланса
        api_key = user_settings.get('bybit_api_key')
        secret_key = user_settings.get('bybit_secret_key')

        try:
            logger.info(f"Получение баланса для пользователя {telegram_id}")

            # Используем async context manager для правильного управления ресурсами
            async with BybitClient(api_key, secret_key) as bybit_client:
                # Получаем баланс
                balance_result = await bybit_client.balance.get_balance()

                # Форматируем результат
                total_usdt = balance_result.get('total_usdt', 0.0)
                free_usdt = balance_result.get('free_usdt', 0.0)
                used_usdt = balance_result.get('used_usdt', 0.0)

                # Эмодзи для баланса
                from ...utils.helpers import get_balance_emoji, format_balance
                balance_emoji = get_balance_emoji(total_usdt)

                # Форматируем числа
                total_formatted = format_balance(total_usdt)
                free_formatted = format_balance(free_usdt)
                used_formatted = format_balance(used_usdt)

                # Получаем информацию об активной стратегии
                strategy_text = ""
                is_active = strategy_manager.is_strategy_active(telegram_id)

                if is_active:
                    strategy_status = strategy_manager.get_strategy_status(telegram_id)
                    position_size_info = db.get_position_size_info(telegram_id)
                    position_size = position_size_info.get('display', 'Unknown')

                    strategy_text = (
                        f"\n🤖 <b>Активная стратегия:</b> {strategy_status.get('strategy_name', 'Unknown')}\n"
                        f"📊 <b>Размер позиции:</b> {position_size}\n"
                        f"🎯 <b>Состояние:</b> {strategy_status.get('position_state', 'Unknown')}"
                    )

                # Время обновления
                update_time = datetime.now().strftime("%H:%M:%S")

                result_text = (
                    f"💰 <b>Баланс счёта Bybit</b>\n\n"
                    f"{balance_emoji} <b>Общий баланс:</b> {total_formatted} USDT\n"
                    f"✅ <b>Доступно:</b> {free_formatted} USDT\n"
                    f"🔒 <b>В позициях:</b> {used_formatted} USDT\n\n"
                    f"🔄 <i>Обновлено: {update_time}</i>"
                    f"{strategy_text}"
                )

                logger.info(f"✅ Баланс получен для {telegram_id}: {total_formatted} USDT")
                return result_text

        except Exception as e:
            error_msg = str(e).lower()
            logger.error(f"❌ Ошибка получения баланса для {telegram_id}: {e}")

            # Определяем тип ошибки для пользователя
            if "api" in error_msg and ("key" in error_msg or "sign" in error_msg):
                error_text = (
                    f"💰 <b>Баланс счёта Bybit</b>\n\n"
                    f"🔑 <b>Ошибка API ключей</b>\n\n"
                    f"❌ Неверные API ключи или подпись\n"
                    f"🔧 Проверьте правильность ключей в настройках\n"
                    f"⚠️ Убедитесь, что ключи имеют права на чтение баланса"
                )
            elif "network" in error_msg or "connection" in error_msg or "timeout" in error_msg:
                error_text = (
                    f"💰 <b>Баланс счёта Bybit</b>\n\n"
                    f"🌐 <b>Ошибка подключения</b>\n\n"
                    f"❌ Не удалось подключиться к Bybit\n"
                    f"🔄 Попробуйте обновить баланс через несколько секунд"
                )
            else:
                error_text = (
                    f"💰 <b>Баланс счёта Bybit</b>\n\n"
                    f"⚠️ <b>Ошибка получения баланса</b>\n\n"
                    f"❌ {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}\n"
                    f"🔧 Проверьте настройки API ключей"
                )

            return error_text

    @staticmethod
    def get_active_strategy_info(telegram_id: int) -> Dict[str, Any]:
        """Получение информации об активной стратегии"""
        from ...strategies import strategy_manager

        if not strategy_manager.is_strategy_active(telegram_id):
            return {
                'is_active': False,
                'strategy_name': None,
                'message': 'Нет активной стратегии'
            }

        strategy_status = strategy_manager.get_strategy_status(telegram_id)

        return {
            'is_active': True,
            'strategy_name': strategy_status.get('strategy_name'),
            'position_state': strategy_status.get('position_state'),
            'symbol': strategy_status.get('symbol'),
            'position_size': strategy_status.get('position_size'),
            'status': strategy_status.get('status'),
            'start_time': strategy_status.get('start_time'),
            'strategy_id': strategy_status.get('strategy_id')
        }
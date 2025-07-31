# src/bot/utils/trade_utils.py
from typing import Dict, Any
from ...database.database import db
from ...utils.logger import logger
from ...utils.helpers import format_msk_time
from ...exchange.bybit import BybitClient


class TradeBotStatus:
    """Статусы торгового бота"""
    WAITING = "waiting"
    TRADING = "trading"
    STOPPED = "stopped"
    ERROR = "error"


class TradeBotUtils:
    """Утилиты для торгового бота с MACD Full стратегией"""

    @staticmethod
    def check_settings_completeness(telegram_id: int) -> Dict[str, Any]:
        """Проверка полноты настроек пользователя"""
        user_settings = db.get_user_settings(telegram_id)

        if not user_settings:
            return {
                'complete': False,
                'missing_count': 5,
                'total_count': 5,
                'missing_settings': [
                    'API ключи', 'Торговая пара', 'Плечо', 'Размер позиции', 'Таймфрейм'
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

        # Проверяем таймфрейм
        timeframe = user_settings.get('timeframe')
        if not timeframe or timeframe not in ['5m', '45m']:
            missing_settings.append('Таймфрейм')

        total_count = 5
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
        from ...strategy import strategy_manager

        # Проверяем настройки
        settings_info = TradeBotUtils.check_settings_completeness(telegram_id)

        # Проверяем активную стратегию
        is_strategy_active = strategy_manager.is_strategy_active(telegram_id)

        if is_strategy_active:
            # Если стратегия активна - показываем красивый статус
            strategy_status = strategy_manager.get_strategy_status(telegram_id)
            strategy_name = strategy_status.get('strategy_name', 'MACD Full')

            # Получаем настройки пользователя для отображения
            user_settings = db.get_user_settings(telegram_id)
            trading_pair = user_settings.get('trading_pair', 'Unknown') if user_settings else 'Unknown'
            leverage = user_settings.get('leverage', 'Unknown') if user_settings else 'Unknown'
            timeframe = user_settings.get('timeframe', 'Unknown') if user_settings else 'Unknown'

            # Размер позиции
            position_size_info = db.get_position_size_info(telegram_id)
            position_size = position_size_info.get('display', 'Unknown')

            text = (
                f"🤖 <b>Торговый бот MACD</b>\n\n"
                f"📊 <b>Статус:</b> 🚀 Стратегия запущена!\n\n"
                f"🎯 <b>Стратегия:</b> {strategy_name}\n"
                f"💰 <b>Пара:</b> {trading_pair}\n"
                f"⚡ <b>Плечо:</b> {leverage}x\n"
                f"📊 <b>Размер:</b> {position_size}\n"
                f"⏱️ <b>Таймфрейм:</b> {timeframe}"
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
                text += f"🎯 <b>Готов к торговле!</b> Запустите MACD Full стратегию."
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
    def get_strategy_confirm_text(strategy_name: str, telegram_id: int) -> str:
        """Текст подтверждения для MACD Full стратегии"""
        # Получаем настройки пользователя
        user_settings = db.get_user_settings(telegram_id)

        if not user_settings:
            return "❌ Ошибка: настройки не найдены"

        # Информация о настройках
        trading_pair = user_settings.get('trading_pair', 'Не установлена')
        leverage = user_settings.get('leverage', 'Не установлено')
        timeframe = user_settings.get('timeframe', 'Не установлен')

        # Размер позиции
        position_size_info = db.get_position_size_info(telegram_id)
        position_size = position_size_info.get('display', 'Не установлен')

        text = (
            f"🚀 <b>Подтверждение запуска</b>\n\n"
            f"🎯 <b>Стратегия:</b> MACD Full (Long + Short)\n\n"
            f"<b>📋 Параметры торговли:</b>\n"
            f"💰 Пара: {trading_pair}\n"
            f"⚡ Плечо: {leverage}x\n"
            f"📊 Размер: {position_size}\n"
            f"⏱️ Таймфрейм: {timeframe}\n\n"
            f"❗ <b>Внимание:</b> Убедитесь, что все параметры настроены корректно!"
        )

        return text

    @staticmethod
    def get_statistics_text(telegram_id: int) -> str:
        """Текст статистики торговли с реальными данными"""
        from ...strategy import strategy_manager

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

        # Статус стратегии
        is_active = strategy_manager.is_strategy_active(telegram_id)
        strategy_status_text = ""

        if is_active:
            strategy_status = strategy_manager.get_strategy_status(telegram_id)
            strategy_status_text = (
                f"\n🟢 <b>Активная стратегия:</b> {strategy_status.get('strategy_name', 'MACD Full')}"
            )

        # Форматируем P&L с помощью helpers
        from ...utils.helpers import format_pnl, format_percentage
        pnl_formatted = format_pnl(total_pnl, with_currency=False)
        win_rate_formatted = format_percentage(win_rate, 1)

        # Время обновления в МСК
        update_time_msk = format_msk_time()

        return (
            f"📊 <b>Статистика торговли</b>\n\n"
            f"{pnl_formatted} USDT\n"
            f"🔢 <b>Всего сделок:</b> {total_trades}\n"
            f"✅ <b>Закрытых сделок:</b> {closed_trades}\n"
            f"📈 <b>Прибыльных:</b> {profitable_trades} ({win_rate_formatted})\n"
            f"📉 <b>Убыточных:</b> {losing_trades}"
            f"{strategy_status_text}\n\n"
            f"🔄 <i>Обновлено: {update_time_msk} МСК</i>"
        )

    @staticmethod
    async def get_balance_text(telegram_id: int) -> str:
        """Получение реального баланса счёта через Bybit API"""
        from ...strategy import strategy_manager

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
                        f"\n🤖 <b>Активная стратегия:</b> {strategy_status.get('strategy_name', 'MACD Full')}\n"
                        f"📊 <b>Размер позиции:</b> {position_size}"
                    )

                # Время обновления в МСК
                update_time_msk = format_msk_time()

                result_text = (
                    f"💰 <b>Баланс счёта Bybit</b>\n\n"
                    f"{balance_emoji} <b>Общий баланс:</b> {total_formatted} USDT\n"
                    f"✅ <b>Доступно:</b> {free_formatted} USDT\n"
                    f"🔒 <b>В позициях:</b> {used_formatted} USDT\n\n"
                    f"🔄 <i>Обновлено: {update_time_msk} МСК</i>"
                    f"{strategy_text}"
                )

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
        from ...strategy import strategy_manager

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
            'symbol': strategy_status.get('symbol'),
            'position_size': strategy_status.get('position_size'),
            'start_time': strategy_status.get('start_time'),
            'strategy_id': strategy_status.get('strategy_id')
        }
# src/bot/utils/trade_utils.py
from typing import Dict, Any, Optional
from ...database.database import db
from ...utils.logger import logger


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

        # Проверяем таймфреймы
        if not user_settings.get('entry_timeframe'):
            missing_settings.append('ТФ входа')

        if not user_settings.get('exit_timeframe'):
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

        # Проверяем настройки
        settings_info = TradeBotUtils.check_settings_completeness(telegram_id)

        # Получаем настройки пользователя
        user_settings = db.get_user_settings(telegram_id)

        # Формируем статус настроек
        if settings_info['complete']:
            settings_status = "✅ Настройки завершены"
            settings_emoji = "🟢"
        else:
            settings_status = f"❌ Не завершены ({settings_info['progress']}/{settings_info['total_count']})"
            settings_emoji = "🔴"

        # Статус бота (пока заглушка)
        bot_status = "⏳ Ожидает запуска"

        # Текущая торговая пара
        trading_pair = user_settings.get('trading_pair', 'Не установлена') if user_settings else 'Не установлена'

        # Активные позиции (пока заглушка)
        active_positions = 0

        text = (
            f"🤖 <b>Торговый бот MACD</b>\n\n"
            f"📊 <b>Статус:</b> {bot_status}\n"
            f"{settings_emoji} <b>Настройки:</b> {settings_status}\n\n"
            f"💰 <b>Торговая пара:</b> {trading_pair}\n"
            f"📈 <b>Активные позиции:</b> {active_positions}\n\n"
        )

        if not settings_info['complete']:
            text += (
                f"⚠️ <b>Для начала торговли завершите настройки:</b>\n"
            )
            for i, setting in enumerate(settings_info['missing_settings'][:3], 1):
                text += f"  {i}. {setting}\n"

            if len(settings_info['missing_settings']) > 3:
                text += f"  ... и ещё {len(settings_info['missing_settings']) - 3}\n"

            text += f"\n💡 Перейдите в «Настройки» из главного меню"
        else:
            text += f"🎯 <b>Готов к торговле!</b> Выберите стратегию для запуска."

        return text

    @staticmethod
    def get_strategy_menu_text() -> str:
        """Текст меню выбора стратегии"""
        return (
            f"🎯 <b>Выбор стратегии MACD</b>\n\n"
            f"📊 <b>MACD Full</b> - торговля в обе стороны\n"
            f"   • Покупки при бычьем пересечении\n"
            f"   • Продажи при медвежьем пересечении\n\n"
            f"📈 <b>MACD Long</b> - только покупки\n"
            f"   • Открытие длинных позиций\n"
            f"   • Закрытие по сигналам выхода\n\n"
            f"📉 <b>MACD Short</b> - только продажи\n"
            f"   • Открытие коротких позиций\n"
            f"   • Закрытие по сигналам выхода\n\n"
            f"💡 Выберите подходящую стратегию для вашего стиля торговли"
        )

    @staticmethod
    def get_strategy_confirm_text(strategy_name: str, telegram_id: int) -> str:
        """Текст подтверждения выбранной стратегии"""

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
        """Текст статистики торговли"""
        # Пока заглушка, в будущем будет получать реальные данные
        return (
            f"📊 <b>Статистика торговли</b>\n\n"
            f"💰 <b>Общий P&L:</b> +0.00 USDT\n"
            f"📈 <b>Прибыльных сделок:</b> 0 из 0 (0%)\n"
            f"📉 <b>Убыточных сделок:</b> 0 из 0 (0%)\n"
            f"⏱️ <b>Время работы:</b> 00:00:00\n"
            f"🎯 <b>Последний сигнал:</b> Нет данных\n"
            f"💹 <b>Лучшая сделка:</b> +0.00 USDT\n"
            f"📉 <b>Худшая сделка:</b> -0.00 USDT\n\n"
            f"📈 <b>Активная стратегия:</b> Не запущена\n"
            f"🔄 <b>Статус бота:</b> Ожидает запуска"
        )

    @staticmethod
    def get_balance_text(telegram_id: int) -> str:
        """Текст баланса счёта"""
        user_settings = db.get_user_settings(telegram_id)
        trading_pair = user_settings.get('trading_pair', 'BTCUSDT') if user_settings else 'BTCUSDT'

        # Пока заглушка, в будущем будет получать реальный баланс через Bybit API
        return (
            f"💰 <b>Баланс счёта Bybit</b>\n\n"
            f"💵 <b>Общий баланс:</b> 0.00 USDT\n"
            f"✅ <b>Доступно:</b> 0.00 USDT\n"
            f"🔒 <b>В позициях:</b> 0.00 USDT\n"
            f"📊 <b>Нереализованный P&L:</b> +0.00 USDT\n\n"
            f"📈 <b>Торговая пара:</b> {trading_pair}\n"
            f"⚡ <b>Открытых позиций:</b> 0\n\n"
            f"🔄 <i>Обновлено: только что</i>\n\n"
            f"⚠️ <i>Для отображения реального баланса\n"
            f"проверьте настройки API ключей</i>"
        )

    @staticmethod
    def get_blocked_strategy_text() -> str:
        """Текст при заблокированной кнопке стратегии"""
        return (
            f"🔒 <b>Стратегии недоступны</b>\n\n"
            f"❌ Не все настройки завершены\n\n"
            f"<b>Для доступа к стратегиям завершите:</b>\n"
            f"1. Настройку API ключей\n"
            f"2. Выбор торговой пары\n"
            f"3. Установку плеча\n"
            f"4. Размер позиции\n"
            f"5. Таймфреймы входа и выхода\n"
            f"6. Время работы бота\n\n"
            f"💡 Перейдите в «Настройки» из главного меню"
        )
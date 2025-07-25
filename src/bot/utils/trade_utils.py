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
        return (
            f"🎯 <b>Выбор стратегии MACD</b>\n\n"
            f"💡 Выберите подходящую стратегию"
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
        """Текст статистики торговли с актуальной позицией"""

        # Получаем настройки пользователя для торговой пары
        user_settings = db.get_user_settings(telegram_id)
        trading_pair = user_settings.get('trading_pair') if user_settings else None

        # Пока заглушка для позиции, в будущем будет реальная проверка через Bybit API
        current_position = TradeBotUtils._get_current_position(telegram_id, trading_pair)

        return (
            f"📊 <b>Статистика торговли</b>\n\n"
            f"💰 <b>Общий P&L:</b> +0.00 USDT\n"
            f"🔢 <b>Всего сделок:</b> 0\n"
            f"📈 <b>Прибыльных сделок:</b> 0 из 0 (0%)\n"
            f"📉 <b>Убыточных сделок:</b> 0 из 0 (0%)\n\n"
            f"📊 <b>Актуальная позиция:</b> {current_position}"
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
        # Пока заглушка, в будущем здесь будет:
        # 1. Проверка API ключей
        # 2. Запрос к Bybit API для получения открытых позиций
        # 3. Форматирование позиции

        try:
            # Проверяем есть ли настройки API
            user_settings = db.get_user_settings(telegram_id)
            if not user_settings or not user_settings.get('bybit_api_key') or not user_settings.get('bybit_secret_key'):
                return "API ключи не настроены"

            if not trading_pair:
                return "торговая пара не установлена"

            # В будущем здесь будет реальный запрос к Bybit API
            # Пока возвращаем заглушку
            has_position = False  # Заглушка, в будущем - реальная проверка

            if has_position:
                # Пример форматирования позиции:
                # return f"LONG {trading_pair} | Размер: 0.1 BTC | P&L: +15.30 USDT"
                return f"нет данных (API в разработке)"
            else:
                return "нет"

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

        return entry_tf == exit_tf and entry_tf is not None

    @staticmethod
    def get_balance_text(telegram_id: int) -> str:
        """Текст баланса счёта"""
        # Пока заглушка, в будущем будет получать реальный баланс через Bybit API
        return (
            f"💰 <b>Баланс счёта Bybit</b>\n\n"
            f"💵 <b>Общий баланс:</b> 0.00 USDT\n"
            f"✅ <b>Доступно:</b> 0.00 USDT\n"
            f"🔒 <b>В позициях:</b> 0.00 USDT\n"
            f"📊 <b>Нереализованный P&L:</b> +0.00 USDT\n\n"
            f"🔄 <i>Обновлено: только что</i>\n\n"
            f"⚠️ <i>Для отображения реального баланса\n"
            f"проверьте настройки API ключей</i>"
        )
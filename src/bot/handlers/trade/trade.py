# src/bot/handlers/trade/trade.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from src.bot.keyboards.trade_menu import (
    get_trade_menu,
    get_strategy_menu,
    get_strategy_confirm_menu,
    get_active_trading_menu,
    get_statistics_menu,
    get_balance_menu,
    get_back_to_trade_menu
)
from ...utils.trade_utils import TradeBotUtils
from src.utils.logger import logger
from src.utils.config import config

router = Router()


@router.callback_query(F.data == "trade_menu")
async def trade_menu(callback: CallbackQuery):
    """Главное торговое меню"""
    if not config.is_user_allowed(callback.from_user.id):
        logger.warning(f"Unauthorized callback from user {callback.from_user.id} - ignored silently")
        return

    try:
        # Проверяем полноту настроек
        settings_info = TradeBotUtils.check_settings_completeness(callback.from_user.id)

        # Генерируем текст меню
        menu_text = TradeBotUtils.get_trade_menu_text(callback.from_user.id)

        # Показываем меню с учетом статуса настроек
        await callback.message.edit_text(
            menu_text,
            reply_markup=get_trade_menu(settings_info['complete']),
            parse_mode='HTML'
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в trade_menu: {e}")
        await callback.answer("❌ Ошибка загрузки торгового меню", show_alert=True)


@router.callback_query(F.data == "trade_strategy_blocked")
async def strategy_blocked(callback: CallbackQuery):
    """Обработка заблокированной кнопки стратегии"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    blocked_text = TradeBotUtils.get_blocked_strategy_text()

    await callback.message.edit_text(
        blocked_text,
        reply_markup=get_back_to_trade_menu(),
        parse_mode='HTML'
    )
    await callback.answer("🔒 Завершите настройки для доступа к стратегиям", show_alert=True)


@router.callback_query(F.data == "trade_strategy_menu")
async def strategy_menu(callback: CallbackQuery):
    """Меню выбора стратегии"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    # Дополнительная проверка настроек
    settings_info = TradeBotUtils.check_settings_completeness(callback.from_user.id)

    if not settings_info['complete']:
        await strategy_blocked(callback)
        return

    strategy_text = TradeBotUtils.get_strategy_menu_text()

    await callback.message.edit_text(
        strategy_text,
        reply_markup=get_strategy_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


@router.callback_query(F.data.startswith("strategy_"))
async def strategy_selected(callback: CallbackQuery):
    """Обработка выбора стратегии"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    strategy_name = callback.data.replace("strategy_", "")

    # Проверяем настройки еще раз
    settings_info = TradeBotUtils.check_settings_completeness(callback.from_user.id)

    if not settings_info['complete']:
        await strategy_blocked(callback)
        return

    # Генерируем текст подтверждения
    confirm_text = TradeBotUtils.get_strategy_confirm_text(strategy_name, callback.from_user.id)

    await callback.message.edit_text(
        confirm_text,
        reply_markup=get_strategy_confirm_menu(strategy_name),
        parse_mode='HTML'
    )
    await callback.answer(f"Стратегия {strategy_name} выбрана")


@router.callback_query(F.data.startswith("start_trading_"))
async def start_trading(callback: CallbackQuery):
    """Запуск торговли (заглушка)"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    strategy_name = callback.data.replace("start_trading_", "")

    # Пока заглушка
    await callback.message.edit_text(
        f"🚀 <b>Торговля запущена!</b>\n\n"
        f"🎯 Стратегия: {strategy_name}\n"
        f"⏳ Статус: Инициализация...\n\n"
        f"🔄 <i>Функционал в разработке</i>",
        reply_markup=get_back_to_trade_menu(),
        parse_mode='HTML'
    )
    await callback.answer("🚀 Торговля запущена (демо режим)")

    logger.info(f"User {callback.from_user.id} started trading with strategy: {strategy_name}")


@router.callback_query(F.data == "trade_statistics")
async def trade_statistics(callback: CallbackQuery):
    """Статистика торговли"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    stats_text = TradeBotUtils.get_statistics_text(callback.from_user.id)

    await callback.message.edit_text(
        stats_text,
        reply_markup=get_statistics_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


@router.callback_query(F.data == "trade_balance")
async def trade_balance(callback: CallbackQuery):
    """Баланс счёта"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    balance_text = TradeBotUtils.get_balance_text(callback.from_user.id)

    await callback.message.edit_text(
        balance_text,
        reply_markup=get_balance_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


@router.callback_query(F.data == "detailed_stats")
async def detailed_stats(callback: CallbackQuery):
    """Подробная статистика (заглушка)"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "📊 <b>Подробная статистика</b>\n\n"
        "🚧 <i>Раздел в разработке</i>\n\n"
        "В будущем здесь будет:\n"
        "• График P&L по времени\n"
        "• Анализ по торговым парам\n"
        "• Эффективность стратегий\n"
        "• Детальная аналитика",
        reply_markup=get_statistics_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


@router.callback_query(F.data == "trade_history")
async def trade_history(callback: CallbackQuery):
    """История сделок (заглушка)"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "📋 <b>История сделок</b>\n\n"
        "🚧 <i>Раздел в разработке</i>\n\n"
        "Здесь будет отображаться:\n"
        "• Все выполненные сделки\n"
        "• Детали каждой операции\n"
        "• Фильтры по датам\n"
        "• Экспорт данных",
        reply_markup=get_statistics_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


@router.callback_query(F.data == "refresh_balance")
async def refresh_balance(callback: CallbackQuery):
    """Обновление баланса (заглушка)"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    # Имитируем обновление
    await callback.answer("🔄 Обновление баланса...")

    balance_text = TradeBotUtils.get_balance_text(callback.from_user.id)

    await callback.message.edit_text(
        balance_text,
        reply_markup=get_balance_menu(),
        parse_mode='HTML'
    )


@router.callback_query(F.data == "view_positions")
async def view_positions(callback: CallbackQuery):
    """Просмотр позиций (заглушка)"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "📊 <b>Открытые позиции</b>\n\n"
        "💼 <i>Открытых позиций нет</i>\n\n"
        "🚧 <i>Функционал в разработке</i>\n\n"
        "В будущем здесь будет:\n"
        "• Список всех открытых позиций\n"
        "• Текущий P&L по каждой\n"
        "• Возможность ручного закрытия\n"
        "• Изменение TP/SL",
        reply_markup=get_balance_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


@router.callback_query(F.data == "balance_history")
async def balance_history(callback: CallbackQuery):
    """История баланса (заглушка)"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "📋 <b>История баланса</b>\n\n"
        "🚧 <i>Раздел в разработке</i>\n\n"
        "Здесь будет показана:\n"
        "• История изменений баланса\n"
        "• График роста/падения\n"
        "• Привязка к сделкам\n"
        "• Статистика по периодам",
        reply_markup=get_balance_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


# Универсальная заглушка для будущих callback'ов
@router.callback_query(F.data.in_([
    "stop_trading",
    "active_trading_menu"
]))
async def trading_placeholder(callback: CallbackQuery):
    """Заглушки для торговых функций"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.answer("🚧 Функция в разработке", show_alert=True)
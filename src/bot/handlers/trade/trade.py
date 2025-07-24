# src/bot/handlers/trade/trade.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from src.bot.keyboards.trade_menu import (
    get_trade_menu,
    get_strategies_menu,
    get_positions_menu,
    get_back_to_trade_menu
)
from src.bot.keyboards.start_menu import get_back_to_start_menu
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
        await callback.message.edit_text(
            "📈 Торговое меню\n\n"
            "🚧 Раздел находится в разработке\n\n"
            "В будущем здесь будут доступны:\n"
            "• MACD торговые стратегии\n"
            "• Управление позициями\n"
            "• Торговая статистика\n"
            "• История сделок",
            reply_markup=get_trade_menu()
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в trade_menu: {e}")
        await callback.answer("❌ Ошибка загрузки торгового меню", show_alert=True)


# Заглушки для стратегий
@router.callback_query(F.data == "strategies_placeholder")
async def strategies_placeholder(callback: CallbackQuery):
    """Заглушка меню стратегий"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "🎯 Торговые стратегии\n\n"
        "🚧 В разработке:\n\n"
        "📊 MACD Full - торговля в обе стороны\n"
        "📈 MACD Long - только покупки\n"
        "📉 MACD Short - только продажи\n\n"
        "Скоро будет доступно!",
        reply_markup=get_strategies_menu()
    )
    await callback.answer()


@router.callback_query(F.data.in_([
    "strategy_full_placeholder",
    "strategy_long_placeholder",
    "strategy_short_placeholder"
]))
async def strategy_placeholder(callback: CallbackQuery):
    """Заглушки для отдельных стратегий"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    strategy_names = {
        "strategy_full_placeholder": "MACD Full",
        "strategy_long_placeholder": "MACD Long",
        "strategy_short_placeholder": "MACD Short"
    }

    strategy_name = strategy_names.get(callback.data, "Стратегия")

    await callback.answer(f"🚧 {strategy_name} стратегия в разработке", show_alert=True)


# Заглушки для позиций
@router.callback_query(F.data == "positions_placeholder")
async def positions_placeholder(callback: CallbackQuery):
    """Заглушка меню позиций"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "📊 Управление позициями\n\n"
        "🚧 В разработке:\n\n"
        "🔄 Текущие открытые позиции\n"
        "📋 История закрытых позиций\n"
        "⚡ Быстрое закрытие позиций\n"
        "📈 Управление TP/SL\n\n"
        "Функционал будет добавлен после реализации стратегий!",
        reply_markup=get_positions_menu()
    )
    await callback.answer()


@router.callback_query(F.data.in_([
    "current_positions_placeholder",
    "positions_history_placeholder"
]))
async def position_details_placeholder(callback: CallbackQuery):
    """Заглушки для деталей позиций"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    details = {
        "current_positions_placeholder": "Текущие позиции",
        "positions_history_placeholder": "История позиций"
    }

    detail_name = details.get(callback.data, "Позиции")
    await callback.answer(f"🚧 {detail_name} в разработке", show_alert=True)


# Заглушки для статистики и истории
@router.callback_query(F.data == "stats_placeholder")
async def stats_placeholder(callback: CallbackQuery):
    """Заглушка статистики"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "📊 Торговая статистика\n\n"
        "🚧 В разработке:\n\n"
        "💰 Общая прибыль/убыток\n"
        "📈 Процент успешных сделок\n"
        "🎯 Лучшие стратегии\n"
        "📅 Статистика по периодам\n"
        "📋 Детальные отчеты\n\n"
        "Статистика появится после начала торговли!",
        reply_markup=get_back_to_trade_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "history_placeholder")
async def history_placeholder(callback: CallbackQuery):
    """Заглушка истории"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        "📋 История торговли\n\n"
        "🚧 В разработке:\n\n"
        "📝 Журнал всех сделок\n"
        "🔍 Фильтры по датам\n"
        "💹 Детали каждой сделки\n"
        "📊 Графики результатов\n"
        "📤 Экспорт данных\n\n"
        "История будет сохраняться автоматически!",
        reply_markup=get_back_to_trade_menu()
    )
    await callback.answer()


# Универсальная заглушка для неожиданных callback'ов
@router.callback_query(F.data.endswith("_placeholder"))
async def universal_placeholder(callback: CallbackQuery):
    """Универсальная заглушка"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.answer("🚧 Функция находится в разработке", show_alert=True)
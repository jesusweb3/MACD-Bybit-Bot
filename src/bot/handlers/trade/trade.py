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
    get_back_to_trade_menu,
    get_trade_history_menu
)
from ...utils.trade_utils import TradeBotUtils
from src.utils.logger import logger
from src.utils.config import config
from src.database.database import db
from src.strategies import strategy_manager

router = Router()


@router.callback_query(F.data == "trade_menu")
async def trade_menu(callback: CallbackQuery):
    """Главное торговое меню"""
    if not config.is_user_allowed(callback.from_user.id):
        logger.warning(f"Unauthorized callback from user {callback.from_user.id} - ignored silently")
        return

    try:
        # Проверяем есть ли активная стратегия
        is_strategy_active = strategy_manager.is_strategy_active(callback.from_user.id)

        if is_strategy_active:
            # Если стратегия активна - показываем меню активной торговли
            await active_trading_menu(callback)
            return

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
    """Обработка заблокированной кнопки стратегии - только уведомление"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    # Просто показываем уведомление и НЕ меняем интерфейс
    await callback.answer("🔒 Завершите настройки для доступа к стратегиям", show_alert=True)


@router.callback_query(F.data == "trade_strategy_menu")
async def strategy_menu(callback: CallbackQuery):
    """Меню выбора стратегии"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    # Дополнительная проверка настроек
    settings_info = TradeBotUtils.check_settings_completeness(callback.from_user.id)

    if not settings_info['complete']:
        # Если настройки не завершены - показываем уведомление и остаемся в меню
        await callback.answer("🔒 Завершите настройки для доступа к стратегиям", show_alert=True)
        return

    # Проверяем есть ли уже активная стратегия
    if strategy_manager.is_strategy_active(callback.from_user.id):
        await callback.answer("⚠️ У вас уже запущена стратегия. Остановите ее в разделе торговли.", show_alert=True)
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
        await callback.answer("🔒 Завершите настройки для доступа к стратегиям", show_alert=True)
        return

    # Проверяем есть ли уже активная стратегия
    if strategy_manager.is_strategy_active(callback.from_user.id):
        await callback.answer("⚠️ У вас уже запущена стратегия. Остановите ее перед запуском новой.", show_alert=True)
        return

    # Специальная проверка для MACD Full - нужны одинаковые таймфреймы
    if strategy_name == "macd_full":
        user_settings = db.get_user_settings(callback.from_user.id)
        entry_tf = user_settings.get('entry_timeframe') if user_settings else None
        exit_tf = user_settings.get('exit_timeframe') if user_settings else None

        if entry_tf != exit_tf:
            await callback.answer("⚠️ Для MACD Full настройте одинаковые ТФ для входа и выхода", show_alert=True)
            return

    # Проверяем доступность стратегии
    available_strategies = strategy_manager.get_available_strategies()
    if not available_strategies.get(strategy_name, False):
        await callback.answer("⚠️ Эта стратегия еще не реализована", show_alert=True)
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
    """Запуск торговли - РЕАЛЬНАЯ РЕАЛИЗАЦИЯ"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    strategy_name = callback.data.replace("start_trading_", "")

    try:
        # Показываем сообщение о запуске
        await callback.message.edit_text(
            f"🔄 <b>Запуск стратегии {strategy_name}...</b>\n\n"
            f"⏳ Инициализация компонентов...\n"
            f"📊 Подключение к MACD индикатору...\n"
            f"🔗 Проверка соединения с Bybit...",
            parse_mode='HTML'
        )
        await callback.answer()

        # РЕАЛЬНЫЙ ЗАПУСК СТРАТЕГИИ
        result = await strategy_manager.start_strategy(callback.from_user.id, strategy_name)

        if result['success']:
            # Успешный запуск
            strategy_status = strategy_manager.get_strategy_status(callback.from_user.id)

            success_text = (
                f"🚀 <b>Стратегия запущена!</b>\n\n"
                f"🎯 <b>Стратегия:</b> {result['strategy_name']}\n"
                f"🆔 <b>ID:</b> {result['strategy_id']}\n"
                f"📊 <b>Состояние:</b> {strategy_status.get('position_state', 'Определяется...')}\n"
                f"⏰ <b>Статус:</b> Активна\n\n"
                f"✅ <b>{result['message']}</b>\n\n"
                f"💡 <i>Стратегия работает автоматически.\n"
                f"Следите за уведомлениями о сделках.</i>"
            )

            await callback.message.edit_text(
                success_text,
                reply_markup=get_active_trading_menu(),
                parse_mode='HTML'
            )

            logger.info(f"✅ Пользователь {callback.from_user.id} успешно запустил стратегию {strategy_name}")

        else:
            # Ошибка запуска
            error_text = (
                f"❌ <b>Ошибка запуска стратегии</b>\n\n"
                f"🎯 <b>Стратегия:</b> {strategy_name}\n"
                f"⚠️ <b>Ошибка:</b> {result['error']}\n\n"
                f"🔧 <i>Проверьте настройки и попробуйте снова.</i>"
            )

            await callback.message.edit_text(
                error_text,
                reply_markup=get_back_to_trade_menu(),
                parse_mode='HTML'
            )

            logger.error(f"❌ Ошибка запуска стратегии {strategy_name} для {callback.from_user.id}: {result['error']}")

    except Exception as e:
        # Критическая ошибка
        logger.error(f"❌ Критическая ошибка при запуске стратегии: {e}")

        await callback.message.edit_text(
            f"🚨 <b>Критическая ошибка</b>\n\n"
            f"❌ <b>Не удалось запустить стратегию</b>\n"
            f"🔧 <i>Обратитесь к администратору</i>\n\n"
            f"<code>Ошибка: {str(e)}</code>",
            reply_markup=get_back_to_trade_menu(),
            parse_mode='HTML'
        )


@router.callback_query(F.data == "stop_trading")
async def stop_trading(callback: CallbackQuery):
    """Остановка торговли - РЕАЛЬНАЯ РЕАЛИЗАЦИЯ"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    try:
        # Проверяем есть ли активная стратегия
        if not strategy_manager.is_strategy_active(callback.from_user.id):
            await callback.answer("❌ У вас нет активной стратегии", show_alert=True)
            return

        # Получаем информацию о текущей стратегии
        strategy_status = strategy_manager.get_strategy_status(callback.from_user.id)
        strategy_name = strategy_status.get('strategy_name', 'Unknown')

        # Показываем сообщение об остановке
        await callback.message.edit_text(
            f"⏹️ <b>Остановка стратегии...</b>\n\n"
            f"🎯 <b>Стратегия:</b> {strategy_name}\n"
            f"⏳ Завершение активных операций...\n"
            f"🔌 Отключение от индикаторов...",
            parse_mode='HTML'
        )
        await callback.answer()

        # РЕАЛЬНАЯ ОСТАНОВКА СТРАТЕГИИ
        result = await strategy_manager.stop_strategy(callback.from_user.id, "Manual stop by user")

        if result['success']:
            # Успешная остановка
            success_text = (
                f"⏹️ <b>Стратегия остановлена</b>\n\n"
                f"🎯 <b>Стратегия:</b> {result['strategy_name']}\n"
                f"✅ <b>Статус:</b> Остановлена пользователем\n\n"
                f"📊 <i>Все позиции остались открытыми.\n"
                f"Управляйте ими вручную при необходимости.</i>"
            )

            await callback.message.edit_text(
                success_text,
                reply_markup=get_back_to_trade_menu(),
                parse_mode='HTML'
            )

            logger.info(f"✅ Пользователь {callback.from_user.id} остановил стратегию {result['strategy_name']}")

        else:
            # Ошибка остановки
            error_text = (
                f"⚠️ <b>Ошибка остановки</b>\n\n"
                f"❌ <b>Ошибка:</b> {result['error']}\n\n"
                f"🔧 <i>Стратегия могла быть остановлена частично</i>"
            )

            await callback.message.edit_text(
                error_text,
                reply_markup=get_back_to_trade_menu(),
                parse_mode='HTML'
            )

            logger.error(f"❌ Ошибка остановки стратегии для {callback.from_user.id}: {result['error']}")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка при остановке стратегии: {e}")

        await callback.message.edit_text(
            f"🚨 <b>Ошибка остановки</b>\n\n"
            f"❌ <code>{str(e)}</code>\n\n"
            f"🔧 <i>Обратитесь к администратору</i>",
            reply_markup=get_back_to_trade_menu(),
            parse_mode='HTML'
        )


@router.callback_query(F.data == "active_trading_menu")
async def active_trading_menu(callback: CallbackQuery):
    """Меню активной торговли - показ статуса"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    try:
        # Проверяем есть ли активная стратегия
        if not strategy_manager.is_strategy_active(callback.from_user.id):
            await callback.message.edit_text(
                "❌ <b>Активной стратегии не найдено</b>\n\n"
                "🔄 <i>Вернитесь в торговое меню для запуска</i>",
                reply_markup=get_back_to_trade_menu(),
                parse_mode='HTML'
            )
            await callback.answer()
            return

        # Получаем статус активной стратегии
        strategy_status = strategy_manager.get_strategy_status(callback.from_user.id)

        status_text = (
            f"🤖 <b>Активная торговля</b>\n\n"
            f"🎯 <b>Стратегия:</b> {strategy_status.get('strategy_name', 'Unknown')}\n"
            f"📊 <b>Позиция:</b> {strategy_status.get('position_state', 'Определяется...')}\n"
            f"💰 <b>Символ:</b> {strategy_status.get('symbol', 'Unknown')}\n"
            f"📈 <b>Размер:</b> {strategy_status.get('position_size', 'Unknown')}\n"
            f"⏰ <b>Статус:</b> {strategy_status.get('status', 'Unknown')}\n\n"
            f"🟢 <i>Стратегия работает автоматически</i>"
        )

        await callback.message.edit_text(
            status_text,
            reply_markup=get_active_trading_menu(),
            parse_mode='HTML'
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в active_trading_menu: {e}")
        await callback.answer("❌ Ошибка получения статуса", show_alert=True)


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


@router.callback_query(F.data == "trade_history")
async def trade_history(callback: CallbackQuery):
    """История сделок"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    # Получаем реальную историю сделок из БД
    trades = db.get_user_trades_history(callback.from_user.id, limit=10)

    if trades:
        history_text = "📋 <b>История сделок</b>\n\n"

        for trade in trades[:5]:  # Показываем последние 5
            side_emoji = "📈" if trade['side'] == 'LONG' else "📉"
            status_emoji = "✅" if trade['status'] == 'closed' else "🔄"

            pnl_text = ""
            if trade['pnl'] is not None:
                pnl_emoji = "💚" if trade['pnl'] > 0 else "💔" if trade['pnl'] < 0 else "💙"
                pnl_text = f"\n{pnl_emoji} P&L: {trade['pnl']:.2f} USDT"

            history_text += (
                f"{status_emoji} {side_emoji} <b>{trade['symbol']}</b>\n"
                f"📊 Количество: {trade['quantity']}\n"
                f"📅 Открыта: {trade['opened_at'][:16] if trade['opened_at'] else 'N/A'}"
                f"{pnl_text}\n\n"
            )

        if len(trades) > 5:
            history_text += f"<i>... и еще {len(trades) - 5} сделок</i>"
    else:
        history_text = (
            "📋 <b>История сделок</b>\n\n"
            "📝 <i>Сделок пока нет</i>\n\n"
            "💡 <i>После запуска стратегии здесь будут\n"
            "отображаться все ваши сделки</i>"
        )

    await callback.message.edit_text(
        history_text,
        reply_markup=get_trade_history_menu(),
        parse_mode='HTML'
    )
    await callback.answer()


@router.callback_query(F.data == "refresh_trade_history")
async def refresh_trade_history(callback: CallbackQuery):
    """Обновление истории сделок"""
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.answer("🔄 Обновление истории...")

    # Просто перенаправляем на trade_history для обновления
    await trade_history(callback)


@router.callback_query(F.data == "refresh_balance")
async def refresh_balance(callback: CallbackQuery):
    """Обновление баланса"""
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
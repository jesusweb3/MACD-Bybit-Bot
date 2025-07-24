# src/bot/handlers/settings/settings.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from src.bot.keyboards.settings_menu import (
    get_settings_menu, get_api_menu, get_leverage_menu,
    get_timeframes_menu, get_timeframe_selection, get_back_to_settings,
    get_tp_sl_menu, get_back_to_tp_sl
)
from src.bot.states.user_states import SettingsStates
from src.database.database import db
from src.utils.logger import logger

router = Router()


def get_progress_bar(filled: int, total: int) -> str:
    """Создание прогресс-бара"""
    if total == 0:
        return ""

    filled_blocks = "⬜" * filled
    empty_blocks = "⬛" * (total - filled)
    return filled_blocks + empty_blocks


def count_filled_settings(user_settings: dict, telegram_id: int) -> tuple[int, int]:
    """Подсчет заполненных настроек"""
    if not user_settings:
        return 0, 8

    # Проверяем каждую настройку для подсчета заполненных
    api_filled = bool(
        user_settings.get('bybit_api_key') and user_settings.get('bybit_secret_key'))

    # Корректируем подсчет
    filled_settings = []
    if api_filled:
        filled_settings.append('api')
    if user_settings.get('trading_pair'):
        filled_settings.append('pair')
    if user_settings.get('leverage'):
        filled_settings.append('leverage')

    # Проверяем размер позиции
    position_size_info = db.get_position_size_info(telegram_id)
    if position_size_info and position_size_info.get('value') is not None and position_size_info.get('value') > 0:
        filled_settings.append('position_size')

    # TP/SL теперь считаем как одну настройку и только если включено
    tp_sl_info = db.get_tp_sl_info(telegram_id)
    if tp_sl_info['enabled'] and tp_sl_info['take_profit'] and tp_sl_info['stop_loss']:
        filled_settings.append('tp_sl')

    if user_settings.get('entry_timeframe'):
        filled_settings.append('entry_tf')
    if user_settings.get('exit_timeframe'):
        filled_settings.append('exit_tf')
    if user_settings.get('bot_duration_hours'):
        filled_settings.append('duration')

    filled_count = len(filled_settings)
    total_count = 8

    return filled_count, total_count


def format_setting_display(value, setting_name: str = "") -> str:
    """Форматирование значения настройки для отображения"""
    # Специальная обработка для API статуса
    if setting_name == "api_status":
        return "✅ Настроено" if value else "—"

    # Обычная проверка для остальных настроек
    if value is None or value == "" or (isinstance(value, (int, float)) and value == 0):
        return "—"

    if setting_name in ["leverage"]:
        return f"{value}x"
    elif setting_name in ["bot_duration_hours"]:
        return f"{value}ч"
    else:
        return str(value)


def parse_position_size_input(user_input: str) -> dict:
    """Парсинг ввода пользователя для размера позиции"""
    try:
        text = user_input.strip().upper()

        if text.endswith('%'):
            # Процент от баланса
            try:
                percent = float(text[:-1])
                if 1 <= percent <= 100:
                    return {
                        'success': True,
                        'type': 'percentage',
                        'value': percent,
                        'display': f"{percent}%"
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Процент должен быть от 1% до 100%'
                    }
            except ValueError:
                return {
                    'success': False,
                    'error': 'Неверный формат процента'
                }

        elif text.endswith('USDT'):
            # Фиксированная сумма
            try:
                amount = float(text[:-4])
                if amount > 0:
                    return {
                        'success': True,
                        'type': 'fixed_usdt',
                        'value': amount,
                        'display': f"{amount}USDT"
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Сумма должна быть больше 0'
                    }
            except ValueError:
                return {
                    'success': False,
                    'error': 'Неверный формат суммы'
                }
        else:
            return {
                'success': False,
                'error': 'Используйте формат: 15% или 100USDT'
            }

    except Exception as e:
        return {
            'success': False,
            'error': f'Ошибка парсинга: {str(e)}'
        }


async def show_settings_menu(callback: CallbackQuery):
    user_settings = db.get_user_settings(callback.from_user.id)

    if not user_settings:
        settings_text = "❌ Настройки не найдены"
    else:
        # Подсчитываем заполненные настройки
        filled_count, total_count = count_filled_settings(user_settings, callback.from_user.id)
        progress_bar = get_progress_bar(filled_count, total_count)

        # Проверяем статус API ключей
        api_status = bool(
            user_settings.get('bybit_api_key') and user_settings.get('bybit_secret_key'))

        # Получаем информацию о размере позиции
        position_size_info = db.get_position_size_info(callback.from_user.id)
        position_size_display = position_size_info.get('display', '—')

        # Получаем информацию о TP/SL
        tp_sl_info = db.get_tp_sl_info(callback.from_user.id)
        tp_sl_display = tp_sl_info.get('display', '—')

        settings_text = (
            f"🔧 Настройки бота\n\n"
            f"Настройки заполнены: {filled_count}/{total_count} {progress_bar}\n\n"
            f"🔑 API ключи: {format_setting_display(api_status, 'api_status')}\n"
            f"💰 Пара: {format_setting_display(user_settings.get('trading_pair'))}\n"
            f"⚡ Плечо: {format_setting_display(user_settings.get('leverage'), 'leverage')}\n"
            f"📊 Размер позиции: {position_size_display}\n"
            f"⚙️ TP/SL: {tp_sl_display}\n"
            f"⏱️ ТФ входа: {format_setting_display(user_settings.get('entry_timeframe'))}\n"
            f"⏱️ ТФ выхода: {format_setting_display(user_settings.get('exit_timeframe'))}\n"
            f"🕒 Работа: {format_setting_display(user_settings.get('bot_duration_hours'), 'bot_duration_hours')}"
        )

    await callback.message.edit_text(settings_text, reply_markup=get_settings_menu())


async def show_settings_menu_after_update(message: Message, message_id: int):
    user_settings = db.get_user_settings(message.from_user.id)

    # Подсчитываем заполненные настройки
    filled_count, total_count = count_filled_settings(user_settings, message.from_user.id)
    progress_bar = get_progress_bar(filled_count, total_count)

    # Проверяем статус API ключей
    api_status = bool(
        user_settings.get('bybit_api_key') and user_settings.get('bybit_secret_key'))

    # Получаем информацию о размере позиции
    position_size_info = db.get_position_size_info(message.from_user.id)
    position_size_display = position_size_info.get('display', '—')

    # Получаем информацию о TP/SL
    tp_sl_info = db.get_tp_sl_info(message.from_user.id)
    tp_sl_display = tp_sl_info.get('display', '—')

    settings_text = (
        f"🔧 Настройки бота\n\n"
        f"Настройки заполнены: {filled_count}/{total_count} {progress_bar}\n\n"
        f"🔑 API ключи: {format_setting_display(api_status, 'api_status')}\n"
        f"💰 Пара: {format_setting_display(user_settings.get('trading_pair'))}\n"
        f"⚡ Плечо: {format_setting_display(user_settings.get('leverage'), 'leverage')}\n"
        f"📊 Размер позиции: {position_size_display}\n"
        f"⚙️ TP/SL: {tp_sl_display}\n"
        f"⏱️ ТФ входа: {format_setting_display(user_settings.get('entry_timeframe'))}\n"
        f"⏱️ ТФ выхода: {format_setting_display(user_settings.get('exit_timeframe'))}\n"
        f"🕒 Работа: {format_setting_display(user_settings.get('bot_duration_hours'), 'bot_duration_hours')}"
    )

    await message.bot.edit_message_text(
        settings_text,
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=get_settings_menu()
    )


@router.callback_query(F.data == "settings")
async def settings_menu(callback: CallbackQuery):
    await show_settings_menu(callback)
    await callback.answer()


@router.callback_query(F.data == "settings_tp_sl")
async def tp_sl_menu(callback: CallbackQuery):
    """Меню настройки TP/SL"""
    # Получаем текущие настройки TP/SL
    tp_sl_info = db.get_tp_sl_info(callback.from_user.id)

    enabled = tp_sl_info['enabled']
    take_profit = tp_sl_info['take_profit']
    stop_loss = tp_sl_info['stop_loss']

    # Формируем текст с текущими значениями
    status_text = "🟢 Включено" if enabled else "🔴 Выключено"

    tp_text = f"{take_profit} пунктов" if take_profit else "не установлен"
    sl_text = f"{stop_loss} пунктов" if stop_loss else "не установлен"

    menu_text = (
        f"⚙️ Настройки TP/SL\n\n"
        f"Статус: {status_text}\n\n"
        f"🎯 Тейк профит: {tp_text}\n"
        f"🛑 Стоп лосс: {sl_text}\n\n"
        f"💡 TP/SL устанавливаются в пунктах от цены входа.\n"
        f"Например: если цена входа 100, TP=20 пунктов, то выход по 120."
    )

    await callback.message.edit_text(
        menu_text,
        reply_markup=get_tp_sl_menu(is_enabled=enabled)
    )
    await callback.answer()


@router.callback_query(F.data == "tp_sl_enable")
async def enable_tp_sl(callback: CallbackQuery):
    """Включение TP/SL"""
    db.update_tp_sl_settings(callback.from_user.id, enabled=True)
    await callback.answer("✅ TP/SL включено")
    logger.info(f"User {callback.from_user.id} enabled TP/SL")
    await tp_sl_menu(callback)


@router.callback_query(F.data == "tp_sl_disable")
async def disable_tp_sl(callback: CallbackQuery):
    """Выключение TP/SL"""
    db.update_tp_sl_settings(callback.from_user.id, enabled=False)
    await callback.answer("✅ TP/SL выключено")
    logger.info(f"User {callback.from_user.id} disabled TP/SL")
    await tp_sl_menu(callback)


@router.callback_query(F.data == "set_take_profit")
async def set_take_profit(callback: CallbackQuery, state: FSMContext):
    """Установка тейк профита"""
    tp_sl_info = db.get_tp_sl_info(callback.from_user.id)
    current_tp = tp_sl_info.get('take_profit', 0)

    prompt_text = (
        "🎯 Введите тейк профит (в пунктах цены):\n\n"
        "Например: 50 (для BTC = +50 USD)"
    )

    if current_tp:
        prompt_text += f"\n\nТекущее значение: {current_tp} пунктов"

    await callback.message.edit_text(
        prompt_text,
        reply_markup=get_back_to_tp_sl()
    )
    await state.set_state(SettingsStates.waiting_for_take_profit)
    await state.update_data(message_id=callback.message.message_id)
    await callback.answer()


@router.message(SettingsStates.waiting_for_take_profit)
async def process_take_profit(message: Message, state: FSMContext):
    data = await state.get_data()
    message_id = data.get('message_id')
    await message.delete()

    try:
        take_profit = float(message.text.strip())
        if take_profit <= 0:
            await message.bot.edit_message_text(
                "❌ Тейк профит должен быть больше 0. Попробуйте еще раз:",
                chat_id=message.chat.id,
                message_id=message_id,
                reply_markup=get_back_to_tp_sl()
            )
            return
    except ValueError:
        await message.bot.edit_message_text(
            "❌ Введите корректное число. Попробуйте еще раз:",
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=get_back_to_tp_sl()
        )
        return

    db.update_tp_sl_settings(message.from_user.id, take_profit=take_profit)
    await state.clear()
    logger.info(f"User {message.from_user.id} set take profit: {take_profit}")

    await message.bot.edit_message_text(
        f"✅ Тейк профит установлен: {take_profit} пунктов",
        chat_id=message.chat.id,
        message_id=message_id
    )

    import asyncio
    await asyncio.sleep(1)

    # Показываем обновленное меню TP/SL
    tp_sl_info = db.get_tp_sl_info(message.from_user.id)
    enabled = tp_sl_info['enabled']
    take_profit = tp_sl_info['take_profit']
    stop_loss = tp_sl_info['stop_loss']

    status_text = "🟢 Включено" if enabled else "🔴 Выключено"
    tp_text = f"{take_profit} пунктов" if take_profit else "не установлен"
    sl_text = f"{stop_loss} пунктов" if stop_loss else "не установлен"

    menu_text = (
        f"⚙️ Настройки TP/SL\n\n"
        f"Статус: {status_text}\n\n"
        f"🎯 Тейк профит: {tp_text}\n"
        f"🛑 Стоп лосс: {sl_text}\n\n"
        f"💡 TP/SL устанавливаются в пунктах от цены входа."
    )

    await message.bot.edit_message_text(
        menu_text,
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=get_tp_sl_menu(is_enabled=enabled)
    )


@router.callback_query(F.data == "set_stop_loss")
async def set_stop_loss(callback: CallbackQuery, state: FSMContext):
    """Установка стоп лосса"""
    tp_sl_info = db.get_tp_sl_info(callback.from_user.id)
    current_sl = tp_sl_info.get('stop_loss', 0)

    prompt_text = (
        "🛑 Введите стоп лосс (в пунктах цены):\n\n"
        "Например: 75 (для BTC = -75 USD)"
    )

    if current_sl:
        prompt_text += f"\n\nТекущее значение: {current_sl} пунктов"

    await callback.message.edit_text(
        prompt_text,
        reply_markup=get_back_to_tp_sl()
    )
    await state.set_state(SettingsStates.waiting_for_stop_loss)
    await state.update_data(message_id=callback.message.message_id)
    await callback.answer()


@router.message(SettingsStates.waiting_for_stop_loss)
async def process_stop_loss(message: Message, state: FSMContext):
    data = await state.get_data()
    message_id = data.get('message_id')
    await message.delete()

    try:
        stop_loss = float(message.text.strip())
        if stop_loss <= 0:
            await message.bot.edit_message_text(
                "❌ Стоп лосс должен быть больше 0. Попробуйте еще раз:",
                chat_id=message.chat.id,
                message_id=message_id,
                reply_markup=get_back_to_tp_sl()
            )
            return
    except ValueError:
        await message.bot.edit_message_text(
            "❌ Введите корректное число. Попробуйте еще раз:",
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=get_back_to_tp_sl()
        )
        return

    db.update_tp_sl_settings(message.from_user.id, stop_loss=stop_loss)
    await state.clear()
    logger.info(f"User {message.from_user.id} set stop loss: {stop_loss}")

    await message.bot.edit_message_text(
        f"✅ Стоп лосс установлен: {stop_loss} пунктов",
        chat_id=message.chat.id,
        message_id=message_id
    )

    import asyncio
    await asyncio.sleep(1)

    # Показываем обновленное меню TP/SL
    tp_sl_info = db.get_tp_sl_info(message.from_user.id)
    enabled = tp_sl_info['enabled']
    take_profit = tp_sl_info['take_profit']
    stop_loss = tp_sl_info['stop_loss']

    status_text = "🟢 Включено" if enabled else "🔴 Выключено"
    tp_text = f"{take_profit} пунктов" if take_profit else "не установлен"
    sl_text = f"{stop_loss} пунктов" if stop_loss else "не установлен"

    menu_text = (
        f"⚙️ Настройки TP/SL\n\n"
        f"Статус: {status_text}\n\n"
        f"🎯 Тейк профит: {tp_text}\n"
        f"🛑 Стоп лосс: {sl_text}\n\n"
        f"💡 TP/SL устанавливаются в пунктах от цены входа."
    )

    await message.bot.edit_message_text(
        menu_text,
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=get_tp_sl_menu(is_enabled=enabled)
    )


@router.callback_query(F.data == "settings_api")
async def api_menu(callback: CallbackQuery):
    user_settings = db.get_user_settings(callback.from_user.id)

    api_key_status = "✅ Установлен" if (
            user_settings and user_settings.get('bybit_api_key')) else "❌ Не установлен"
    secret_key_status = "✅ Установлен" if (
            user_settings and user_settings.get('bybit_secret_key')) else "❌ Не установлен"

    api_text = (
        f"🔑 Настройки API\n\n"
        f"API ключ: {api_key_status}\n"
        f"Secret ключ: {secret_key_status}\n\n"
        f"⚠️ Используйте ключи с правами на торговлю"
    )

    await callback.message.edit_text(api_text, reply_markup=get_api_menu())
    await callback.answer()


@router.callback_query(F.data == "set_api_key")
async def set_api_key(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔑 Введите API ключ:\n\n"
        "⚠️ Убедитесь, что ключ имеет права на торговлю",
        reply_markup=get_back_to_settings()
    )
    await state.set_state(SettingsStates.waiting_for_api_key)
    await state.update_data(message_id=callback.message.message_id)
    await callback.answer()


@router.message(SettingsStates.waiting_for_api_key)
async def process_api_key(message: Message, state: FSMContext):
    api_key = message.text.strip()
    data = await state.get_data()
    message_id = data.get('message_id')
    await message.delete()

    if len(api_key) < 10:
        await message.bot.edit_message_text(
            "❌ API ключ слишком короткий. Попробуйте еще раз:",
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=get_back_to_settings()
        )
        return

    db.update_user_settings(message.from_user.id, bybit_api_key=api_key)
    await state.clear()
    logger.info(f"User {message.from_user.id} updated API key")

    user_settings = db.get_user_settings(message.from_user.id)
    api_key_status = "✅ Установлен" if user_settings.get('bybit_api_key') else "❌ Не установлен"
    secret_key_status = "✅ Установлен" if user_settings.get('bybit_secret_key') else "❌ Не установлен"

    api_text = (
        f"🔑 Настройки API\n\n"
        f"API ключ: {api_key_status}\n"
        f"Secret ключ: {secret_key_status}\n\n"
        f"⚠️ Используйте ключи с правами на торговлю\n\n"
        f"✅ API ключ успешно сохранен!"
    )

    await message.bot.edit_message_text(
        api_text,
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=get_api_menu()
    )


@router.callback_query(F.data == "set_secret_key")
async def set_secret_key(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔐 Введите Secret ключ:\n\n"
        "⚠️ Этот ключ будет храниться в зашифрованном виде",
        reply_markup=get_back_to_settings()
    )
    await state.set_state(SettingsStates.waiting_for_secret_key)
    await state.update_data(message_id=callback.message.message_id)
    await callback.answer()


@router.message(SettingsStates.waiting_for_secret_key)
async def process_secret_key(message: Message, state: FSMContext):
    secret_key = message.text.strip()
    data = await state.get_data()
    message_id = data.get('message_id')
    await message.delete()

    if len(secret_key) < 10:
        await message.bot.edit_message_text(
            "❌ Secret ключ слишком короткий. Попробуйте еще раз:",
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=get_back_to_settings()
        )
        return

    db.update_user_settings(message.from_user.id, bybit_secret_key=secret_key)
    await state.clear()
    logger.info(f"User {message.from_user.id} updated secret key")

    user_settings = db.get_user_settings(message.from_user.id)
    api_key_status = "✅ Установлен" if user_settings.get('bybit_api_key') else "❌ Не установлен"
    secret_key_status = "✅ Установлен" if user_settings.get('bybit_secret_key') else "❌ Не установлен"

    api_text = (
        f"🔑 Настройки API\n\n"
        f"API ключ: {api_key_status}\n"
        f"Secret ключ: {secret_key_status}\n\n"
        f"⚠️ Используйте ключи с правами на торговлю\n\n"
        f"✅ Secret ключ успешно сохранен!"
    )

    await message.bot.edit_message_text(
        api_text,
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=get_api_menu()
    )


@router.callback_query(F.data == "settings_pair")
async def set_trading_pair(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💰 Введите торговую пару (например: BTCUSDT, ETHUSDT):",
        reply_markup=get_back_to_settings()
    )
    await state.set_state(SettingsStates.waiting_for_trading_pair)
    await state.update_data(message_id=callback.message.message_id)
    await callback.answer()


@router.message(SettingsStates.waiting_for_trading_pair)
async def process_trading_pair(message: Message, state: FSMContext):
    pair = message.text.strip().upper()
    data = await state.get_data()
    message_id = data.get('message_id')
    await message.delete()

    if not pair or len(pair) < 5:
        await message.bot.edit_message_text(
            "❌ Неверный формат пары. Попробуйте еще раз (например: BTCUSDT):",
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=get_back_to_settings()
        )
        return

    db.update_user_settings(message.from_user.id, trading_pair=pair)
    await state.clear()
    logger.info(f"User {message.from_user.id} set trading pair: {pair}")
    await show_settings_menu_after_update(message, message_id)


@router.callback_query(F.data == "settings_leverage")
async def leverage_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚡ Выберите плечо (от 3x до 10x):",
        reply_markup=get_leverage_menu()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("leverage_"))
async def process_leverage(callback: CallbackQuery):
    leverage = int(callback.data.split("_")[1])

    if leverage < 3 or leverage > 10:
        await callback.answer("❌ Недопустимое плечо", show_alert=True)
        return

    db.update_user_settings(callback.from_user.id, leverage=leverage)
    await callback.answer(f"✅ Плечо установлено: {leverage}x")
    logger.info(f"User {callback.from_user.id} set leverage: {leverage}")
    await show_settings_menu(callback)


@router.callback_query(F.data == "settings_position_size")
async def set_position_size(callback: CallbackQuery, state: FSMContext):
    position_size_info = db.get_position_size_info(callback.from_user.id)
    current_display = position_size_info.get('display', 'не установлен')

    await callback.message.edit_text(
        f"📊 Введите новый размер позиции, пример:\n"
        f"15%\n"
        f"100USDT\n\n"
        f"Текущий размер: {current_display}",
        reply_markup=get_back_to_settings()
    )
    await state.set_state(SettingsStates.waiting_for_position_size)
    await state.update_data(message_id=callback.message.message_id)
    await callback.answer()


@router.message(SettingsStates.waiting_for_position_size)
async def process_position_size(message: Message, state: FSMContext):
    data = await state.get_data()
    message_id = data.get('message_id')
    await message.delete()

    parse_result = parse_position_size_input(message.text)

    if not parse_result['success']:
        await message.bot.edit_message_text(
            f"❌ {parse_result['error']}\n\n"
            f"Попробуйте еще раз:\n"
            f"15%\n"
            f"100USDT",
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=get_back_to_settings()
        )
        return

    db.update_position_size(
        telegram_id=message.from_user.id,
        size_type=parse_result['type'],
        size_value=parse_result['value']
    )

    await state.clear()
    logger.info(f"User {message.from_user.id} set position size: {parse_result['display']}")
    await show_settings_menu_after_update(message, message_id)


@router.callback_query(F.data == "settings_timeframes")
async def timeframes_menu(callback: CallbackQuery):
    user_settings = db.get_user_settings(callback.from_user.id)
    entry_tf = user_settings.get('entry_timeframe') if user_settings else None
    exit_tf = user_settings.get('exit_timeframe') if user_settings else None

    entry_text = entry_tf if entry_tf else "❌ Не установлен"
    exit_text = exit_tf if exit_tf else "❌ Не установлен"

    await callback.message.edit_text(
        f"⏱️ Настройка таймфреймов\n\n"
        f"📈 ТФ входа: {entry_text}\n"
        f"📉 ТФ выхода: {exit_text}\n\n"
        f"Поддерживаемые ТФ: 5m, 15m, 45m, 50m, 55m, 1h, 2h, 3h, 4h",
        reply_markup=get_timeframes_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "set_entry_timeframe")
async def set_entry_timeframe(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📈 Выберите таймфрейм для входа в позицию:\n\n"
        "Поддерживаемые: 5m, 15m, 45m, 50m, 55m, 1h, 2h, 3h, 4h",
        reply_markup=get_timeframe_selection()
    )
    await state.update_data(setting_type="entry", message_id=callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data == "set_exit_timeframe")
async def set_exit_timeframe(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📉 Выберите таймфрейм для выхода из позиции:\n\n"
        "Поддерживаемые: 5m, 15m, 45m, 50m, 55m, 1h, 2h, 3h, 4h",
        reply_markup=get_timeframe_selection()
    )
    await state.update_data(setting_type="exit", message_id=callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("tf_"))
async def process_timeframe(callback: CallbackQuery, state: FSMContext):
    timeframe = callback.data.split("_")[1]
    data = await state.get_data()
    setting_type = data.get("setting_type")

    if setting_type == "entry":
        db.update_user_settings(callback.from_user.id, entry_timeframe=timeframe)
        await callback.answer(f"✅ ТФ входа установлен: {timeframe}")
        logger.info(f"User {callback.from_user.id} set entry timeframe: {timeframe}")
    elif setting_type == "exit":
        db.update_user_settings(callback.from_user.id, exit_timeframe=timeframe)
        await callback.answer(f"✅ ТФ выхода установлен: {timeframe}")
        logger.info(f"User {callback.from_user.id} set exit timeframe: {timeframe}")

    await state.clear()

    user_settings = db.get_user_settings(callback.from_user.id)
    entry_tf = user_settings.get('entry_timeframe') if user_settings else None
    exit_tf = user_settings.get('exit_timeframe') if user_settings else None

    entry_text = entry_tf if entry_tf else "❌ Не установлен"
    exit_text = exit_tf if exit_tf else "❌ Не установлен"

    await callback.message.edit_text(
        f"⏱️ Настройка таймфреймов\n\n"
        f"📈 ТФ входа: {entry_text}\n"
        f"📉 ТФ выхода: {exit_text}\n\n"
        f"Поддерживаемые ТФ: 5m, 15m, 45m, 50m, 55m, 1h, 2h, 3h, 4h",
        reply_markup=get_timeframes_menu()
    )


@router.callback_query(F.data == "settings_duration")
async def set_bot_duration(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🕒 Введите время работы бота в часах:\n\n"
        "Например: 168 (неделя), 24 (сутки)",
        reply_markup=get_back_to_settings()
    )
    await state.set_state(SettingsStates.waiting_for_bot_duration)
    await state.update_data(message_id=callback.message.message_id)
    await callback.answer()


@router.message(SettingsStates.waiting_for_bot_duration)
async def process_bot_duration(message: Message, state: FSMContext):
    data = await state.get_data()
    message_id = data.get('message_id')
    await message.delete()

    try:
        duration = int(message.text.strip())
        if duration <= 0:
            await message.bot.edit_message_text(
                "❌ Время работы должно быть больше 0. Попробуйте еще раз:",
                chat_id=message.chat.id,
                message_id=message_id,
                reply_markup=get_back_to_settings()
            )
            return
    except ValueError:
        await message.bot.edit_message_text(
            "❌ Введите корректное число часов. Попробуйте еще раз:",
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=get_back_to_settings()
        )
        return

    db.update_user_settings(message.from_user.id, bot_duration_hours=duration)
    await state.clear()
    logger.info(f"User {message.from_user.id} set bot duration: {duration} hours")
    await show_settings_menu_after_update(message, message_id)
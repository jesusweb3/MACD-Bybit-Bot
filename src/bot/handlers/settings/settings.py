# src/bot/handlers/settings/settings.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from src.bot.keyboards.settings_menu import (
    get_settings_menu, get_api_menu, get_leverage_menu,
    get_timeframe_menu, get_back_to_settings
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
        return 0, 5

    filled_settings = []

    # API ключи
    if user_settings.get('bybit_api_key') and user_settings.get('bybit_secret_key'):
        filled_settings.append('api')

    # Торговая пара
    if user_settings.get('trading_pair'):
        filled_settings.append('pair')

    # Плечо
    if user_settings.get('leverage'):
        filled_settings.append('leverage')

    # Размер позиции
    position_size_info = db.get_position_size_info(telegram_id)
    if position_size_info and position_size_info.get('value') is not None and position_size_info.get('value') > 0:
        filled_settings.append('position_size')

    # Таймфрейм
    if user_settings.get('timeframe'):
        filled_settings.append('timeframe')

    filled_count = len(filled_settings)
    total_count = 5

    return filled_count, total_count


def format_setting_display(value, setting_name: str = "") -> str:
    """Форматирование значения настройки для отображения"""
    if setting_name == "api_status":
        return "✅ Настроено" if value else "—"

    if value is None or value == "" or (isinstance(value, (int, float)) and value == 0):
        return "—"

    if setting_name in ["leverage"]:
        return f"{value}x"
    else:
        return str(value)


def parse_position_size_input(user_input: str) -> dict:
    """Парсинг ввода пользователя для размера позиции"""
    try:
        text = user_input.strip().upper()

        if text.endswith('%'):
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
        filled_count, total_count = count_filled_settings(user_settings, callback.from_user.id)
        progress_bar = get_progress_bar(filled_count, total_count)

        # API статус
        api_status = bool(user_settings.get('bybit_api_key') and user_settings.get('bybit_secret_key'))

        # Размер позиции
        position_size_info = db.get_position_size_info(callback.from_user.id)
        position_size_display = position_size_info.get('display', '—')

        settings_text = (
            f"🔧 Настройки бота\n\n"
            f"Настройки заполнены: {filled_count}/{total_count} {progress_bar}\n\n"
            f"🔑 API ключи: {format_setting_display(api_status, 'api_status')}\n"
            f"💰 Пара: {format_setting_display(user_settings.get('trading_pair'))}\n"
            f"⚡ Плечо: {format_setting_display(user_settings.get('leverage'), 'leverage')}\n"
            f"📊 Размер позиции: {position_size_display}\n"
            f"⏱️ Таймфрейм: {format_setting_display(user_settings.get('timeframe'))}"
        )

    await callback.message.edit_text(settings_text, reply_markup=get_settings_menu())


async def show_settings_menu_after_update(message: Message, message_id: int):
    user_settings = db.get_user_settings(message.from_user.id)

    filled_count, total_count = count_filled_settings(user_settings, message.from_user.id)
    progress_bar = get_progress_bar(filled_count, total_count)

    # API статус
    api_status = bool(user_settings.get('bybit_api_key') and user_settings.get('bybit_secret_key'))

    # Размер позиции
    position_size_info = db.get_position_size_info(message.from_user.id)
    position_size_display = position_size_info.get('display', '—')

    settings_text = (
        f"🔧 Настройки бота\n\n"
        f"Настройки заполнены: {filled_count}/{total_count} {progress_bar}\n\n"
        f"🔑 API ключи: {format_setting_display(api_status, 'api_status')}\n"
        f"💰 Пара: {format_setting_display(user_settings.get('trading_pair'))}\n"
        f"⚡ Плечо: {format_setting_display(user_settings.get('leverage'), 'leverage')}\n"
        f"📊 Размер позиции: {position_size_display}\n"
        f"⏱️ Таймфрейм: {format_setting_display(user_settings.get('timeframe'))}"
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


# API обработчики
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
    logger.info(f"⚙️ Пользователь {message.from_user.id} обновил API ключ")

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
    logger.info(f"⚙️ Пользователь {message.from_user.id} обновил Secret ключ")

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
    logger.info(f"⚙️ Пользователь {message.from_user.id} установил торговую пару: {pair}")
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
    logger.info(f"⚙️ Пользователь {callback.from_user.id} установил плечо: {leverage}x")
    await show_settings_menu(callback)


@router.callback_query(F.data == "settings_position_size")
async def set_position_size(callback: CallbackQuery, state: FSMContext):
    position_size_info = db.get_position_size_info(callback.from_user.id)
    current_display = position_size_info.get('display', '—')

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
    logger.info(f"⚙️ Пользователь {message.from_user.id} установил размер позиции: {parse_result['display']}")
    await show_settings_menu_after_update(message, message_id)


@router.callback_query(F.data == "settings_timeframe")
async def timeframe_menu(callback: CallbackQuery):
    """Упрощенное меню выбора единого таймфрейма"""
    user_settings = db.get_user_settings(callback.from_user.id)
    current_timeframe = user_settings.get('timeframe') if user_settings else None

    current_text = current_timeframe if current_timeframe else "❌ Не установлен"

    await callback.message.edit_text(
        f"⏱️ Выберите таймфрейм для MACD стратегии\n\n"
        f"📊 Текущий: {current_text}\n\n"
        f"Поддерживаемые: 5m, 45m",
        reply_markup=get_timeframe_menu()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tf_"))
async def process_timeframe(callback: CallbackQuery):
    """Обработка выбора таймфрейма"""
    timeframe = callback.data.split("_")[1]

    # Проверяем что таймфрейм поддерживается
    if timeframe not in ["5m", "45m"]:
        await callback.answer("❌ Неподдерживаемый таймфрейм", show_alert=True)
        return

    # Сохраняем единый таймфрейм
    db.update_user_settings(callback.from_user.id, timeframe=timeframe)
    await callback.answer(f"✅ Таймфрейм установлен: {timeframe}")
    logger.info(f"⚙️ Пользователь {callback.from_user.id} установил таймфрейм: {timeframe}")

    # Возвращаемся в главное меню настроек
    await show_settings_menu(callback)
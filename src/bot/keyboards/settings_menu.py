# src/bot/keyboards/settings_menu.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_settings_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="🔑 API ключи", callback_data="settings_api"),
            InlineKeyboardButton(text="💰 Торговая пара", callback_data="settings_pair")
        ],
        [
            InlineKeyboardButton(text="⚡ Плечо", callback_data="settings_leverage"),
            InlineKeyboardButton(text="📊 Размер позиции", callback_data="settings_position_size")
        ],
        [
            InlineKeyboardButton(text="⚙️ TP/SL", callback_data="settings_tp_sl"),
            InlineKeyboardButton(text="⏱️ Таймфреймы", callback_data="settings_timeframes")
        ],
        [
            InlineKeyboardButton(text="🕒 Время работы", callback_data="settings_duration")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_api_menu() -> InlineKeyboardMarkup:
    """Меню настройки API ключей"""
    keyboard = [
        [
            InlineKeyboardButton(text="🔑 API ключ", callback_data="set_api_key"),
            InlineKeyboardButton(text="🔐 Secret ключ", callback_data="set_secret_key")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_leverage_menu() -> InlineKeyboardMarkup:
    """Клавиатура плеча: от 3x до 10x"""
    keyboard = [
        [
            InlineKeyboardButton(text="3x", callback_data="leverage_3"),
            InlineKeyboardButton(text="4x", callback_data="leverage_4"),
            InlineKeyboardButton(text="5x", callback_data="leverage_5"),
            InlineKeyboardButton(text="6x", callback_data="leverage_6")
        ],
        [
            InlineKeyboardButton(text="7x", callback_data="leverage_7"),
            InlineKeyboardButton(text="8x", callback_data="leverage_8"),
            InlineKeyboardButton(text="9x", callback_data="leverage_9"),
            InlineKeyboardButton(text="10x", callback_data="leverage_10")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_tp_sl_menu(is_enabled: bool = False) -> InlineKeyboardMarkup:
    """Меню настройки TP/SL с переключателем"""
    toggle_text = "🔴 Выключить" if is_enabled else "🟢 Включить"
    toggle_data = "tp_sl_disable" if is_enabled else "tp_sl_enable"

    keyboard = [
        [
            InlineKeyboardButton(text="🎯 Тейк профит", callback_data="set_take_profit"),
            InlineKeyboardButton(text="🛑 Стоп лосс", callback_data="set_stop_loss")
        ],
        [
            InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_timeframes_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="📈 ТФ входа", callback_data="set_entry_timeframe"),
            InlineKeyboardButton(text="📉 ТФ выхода", callback_data="set_exit_timeframe")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_timeframe_selection() -> InlineKeyboardMarkup:
    """Клавиатура с поддерживаемыми таймфреймами: 5m, 15m, 45m, 50m, 55m, 1h, 2h, 3h, 4h"""
    keyboard = [
        [
            InlineKeyboardButton(text="5m", callback_data="tf_5m"),
            InlineKeyboardButton(text="15m", callback_data="tf_15m"),
            InlineKeyboardButton(text="45m", callback_data="tf_45m")
        ],
        [
            InlineKeyboardButton(text="50m", callback_data="tf_50m"),
            InlineKeyboardButton(text="55m", callback_data="tf_55m"),
            InlineKeyboardButton(text="1h", callback_data="tf_1h")
        ],
        [
            InlineKeyboardButton(text="2h", callback_data="tf_2h"),
            InlineKeyboardButton(text="3h", callback_data="tf_3h"),
            InlineKeyboardButton(text="4h", callback_data="tf_4h")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="settings_timeframes")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_settings() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🔙 К настройкам", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_tp_sl() -> InlineKeyboardMarkup:
    """Кнопка возврата к меню TP/SL"""
    keyboard = [
        [InlineKeyboardButton(text="🔙 К TP/SL", callback_data="settings_tp_sl")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
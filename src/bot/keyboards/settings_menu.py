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
            InlineKeyboardButton(text="⏱️ Таймфрейм", callback_data="settings_timeframe")
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


def get_back_to_settings() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🔙 К настройкам", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_timeframe_menu() -> InlineKeyboardMarkup:
    """Меню выбора таймфрейма"""
    keyboard = [
        [
            InlineKeyboardButton(text="5m", callback_data="tf_5m"),
            InlineKeyboardButton(text="45m", callback_data="tf_45m")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
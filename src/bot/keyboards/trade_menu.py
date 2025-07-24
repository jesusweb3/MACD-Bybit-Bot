# src/bot/keyboards/trade_menu.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_trade_menu() -> InlineKeyboardMarkup:
    """Торговое меню (заглушка)"""
    keyboard = [
        [
            InlineKeyboardButton(text="🚧 Стратегии", callback_data="strategies_placeholder"),
            InlineKeyboardButton(text="🚧 Статистика", callback_data="stats_placeholder")
        ],
        [
            InlineKeyboardButton(text="🚧 Позиции", callback_data="positions_placeholder"),
            InlineKeyboardButton(text="🚧 История", callback_data="history_placeholder")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_trade_menu() -> InlineKeyboardMarkup:
    """Кнопка возврата к торговому меню"""
    keyboard = [
        [InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_strategies_menu() -> InlineKeyboardMarkup:
    """Заглушка меню стратегий"""
    keyboard = [
        [
            InlineKeyboardButton(text="🚧 MACD Full", callback_data="strategy_full_placeholder"),
            InlineKeyboardButton(text="🚧 MACD Long", callback_data="strategy_long_placeholder")
        ],
        [
            InlineKeyboardButton(text="🚧 MACD Short", callback_data="strategy_short_placeholder")
        ],
        [
            InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_positions_menu() -> InlineKeyboardMarkup:
    """Заглушка меню позиций"""
    keyboard = [
        [
            InlineKeyboardButton(text="🚧 Текущие", callback_data="current_positions_placeholder"),
            InlineKeyboardButton(text="🚧 История", callback_data="positions_history_placeholder")
        ],
        [
            InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
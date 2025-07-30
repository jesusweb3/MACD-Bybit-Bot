# src/bot/keyboards/trade_menu.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_trade_menu(settings_complete: bool = False) -> InlineKeyboardMarkup:
    """
    Главное торговое меню

    Args:
        settings_complete: Завершены ли все настройки
    """
    # Кнопка стратегии - активна только если настройки завершены
    if settings_complete:
        strategy_button = InlineKeyboardButton(
            text="🎯 Запустить MACD Full",
            callback_data="trade_strategy_menu"
        )
    else:
        strategy_button = InlineKeyboardButton(
            text="🔒 Запустить MACD Full",
            callback_data="trade_strategy_blocked"
        )

    keyboard = [
        [strategy_button],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="trade_statistics"),
            InlineKeyboardButton(text="💰 Баланс счёта", callback_data="trade_balance")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_strategy_confirm_menu(strategy_name: str) -> InlineKeyboardMarkup:
    """Меню подтверждения запуска MACD Full стратегии"""
    keyboard = [
        [
            InlineKeyboardButton(text="🚀 Запустить торговлю", callback_data=f"start_trading_{strategy_name}"),
        ],
        [
            InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_active_trading_menu() -> InlineKeyboardMarkup:
    """Меню во время активной торговли"""
    keyboard = [
        [
            InlineKeyboardButton(text="⏹️ Остановить торговлю", callback_data="stop_trading"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="trade_statistics"),
            InlineKeyboardButton(text="💰 Баланс", callback_data="trade_balance")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_statistics_menu() -> InlineKeyboardMarkup:
    """Меню статистики"""
    keyboard = [
        [
            InlineKeyboardButton(text="📋 История сделок", callback_data="trade_history")
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="trade_statistics")
        ],
        [
            InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_trade_history_menu() -> InlineKeyboardMarkup:
    """Меню истории сделок"""
    keyboard = [
        [
            InlineKeyboardButton(text="🔄 Обновить историю", callback_data="refresh_trade_history")
        ],
        [
            InlineKeyboardButton(text="📊 К статистике", callback_data="trade_statistics"),
            InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_balance_menu() -> InlineKeyboardMarkup:
    """Меню баланса"""
    keyboard = [
        [
            InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="refresh_balance")
        ],
        [
            InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_trade_menu() -> InlineKeyboardMarkup:
    """Кнопка возврата к торговому меню"""
    keyboard = [
        [InlineKeyboardButton(text="🔙 К торговле", callback_data="trade_menu")]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
# src/bot/keyboards/start_menu.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_start_menu() -> InlineKeyboardMarkup:
    """
    Главное стартовое меню бота
    """
    keyboard = [
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
        ],
        [
            InlineKeyboardButton(text="📈 Торговля", callback_data="trade_menu")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_start_menu() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное стартовое меню"""
    keyboard = [
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="start_menu")]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
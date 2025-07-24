# src/bot/handlers/start/start.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from src.bot.keyboards.start_menu import get_start_menu, get_back_to_start_menu
from src.database.database import db
from src.utils.logger import logger
from src.utils.config import config

router = Router()


@router.message(CommandStart())
async def start_command(message: Message):
    """Обработчик команды /start"""
    # Тихо игнорируем неавторизованных пользователей
    if not config.is_user_allowed(message.from_user.id):
        logger.warning(
            f"Unauthorized access attempt from user {message.from_user.id} (@{message.from_user.username}) - ignored silently")
        return

    # Создаем или получаем пользователя
    db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )

    welcome_text = (
        f"👋 Добро пожаловать!\n\n"
        "🤖 Это твой личный торговый бот для Bybit\n"
        "📊 Бот будет торговать на основе твоих настроек\n\n"
        "⚙️ Сначала настрой все параметры в разделе «Настройки»"
    )

    await message.answer(welcome_text, reply_markup=get_start_menu())
    logger.info(f"User {message.from_user.id} started bot")


@router.callback_query(F.data == "start_menu")
async def start_menu_callback(callback: CallbackQuery):
    """Возврат к стартовому меню"""
    # Тихо игнорируем неавторизованных пользователей
    if not config.is_user_allowed(callback.from_user.id):
        logger.warning(f"Unauthorized callback from user {callback.from_user.id} - ignored silently")
        return  # Никакого ответа в callback

    await callback.message.edit_text(
        "🏠 Главное меню\n\nВыберите действие:",
        reply_markup=get_start_menu()
    )
    await callback.answer()


# Заглушка для торговли
@router.callback_query(F.data == "trade_menu")
async def trade_menu_callback(callback: CallbackQuery):
    """Временная заглушка для торгового меню"""
    if not config.is_user_allowed(callback.from_user.id):
        logger.warning(f"Unauthorized callback from user {callback.from_user.id} - ignored silently")
        return

    await callback.message.edit_text(
        "📈 Торговое меню\n\n"
        "🚧 Функционал находится в разработке\n\n"
        "Скоро здесь будут доступны торговые стратегии!",
        reply_markup=get_back_to_start_menu()
    )
    await callback.answer()


# Универсальная функция возврата в стартовое меню для других модулей
async def return_to_start_menu(callback: CallbackQuery, message: str = "🏠 Главное меню\n\nВыберите действие:"):
    """
    Универсальная функция возврата в стартовое меню

    Args:
        callback: CallbackQuery объект
        message: Текст сообщения (опционально)
    """
    if not config.is_user_allowed(callback.from_user.id):
        return

    await callback.message.edit_text(
        message,
        reply_markup=get_start_menu()
    )
    await callback.answer()
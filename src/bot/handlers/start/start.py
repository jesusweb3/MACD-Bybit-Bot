# src/bot/handlers/start/start.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from src.bot.keyboards.start_menu import get_start_menu, get_back_to_start_menu
from src.database.database import db
from src.utils.logger import logger
from src.utils.config import config
from src.utils.helpers import format_msk_time

router = Router()


@router.message(CommandStart())
async def start_command(message: Message):
    """Обработчик команды /start"""
    # Тихо игнорируем неавторизованных пользователей
    if not config.is_user_allowed(message.from_user.id):
        current_time_msk = format_msk_time()
        logger.warning(
            f"🚫 Неавторизованный доступ от пользователя {message.from_user.id} (@{message.from_user.username}) в {current_time_msk} МСК")
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

    current_time_msk = format_msk_time()
    logger.info(f"👋 Пользователь {message.from_user.id} запустил бота в {current_time_msk} МСК")


@router.callback_query(F.data == "start_menu")
async def start_menu_callback(callback: CallbackQuery):
    """Возврат к стартовому меню"""
    # Тихо игнорируем неавторизованных пользователей
    if not config.is_user_allowed(callback.from_user.id):
        current_time_msk = format_msk_time()
        logger.warning(f"🚫 Неавторизованный callback от пользователя {callback.from_user.id} в {current_time_msk} МСК")
        return  # Никакого ответа в callback

    await callback.message.edit_text(
        "🏠 Главное меню\n\nВыберите действие:",
        reply_markup=get_start_menu()
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
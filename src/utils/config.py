# src/utils/config.py
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Конфигурация торгового скрипта без Telegram"""

    # Bybit API
    bybit_api_key: str
    bybit_secret_key: str

    # Торговые настройки
    trading_pair: str
    leverage: int
    timeframe: str  # 5m или 45m

    # Размер позиции (фиксированная сумма в USDT)
    position_size_usdt: float

    # База данных и логи
    database_url: str = "sqlite:///trading_bot.db"
    log_level: str = "INFO"

    # Дополнительные настройки
    environment: str = "production"  # production или testnet

    @classmethod
    def from_env(cls) -> "Config":
        """Создание конфигурации из переменных окружения"""

        # Обязательные параметры
        bybit_api_key = os.getenv("BYBIT_API_KEY", "")
        bybit_secret_key = os.getenv("BYBIT_SECRET_KEY", "")
        trading_pair = os.getenv("TRADING_PAIR", "")

        if not bybit_api_key:
            raise ValueError("BYBIT_API_KEY не найден в переменных окружения")
        if not bybit_secret_key:
            raise ValueError("BYBIT_SECRET_KEY не найден в переменных окружения")
        if not trading_pair:
            raise ValueError("TRADING_PAIR не найден в переменных окружения")

        # Парсим leverage
        try:
            leverage = int(os.getenv("LEVERAGE", "5"))
            if not (3 <= leverage <= 10):
                raise ValueError("LEVERAGE должно быть от 3 до 10")
        except ValueError as e:
            raise ValueError(f"Некорректное значение LEVERAGE: {e}")

        # Парсим timeframe
        timeframe = os.getenv("TIMEFRAME", "5m")
        if timeframe not in ["5m", "45m"]:
            raise ValueError("TIMEFRAME должен быть '5m' или '45m'")

        # Парсим размер позиции (только USDT)
        try:
            position_size_usdt = float(os.getenv("POSITION_SIZE_USDT", "15"))
            if position_size_usdt <= 0:
                raise ValueError("POSITION_SIZE_USDT должен быть больше 0")
        except ValueError as e:
            raise ValueError(f"Некорректное значение POSITION_SIZE_USDT: {e}")

        return cls(
            bybit_api_key=bybit_api_key,
            bybit_secret_key=bybit_secret_key,
            trading_pair=trading_pair.upper(),
            leverage=leverage,
            timeframe=timeframe,
            position_size_usdt=position_size_usdt,
            database_url=os.getenv("DATABASE_URL", "sqlite:///trading_bot.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            environment=os.getenv("ENVIRONMENT", "production")
        )

    def validate(self) -> bool:
        """Валидация всех настроек"""
        errors = []

        # Проверяем API ключи
        if len(self.bybit_api_key) < 10:
            errors.append("BYBIT_API_KEY слишком короткий")
        if len(self.bybit_secret_key) < 10:
            errors.append("BYBIT_SECRET_KEY слишком короткий")

        # Проверяем торговую пару
        if not self.trading_pair.endswith("USDT"):
            errors.append("TRADING_PAIR должна заканчиваться на USDT")

        if errors:
            raise ValueError("Ошибки конфигурации:\n" + "\n".join(f"- {error}" for error in errors))

        return True

    def get_position_size_display(self) -> str:
        """Получение отображаемого размера позиции"""
        return f"{self.position_size_usdt} USDT"

    def print_config(self) -> None:
        """Вывод конфигурации для проверки"""
        print("=" * 50)
        print("КОНФИГУРАЦИЯ ТОРГОВОГО БОТА")
        print("=" * 50)
        print(f"Торговая пара: {self.trading_pair}")
        print(f"Плечо: {self.leverage}x")
        print(f"Таймфрейм: {self.timeframe}")
        print(f"Размер позиции: {self.get_position_size_display()}")
        print(f"Среда: {self.environment}")
        print(f"API ключ: {self.bybit_api_key[:8]}...{self.bybit_api_key[-4:]}")
        print(f"База данных: {self.database_url}")
        print(f"Уровень логов: {self.log_level}")
        print("=" * 50)


# Глобальный экземпляр конфигурации
config = Config.from_env()
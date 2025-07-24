# src/utils/config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    telegram_token: str
    database_url: str
    log_level: str = "INFO"
    allowed_users: list[int] = None

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            database_url=os.getenv("DATABASE_URL", "sqlite:///bot.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            allowed_users=cls._parse_allowed_users(os.getenv("ALLOWED_USERS", ""))
        )

    @staticmethod
    def _parse_allowed_users(users_str: str) -> list[int]:
        if not users_str:
            return []
        try:
            return [int(user_id.strip()) for user_id in users_str.split(",") if user_id.strip()]
        except ValueError:
            return []

    def is_user_allowed(self, user_id: int) -> bool:
        return not self.allowed_users or user_id in self.allowed_users


config = Config.from_env()
# src/utils/logger.py
import logging
import sys
from pathlib import Path
from datetime import datetime
from .config import config
from .helpers import MSK_TIMEZONE


class MSKFormatter(logging.Formatter):
    """Форматтер с московским временем"""

    def formatTime(self, record, datefmt=None):
        # Конвертируем время записи в московское время
        dt = datetime.fromtimestamp(record.created, tz=MSK_TIMEZONE)
        if datefmt:
            return dt.strftime(datefmt)
        else:
            return dt.strftime('%Y-%m-%d %H:%M:%S MSK')


def setup_logger(name: str = __name__) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, config.log_level))

    # Используем кастомный форматтер с московским временем
    formatter = MSKFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S MSK'
    )

    # Консольный handler с UTF-8 для Windows
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Устанавливаем UTF-8 для Windows
    if sys.platform == "win32":
        console_handler.stream.reconfigure(encoding='utf-8')

    logger.addHandler(console_handler)

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Файловый handler с UTF-8
    file_handler = logging.FileHandler(log_dir / "bot.log", encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger("macd_bot")
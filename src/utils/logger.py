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
    """Настройка логгера с поддержкой московского времени и оптимизацией для торговли"""
    logger = logging.getLogger(name)

    # Проверяем что логгер еще не настроен
    if logger.handlers:
        return logger

    # Устанавливаем уровень логирования
    logger.setLevel(getattr(logging, config.log_level))

    # Создаем кастомный форматтер с московским временем
    formatter = MSKFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S MSK'
    )

    # === КОНСОЛЬНЫЙ ВЫВОД ===
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Устанавливаем UTF-8 для Windows
    if sys.platform == "win32" and hasattr(console_handler.stream, 'reconfigure'):
        try:
            console_handler.stream.reconfigure(encoding='utf-8')
        except (AttributeError, OSError):
            # Fallback для старых версий Python или системных ограничений
            pass

    logger.addHandler(console_handler)

    # === ФАЙЛОВОЕ ЛОГИРОВАНИЕ ===
    try:
        # Создаем директорию для логов
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Основной файл логов
        main_log_file = log_dir / "bot.log"
        file_handler = logging.FileHandler(main_log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)

        # Устанавливаем уровень для файла - можно сделать более детальным
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

        # === ДОПОЛНИТЕЛЬНЫЕ ФАЙЛЫ ЛОГОВ ===

        # Лог только ошибок
        error_log_file = log_dir / "errors.log"
        error_handler = logging.FileHandler(error_log_file, encoding='utf-8')
        error_handler.setFormatter(formatter)
        error_handler.setLevel(logging.ERROR)
        logger.addHandler(error_handler)

        # Лог торговых операций (только INFO+ с ключевыми словами)
        trade_log_file = log_dir / "trading.log"
        trade_handler = TradingLogHandler(trade_log_file)
        trade_handler.setFormatter(formatter)
        trade_handler.setLevel(logging.INFO)
        logger.addHandler(trade_handler)

    except (OSError, PermissionError) as e:
        # Если не можем создать файлы логов - продолжаем только с консольным выводом
        logger.warning(f"⚠️ Не удалось настроить файловое логирование: {e}")

    return logger


class TradingLogHandler(logging.FileHandler):
    """Специальный обработчик для логирования торговых операций"""

    def __init__(self, filename, mode='a', encoding='utf-8', delay=False):
        super().__init__(filename, mode, encoding, delay)

        # Ключевые слова для торговых операций
        self.trading_keywords = [
            'ПЕРЕСЕЧЕНИЕ MACD',
            'сигнал',
            'позиция открыта',
            'позиция закрыта',
            'Запуск MACD стратегии',
            'Остановка MACD стратегии',
            'Размещаем маркет ордер',
            'Маркет ордер размещен',
            'Завершен',  # для завершения интервалов
            'Начат новый',  # для начала интервалов
            'Записана сделка',
            'LONG позиция',
            'SHORT позиция',
            'Баланс счёта'
        ]

    def emit(self, record):
        """Записываем только торговые сообщения"""
        if record.levelno >= logging.INFO:
            message = record.getMessage()

            # Проверяем содержит ли сообщение торговые ключевые слова
            if any(keyword in message for keyword in self.trading_keywords):
                super().emit(record)


def get_logger_stats() -> dict:
    """НОВАЯ ФУНКЦИЯ: Получение статистики логирования"""
    try:
        log_dir = Path("logs")
        if not log_dir.exists():
            return {"error": "Директория логов не найдена"}

        stats = {}

        # Размеры файлов логов
        for log_file in log_dir.glob("*.log"):
            try:
                size_mb = log_file.stat().st_size / (1024 * 1024)
                stats[log_file.name] = f"{size_mb:.2f} MB"
            except OSError:
                stats[log_file.name] = "недоступен"

        return stats

    except Exception as e:
        return {"error": f"Ошибка получения статистики: {e}"}


def cleanup_old_logs(days_to_keep: int = 7):
    """НОВАЯ ФУНКЦИЯ: Очистка старых логов"""
    try:
        log_dir = Path("logs")
        if not log_dir.exists():
            return

        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        cleaned_count = 0
        for log_file in log_dir.glob("*.log.*"):  # Ротированные логи (.log.1, .log.2 и т.д.)
            try:
                if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_date:
                    log_file.unlink()
                    cleaned_count += 1
            except OSError:
                continue

        if cleaned_count > 0:
            logger = logging.getLogger(__name__)
            logger.info(f"🧹 Очищено {cleaned_count} старых файлов логов (старше {days_to_keep} дней)")

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка очистки логов: {e}")


def rotate_logs_if_needed():
    """НОВАЯ ФУНКЦИЯ: Ротация логов при превышении размера"""
    try:
        log_dir = Path("logs")
        if not log_dir.exists():
            return

        max_size_mb = 10  # Максимальный размер файла лога в MB
        max_size_bytes = max_size_mb * 1024 * 1024

        for log_file in log_dir.glob("*.log"):
            try:
                if log_file.stat().st_size > max_size_bytes:
                    # Простая ротация - переименовываем в .log.old
                    old_log = log_file.with_suffix('.log.old')
                    if old_log.exists():
                        old_log.unlink()  # Удаляем старый бэкап

                    log_file.rename(old_log)

                    logger = logging.getLogger(__name__)
                    logger.info(f"🔄 Ротирован лог файл: {log_file.name} (размер превысил {max_size_mb}MB)")

            except OSError:
                continue

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка ротации логов: {e}")


# Основной логгер для использования в проекте
logger = setup_logger("macd_bot")

# Инициализация - проверяем и ротируем логи при запуске
try:
    rotate_logs_if_needed()
    cleanup_old_logs(days_to_keep=7)  # Храним логи 7 дней
except Exception:
    # Не критично если не получилось
    pass
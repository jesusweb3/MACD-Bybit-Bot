# src/utils/helpers.py
from typing import Union


def format_balance(balance: Union[float, int, str]) -> str:
    """
    Форматирование баланса для отображения с разделителями тысяч
    """
    try:
        # Преобразуем в float если это строка
        if isinstance(balance, str):
            balance = float(balance)
        elif isinstance(balance, int):
            balance = float(balance)

        # Обрабатываем отрицательные значения
        is_negative = balance < 0
        abs_balance = abs(balance)

        # Для очень маленьких значений (меньше 0.01) показываем больше знаков
        if 0 < abs_balance < 0.01:
            if abs_balance >= 0.001:
                formatted = f"{abs_balance:.5f}".rstrip('0').rstrip('.')
            else:
                formatted = f"{abs_balance:.8f}".rstrip('0').rstrip('.')
        # Для больших значений используем разделители тысяч
        elif abs_balance >= 1000:
            formatted = f"{abs_balance:,.2f}"
        # Для обычных значений стандартное форматирование
        else:
            formatted = f"{abs_balance:.2f}"

        # Добавляем знак минус обратно если было отрицательное значение
        if is_negative:
            formatted = f"-{formatted}"

        return formatted

    except (ValueError, TypeError):
        # Если не удалось преобразовать, возвращаем как есть
        return str(balance)


def format_usdt(amount: Union[float, int, str], with_currency: bool = True) -> str:
    """
    Специальное форматирование для USDT с валютой

    Args:
        amount: Сумма в USDT
        with_currency: Добавлять ли " USDT" в конце

    Returns:
        Отформатированная строка

    Examples:
        format_usdt(1234.56) -> "1,234.56 USDT"
        format_usdt(1234.56, False) -> "1,234.56"
        format_usdt(0.00123) -> "0.00123 USDT"
    """
    formatted = format_balance(amount)

    if with_currency:
        return f"{formatted} USDT"
    else:
        return formatted


def format_percentage(value: Union[float, int, str], decimal_places: int = 2) -> str:
    """
    Форматирование процентов

    Args:
        value: Значение в процентах
        decimal_places: Количество знаков после запятой

    Returns:
        Отформатированная строка с %

    Examples:
        format_percentage(75.5) -> "75.50%"
        format_percentage(100) -> "100.00%"
        format_percentage(0.123, 3) -> "0.123%"
    """
    try:
        if isinstance(value, str):
            value = float(value)
        elif isinstance(value, int):
            value = float(value)

        return f"{value:.{decimal_places}f}%"

    except (ValueError, TypeError):
        return f"{value}%"


def format_pnl(pnl: Union[float, int, str], with_currency: bool = True, with_sign: bool = True) -> str:
    """
    Форматирование P&L с правильными знаками и цветовыми эмодзи

    Args:
        pnl: Значение P&L
        with_currency: Добавлять ли " USDT"
        with_sign: Добавлять ли знак + для положительных значений

    Returns:
        Отформатированная строка с эмодзи

    Examples:
        format_pnl(123.45) -> "💚 +123.45 USDT"
        format_pnl(-50.25) -> "💔 -50.25 USDT"
        format_pnl(0) -> "💙 0.00 USDT"
    """
    try:
        if isinstance(pnl, str):
            pnl = float(pnl)
        elif isinstance(pnl, int):
            pnl = float(pnl)

        # Выбираем эмодзи в зависимости от значения
        if pnl > 0:
            emoji = "💚"
            sign = "+" if with_sign else ""
        elif pnl < 0:
            emoji = "💔"
            sign = ""  # Минус уже включен в число
        else:
            emoji = "💙"
            sign = ""

        formatted_amount = format_balance(abs(pnl) if pnl > 0 else pnl)

        if with_currency:
            return f"{emoji} {sign}{formatted_amount} USDT"
        else:
            return f"{emoji} {sign}{formatted_amount}"

    except (ValueError, TypeError):
        return f"💙 {pnl}"


def format_quantity(quantity: Union[float, int, str], precision: int = 8) -> str:
    """
    Форматирование количества для торговых операций

    Args:
        quantity: Количество
        precision: Максимальная точность (знаков после запятой)

    Returns:
        Отформатированная строка без лишних нулей

    Examples:
        format_quantity(1.50000000) -> "1.5"
        format_quantity(0.00012345) -> "0.00012345"
        format_quantity(1000) -> "1,000"
    """
    try:
        if isinstance(quantity, str):
            quantity = float(quantity)
        elif isinstance(quantity, int):
            quantity = float(quantity)

        # Для целых чисел
        if quantity == int(quantity):
            return format_balance(int(quantity)).replace('.00', '')

        # Для дробных чисел убираем лишние нули
        formatted = f"{quantity:.{precision}f}".rstrip('0').rstrip('.')

        # Применяем форматирование для больших чисел
        if float(formatted) >= 1000:
            return format_balance(float(formatted))
        else:
            return formatted

    except (ValueError, TypeError):
        return str(quantity)


def format_price(price: Union[float, int, str], symbol: str = "") -> str:
    """
    Форматирование цены в зависимости от торговой пары

    Args:
        price: Цена
        symbol: Торговая пара (например, BTCUSDT)

    Returns:
        Отформатированная цена

    Examples:
        format_price(43250.5, "BTCUSDT") -> "43,250.50"
        format_price(0.00123, "ADAUSDT") -> "0.00123"
    """
    try:
        if isinstance(price, str):
            price = float(price)
        elif isinstance(price, int):
            price = float(price)

        # Определяем точность в зависимости от пары
        if symbol.upper().endswith("USDT"):
            base_asset = symbol.upper().replace("USDT", "")

            # Для дорогих активов (BTC, ETH) - 2 знака
            if base_asset in ["BTC", "ETH", "BNB"]:
                precision = 2
            # Для дешевых активов - больше знаков
            elif price < 1:
                precision = 6
            else:
                precision = 4
        else:
            # По умолчанию
            precision = 4

        # Форматируем с нужной точностью
        if price >= 1000:
            return f"{price:,.{precision}f}".rstrip('0').rstrip('.')
        else:
            return f"{price:.{precision}f}".rstrip('0').rstrip('.')

    except (ValueError, TypeError):
        return str(price)


def get_balance_emoji(balance: Union[float, int, str]) -> str:
    """
    Получение эмодзи в зависимости от размера баланса

    Args:
        balance: Баланс в USDT

    Returns:
        Эмодзи для баланса
    """
    try:
        if isinstance(balance, str):
            balance = float(balance)
        elif isinstance(balance, int):
            balance = float(balance)

        if balance >= 10000:
            return "💎"  # Большой баланс
        elif balance >= 1000:
            return "💚"  # Хороший баланс
        elif balance >= 100:
            return "💛"  # Средний баланс
        elif balance >= 10:
            return "🧡"  # Небольшой баланс
        elif balance > 0:
            return "💔"  # Очень маленький баланс
        else:
            return "💀"  # Нет баланса

    except (ValueError, TypeError):
        return "💙"  # По умолчанию


def truncate_string(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Обрезание строки с добавлением суффикса

    Args:
        text: Исходная строка
        max_length: Максимальная длина
        suffix: Что добавить в конце при обрезании

    Returns:
        Обрезанная строка
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def format_duration(hours: Union[int, float]) -> str:
    """
    Форматирование продолжительности в удобочитаемый вид

    Args:
        hours: Количество часов

    Returns:
        Форматированная строка

    Examples:
        format_duration(24) -> "1 день"
        format_duration(168) -> "1 неделя"
        format_duration(36) -> "1 день 12 часов"
    """
    try:
        hours = int(hours)

        if hours == 0:
            return "0 часов"

        weeks = hours // 168
        days = (hours % 168) // 24
        remaining_hours = hours % 24

        parts = []

        if weeks > 0:
            parts.append(f"{weeks} {'неделя' if weeks == 1 else 'недель' if weeks < 5 else 'недель'}")

        if days > 0:
            parts.append(f"{days} {'день' if days == 1 else 'дня' if days < 5 else 'дней'}")

        if remaining_hours > 0:
            parts.append(
                f"{remaining_hours} {'час' if remaining_hours == 1 else 'часа' if remaining_hours < 5 else 'часов'}")

        return " ".join(parts)

    except (ValueError, TypeError):
        return f"{hours} часов"
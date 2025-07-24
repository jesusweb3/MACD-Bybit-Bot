# src/utils/helpers.py

def format_balance(balance: float) -> str:
    """Форматирование баланса для отображения с разделителями тысяч"""
    if balance >= 1000:
        return f"{balance:,.2f}"
    else:
        return f"{balance:.2f}"
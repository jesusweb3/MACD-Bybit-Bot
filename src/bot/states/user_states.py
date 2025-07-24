# src/bot/states/user_states.py
from aiogram.fsm.state import State, StatesGroup


class SettingsStates(StatesGroup):
    # API ключи
    waiting_for_api_key = State()
    waiting_for_secret_key = State()

    # Торговые настройки
    waiting_for_trading_pair = State()
    waiting_for_leverage = State()
    waiting_for_position_size = State()
    waiting_for_take_profit = State()
    waiting_for_stop_loss = State()
    waiting_for_entry_timeframe = State()
    waiting_for_exit_timeframe = State()
    waiting_for_bot_duration = State()


class TradingStates(StatesGroup):
    long_mode = State()
    short_mode = State()
    stopped = State()
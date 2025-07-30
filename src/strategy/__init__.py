# src/strategy/__init__.py
from .macd import MACDStrategy
from .strategy_manager import StrategyManager, strategy_manager

__all__ = ['MACDStrategy', 'StrategyManager', 'strategy_manager']
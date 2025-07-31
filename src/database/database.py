# src/database/database.py
import sqlite3
from typing import Optional, Dict, Any, List
from ..utils.config import config
from ..utils.logger import logger
from ..utils.helpers import get_msk_time
from datetime import datetime, UTC


class Database:
    def __init__(self):
        db_path = config.database_url.replace("sqlite:///", "")
        self.db_path = db_path

    def create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ - чистая структура без лишних полей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,

                    -- API ключи
                    bybit_api_key TEXT,
                    bybit_secret_key TEXT,

                    -- Торговые настройки
                    trading_pair TEXT,
                    leverage INTEGER,

                    -- Размер позиции
                    position_size_type TEXT,
                    position_size_value REAL,

                    -- ЕДИНЫЙ таймфрейм
                    timeframe TEXT,

                    -- Активная стратегия
                    active_strategy_name TEXT,
                    strategy_status TEXT DEFAULT 'stopped',
                    strategy_started_at TEXT,
                    strategy_stopped_at TEXT,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ТАБЛИЦА СДЕЛОК
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,  -- LONG/SHORT
                    entry_price REAL,
                    exit_price REAL,
                    quantity TEXT NOT NULL,
                    pnl REAL,
                    order_id TEXT,
                    opened_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT,
                    status TEXT DEFAULT 'open',  -- open/closed
                    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
                )
            """)

            conn.commit()
            logger.info("✅ Таблицы базы данных созданы")

    def get_or_create_user(self, telegram_id: int, username: Optional[str] = None) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()

            if user is None:
                cursor.execute(
                    "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
                    (telegram_id, username)
                )
                conn.commit()

                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
                user = cursor.fetchone()
                logger.info(f"👤 Создан новый пользователь: {telegram_id}")

            return dict(user)

    def get_user_settings(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()

            return dict(user) if user else None

    def update_user_settings(self, telegram_id: int, **kwargs) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if kwargs:
                set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
                values = list(kwargs.values()) + [datetime.now(UTC).isoformat(), telegram_id]

                cursor.execute(f"""
                    UPDATE users 
                    SET {set_clause}, updated_at = ?
                    WHERE telegram_id = ?
                """, values)

                conn.commit()

    def update_position_size(self, telegram_id: int, size_type: str, size_value: float) -> None:
        """Обновление размера позиции"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE users 
                    SET position_size_type = ?, 
                        position_size_value = ?,
                        updated_at = ?
                    WHERE telegram_id = ?
                """, (
                    size_type,
                    size_value,
                    datetime.now(UTC).isoformat(),
                    telegram_id
                ))

                conn.commit()

        except Exception as e:
            logger.error(f"❌ Ошибка обновления размера позиции для {telegram_id}: {e}")

    def get_position_size_info(self, telegram_id: int) -> Dict[str, Any]:
        """Получение информации о размере позиции"""
        user = self.get_user_settings(telegram_id)

        if not user:
            return {
                'type': None,
                'value': None,
                'display': '—'
            }

        size_type = user.get('position_size_type')
        size_value = user.get('position_size_value')

        if not size_type or size_value is None:
            return {
                'type': None,
                'value': None,
                'display': '—'
            }

        if size_type == 'percentage':
            display = f"{size_value}%"
        elif size_type == 'fixed_usdt':
            display = f"{size_value}USDT"
        else:
            display = '—'

        return {
            'type': size_type,
            'value': size_value,
            'display': display
        }

    def get_api_keys(self, telegram_id: int) -> Dict[str, Any]:
        """Получение API ключей пользователя"""
        user = self.get_user_settings(telegram_id)
        if not user:
            return {'api_key': None, 'secret_key': None}

        return {
            'api_key': user.get('bybit_api_key'),
            'secret_key': user.get('bybit_secret_key')
        }

    # МЕТОДЫ ДЛЯ СТРАТЕГИЙ
    def create_active_strategy(self, user_id: int, strategy_name: str) -> int:
        """Создание записи активной стратегии"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Находим пользователя по ID (если передали внутренний ID)
            cursor.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()

            if result:
                telegram_id = result[0]
            else:
                # Возможно передали telegram_id напрямую
                telegram_id = user_id

            cursor.execute("""
                UPDATE users 
                SET active_strategy_name = ?, 
                    strategy_status = 'running',
                    strategy_started_at = ?
                WHERE telegram_id = ?
            """, (strategy_name, get_msk_time().isoformat(), telegram_id))

            conn.commit()

            # Возвращаем telegram_id как strategy_id для совместимости
            return telegram_id

    def update_active_strategy_status(self, strategy_id: int, status: str, error_message: Optional[str] = None):
        """Обновление статуса активной стратегии"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            updates = ['strategy_status = ?']
            values = [status]

            if status == 'stopped':
                updates.append('strategy_stopped_at = ?')
                values.append(get_msk_time().isoformat())
                # Очищаем активную стратегию
                updates.append('active_strategy_name = NULL')

            # Логируем ошибку если есть
            if error_message:
                logger.warning(f"⚠️ Ошибка стратегии для пользователя {strategy_id}: {error_message}")

            values.append(strategy_id)

            cursor.execute(f"""
                UPDATE users 
                SET {', '.join(updates)}
                WHERE telegram_id = ?
            """, values)

            conn.commit()

    def get_active_strategy(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Получение активной стратегии пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT active_strategy_name as strategy_name, 
                       strategy_status as status,
                       strategy_started_at as started_at
                FROM users 
                WHERE telegram_id = ? AND strategy_status = 'running'
            """, (telegram_id,))

            strategy = cursor.fetchone()
            return dict(strategy) if strategy else None

    # МЕТОДЫ ДЛЯ СДЕЛОК
    def create_trade_record(self, user_id: int, strategy_id: int, symbol: str,
                            side: str, quantity: str, order_id: Optional[str] = None) -> int:
        """Создание записи сделки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Определяем telegram_id (может быть передан как user_id или strategy_id)
            telegram_id = user_id if user_id else strategy_id

            cursor.execute("""
                INSERT INTO trades 
                (telegram_id, symbol, side, quantity, order_id, opened_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (telegram_id, symbol, side, quantity, order_id,
                  get_msk_time().isoformat()))

            trade_id = cursor.lastrowid
            conn.commit()

            return trade_id

    def update_trade_record(self, trade_id: int, exit_price: Optional[float] = None,
                            pnl: Optional[float] = None, status: Optional[str] = None):
        """Обновление записи сделки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            update_fields = []
            values = []

            if exit_price is not None:
                update_fields.append('exit_price = ?')
                values.append(exit_price)

            if pnl is not None:
                update_fields.append('pnl = ?')
                values.append(pnl)

            if status:
                update_fields.append('status = ?')
                values.append(status)

                if status == 'closed':
                    update_fields.append('closed_at = ?')
                    values.append(get_msk_time().isoformat())

            if update_fields:
                values.append(trade_id)
                cursor.execute(f"""
                    UPDATE trades 
                    SET {', '.join(update_fields)}
                    WHERE id = ?
                """, values)

                conn.commit()

    def get_user_trades_history(self, telegram_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Получение истории сделок пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM trades 
                WHERE telegram_id = ?
                ORDER BY opened_at DESC
                LIMIT ?
            """, (telegram_id, limit))

            trades = cursor.fetchall()
            return [dict(trade) for trade in trades]

    def get_user_statistics(self, telegram_id: int) -> Dict[str, Any]:
        """НОВЫЙ МЕТОД: Получение статистики торговли пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Получаем все сделки пользователя
            cursor.execute("""
                SELECT * FROM trades 
                WHERE telegram_id = ?
                ORDER BY opened_at DESC
            """, (telegram_id,))

            trades = cursor.fetchall()

            # Считаем статистику
            total_trades = len(trades)
            closed_trades = len([t for t in trades if t['status'] == 'closed'])
            profitable_trades = len([t for t in trades if t['status'] == 'closed' and t['pnl'] and t['pnl'] > 0])
            losing_trades = len([t for t in trades if t['status'] == 'closed' and t['pnl'] and t['pnl'] < 0])

            total_pnl = sum([t['pnl'] for t in trades if t['pnl'] is not None])
            win_rate = (profitable_trades / closed_trades * 100) if closed_trades > 0 else 0

            return {
                'total_trades': total_trades,
                'closed_trades': closed_trades,
                'profitable_trades': profitable_trades,
                'losing_trades': losing_trades,
                'total_pnl': total_pnl,
                'win_rate': win_rate
            }

    @staticmethod
    def get_user_strategies_history(telegram_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """История стратегий - заглушка (не используется в текущей версии)"""
        return []

    def cleanup_old_data(self, days_to_keep: int = 30):
        """НОВЫЙ МЕТОД: Очистка старых данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Удаляем старые закрытые сделки
                cursor.execute("""
                    DELETE FROM trades 
                    WHERE status = 'closed' 
                    AND closed_at < datetime('now', '-{} days')
                """.format(days_to_keep))

                deleted_trades = cursor.rowcount
                conn.commit()

                if deleted_trades > 0:
                    logger.info(f"🧹 Удалено {deleted_trades} старых сделок (старше {days_to_keep} дней)")

        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых данных: {e}")

    def get_database_stats(self) -> Dict[str, Any]:
        """НОВЫЙ МЕТОД: Статистика базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Считаем пользователей
                cursor.execute("SELECT COUNT(*) FROM users")
                total_users = cursor.fetchone()[0]

                # Считаем активные стратегии
                cursor.execute("SELECT COUNT(*) FROM users WHERE strategy_status = 'running'")
                active_strategies = cursor.fetchone()[0]

                # Считаем сделки
                cursor.execute("SELECT COUNT(*) FROM trades")
                total_trades = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'open'")
                open_trades = cursor.fetchone()[0]

                return {
                    'total_users': total_users,
                    'active_strategies': active_strategies,
                    'total_trades': total_trades,
                    'open_trades': open_trades
                }

        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики БД: {e}")
            return {}


db = Database()
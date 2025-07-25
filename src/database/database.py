# src/database/database.py
import sqlite3
from typing import Optional, Dict, Any, List
from ..utils.config import config
from ..utils.logger import logger
from datetime import datetime, UTC


class Database:
    def __init__(self):
        db_path = config.database_url.replace("sqlite:///", "")
        self.db_path = db_path

    def create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE,

                    -- API ключи
                    bybit_api_key TEXT,
                    bybit_secret_key TEXT,

                    -- Торговые настройки
                    trading_pair TEXT,
                    leverage INTEGER,

                    -- Размер позиции
                    position_size_type TEXT,                      -- 'percentage' или 'fixed_usdt'
                    position_size_value REAL,                     -- число (10 для 10% или 100 для 100 USDT)

                    -- TP/SL настройки
                    take_profit REAL,                             -- значение в пунктах
                    stop_loss REAL,                               -- значение в пунктах
                    tp_sl_enabled INTEGER DEFAULT 0,              -- 0 = выключено, 1 = включено

                    -- Таймфреймы
                    entry_timeframe TEXT,
                    exit_timeframe TEXT,

                    bot_duration_hours INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    strategy_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    stopped_at TEXT,
                    error_message TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    strategy_id INTEGER,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    quantity TEXT NOT NULL,
                    pnl REAL,
                    order_id TEXT,
                    opened_at TEXT,
                    closed_at TEXT,
                    status TEXT DEFAULT 'open',
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (strategy_id) REFERENCES active_strategies (id)
                )
            """)

            # Миграция для добавления tp_sl_enabled если колонка не существует
            Database._migrate_tp_sl_enabled(cursor)

            conn.commit()
            logger.info("Database tables created")

    @staticmethod
    def _migrate_tp_sl_enabled(cursor):
        """Миграция для добавления поля tp_sl_enabled в существующие таблицы"""
        try:
            cursor.execute("PRAGMA table_info(user_settings)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'tp_sl_enabled' not in columns:
                logger.info("Добавление поля tp_sl_enabled в user_settings")
                cursor.execute("""
                    ALTER TABLE user_settings 
                    ADD COLUMN tp_sl_enabled INTEGER DEFAULT 0
                """)

                # Для существующих пользователей включаем TP/SL если значения заполнены
                cursor.execute("""
                    UPDATE user_settings 
                    SET tp_sl_enabled = 1 
                    WHERE take_profit IS NOT NULL 
                    AND take_profit > 0 
                    AND stop_loss IS NOT NULL 
                    AND stop_loss > 0
                """)

                logger.info("Миграция tp_sl_enabled завершена")

        except Exception as e:
            logger.error(f"Ошибка миграции tp_sl_enabled: {e}")

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
                user_id = cursor.lastrowid

                cursor.execute(
                    "INSERT INTO user_settings (user_id) VALUES (?)",
                    (user_id,)
                )

                conn.commit()

                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                logger.info(f"Created new user: {telegram_id}")

            return dict(user)

    def get_user_settings(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT us.* FROM user_settings us
                JOIN users u ON us.user_id = u.id
                WHERE u.telegram_id = ?
            """, (telegram_id,))

            settings = cursor.fetchone()
            if settings:
                return dict(settings)

            return None

    def update_user_settings(self, telegram_id: int, **kwargs) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()

            if user:
                user_id = user[0]

                set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
                values = list(kwargs.values()) + [datetime.now(UTC).isoformat(), user_id]

                cursor.execute(f"""
                    UPDATE user_settings 
                    SET {set_clause}, updated_at = ?
                    WHERE user_id = ?
                """, values)

                conn.commit()
                logger.info(f"Updated settings for user {telegram_id}")

    def update_position_size(self, telegram_id: int, size_type: str, size_value: float) -> None:
        """Обновление размера позиции"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
                user = cursor.fetchone()

                if user:
                    user_id = user[0]

                    cursor.execute("""
                        UPDATE user_settings 
                        SET position_size_type = ?, 
                            position_size_value = ?,
                            updated_at = ?
                        WHERE user_id = ?
                    """, (
                        size_type,
                        size_value,
                        datetime.now(UTC).isoformat(),
                        user_id
                    ))

                    conn.commit()
                    logger.info(f"Updated position size for user {telegram_id}: {size_type} = {size_value}")

        except Exception as e:
            logger.error(f"Ошибка обновления размера позиции: {e}")

    def get_position_size_info(self, telegram_id: int) -> Dict[str, Any]:
        """Получение информации о размере позиции"""
        settings = self.get_user_settings(telegram_id)

        if not settings:
            return {
                'type': None,
                'value': None,
                'display': 'не установлен'
            }

        size_type = settings.get('position_size_type')
        size_value = settings.get('position_size_value')

        if not size_type or size_value is None:
            return {
                'type': None,
                'value': None,
                'display': 'не установлен'
            }

        if size_type == 'percentage':
            display = f"{size_value}%"
        elif size_type == 'fixed_usdt':
            display = f"{size_value}USDT"
        else:
            display = 'не установлен'

        return {
            'type': size_type,
            'value': size_value,
            'display': display
        }

    def get_tp_sl_info(self, telegram_id: int) -> Dict[str, Any]:
        """Получение информации о настройках TP/SL"""
        settings = self.get_user_settings(telegram_id)

        if not settings:
            return {
                'enabled': False,
                'take_profit': None,
                'stop_loss': None,
                'display': 'не настроено'
            }

        enabled = bool(settings.get('tp_sl_enabled', 0))
        take_profit = settings.get('take_profit')
        stop_loss = settings.get('stop_loss')

        if enabled and take_profit and stop_loss:
            display = f"TP: {take_profit} | SL: {stop_loss}"
        elif not enabled:
            display = "выключено"
        else:
            display = "не настроено"

        return {
            'enabled': enabled,
            'take_profit': take_profit,
            'stop_loss': stop_loss,
            'display': display
        }

    def update_tp_sl_settings(self, telegram_id: int, take_profit: float = None,
                              stop_loss: float = None, enabled: bool = None) -> None:
        """Обновление настроек TP/SL"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
                user = cursor.fetchone()

                if user:
                    user_id = user[0]

                    updates = []
                    values = []

                    if take_profit is not None:
                        updates.append("take_profit = ?")
                        values.append(take_profit)

                    if stop_loss is not None:
                        updates.append("stop_loss = ?")
                        values.append(stop_loss)

                    if enabled is not None:
                        updates.append("tp_sl_enabled = ?")
                        values.append(1 if enabled else 0)

                    if updates:
                        updates.append("updated_at = ?")
                        values.extend([datetime.now(UTC).isoformat(), user_id])

                        query = f"""
                            UPDATE user_settings 
                            SET {', '.join(updates)}
                            WHERE user_id = ?
                        """

                        cursor.execute(query, values)
                        conn.commit()

                        logger.info(f"Updated TP/SL settings for user {telegram_id}")

        except Exception as e:
            logger.error(f"Ошибка обновления TP/SL настроек: {e}")

    def get_api_keys(self, telegram_id: int) -> Dict[str, Any]:
        """Получение API ключей пользователя"""
        settings = self.get_user_settings(telegram_id)
        if not settings:
            return {'api_key': None, 'secret_key': None}

        return {
            'api_key': settings.get('bybit_api_key'),
            'secret_key': settings.get('bybit_secret_key')
        }

    # Методы для работы со стратегиями
    def create_active_strategy(self, user_id: int, strategy_name: str) -> int:
        """Создание записи активной стратегии"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO active_strategies (user_id, strategy_name, status, started_at)
                VALUES (?, ?, 'running', ?)
            """, (user_id, strategy_name, datetime.now(UTC).isoformat()))

            strategy_id = cursor.lastrowid
            conn.commit()

            logger.info(f"Создана активная стратегия ID={strategy_id} для пользователя {user_id}")
            return strategy_id

    def update_active_strategy_status(self, strategy_id: int, status: str, error_message: str = None):
        """Обновление статуса активной стратегии"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            update_fields = ['status = ?']
            values = [status]

            if status == 'stopped':
                update_fields.append('stopped_at = ?')
                values.append(datetime.now(UTC).isoformat())

            if error_message:
                update_fields.append('error_message = ?')
                values.append(error_message)

            values.append(strategy_id)

            cursor.execute(f"""
                UPDATE active_strategies 
                SET {', '.join(update_fields)}
                WHERE id = ?
            """, values)

            conn.commit()
            logger.info(f"Обновлен статус стратегии {strategy_id}: {status}")

    def get_active_strategy(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Получение активной стратегии пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT s.* FROM active_strategies s
                JOIN users u ON s.user_id = u.id
                WHERE u.telegram_id = ? AND s.status = 'running'
                ORDER BY s.started_at DESC
                LIMIT 1
            """, (telegram_id,))

            strategy = cursor.fetchone()
            return dict(strategy) if strategy else None

    def get_user_strategies_history(self, telegram_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение истории стратегий пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT s.* FROM active_strategies s
                JOIN users u ON s.user_id = u.id
                WHERE u.telegram_id = ?
                ORDER BY s.started_at DESC
                LIMIT ?
            """, (telegram_id, limit))

            strategies = cursor.fetchall()
            return [dict(strategy) for strategy in strategies]

    def create_trade_record(self, user_id: int, strategy_id: int, symbol: str,
                            side: str, quantity: str, order_id: str = None) -> int:
        """Создание записи сделки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO trade_history 
                (user_id, strategy_id, symbol, side, quantity, order_id, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, strategy_id, symbol, side, quantity, order_id,
                  datetime.now(UTC).isoformat()))

            trade_id = cursor.lastrowid
            conn.commit()

            logger.info(f"Создана запись сделки ID={trade_id}")
            return trade_id

    def update_trade_record(self, trade_id: int, exit_price: float = None,
                            pnl: float = None, status: str = None):
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
                    values.append(datetime.now(UTC).isoformat())

            if update_fields:
                values.append(trade_id)
                cursor.execute(f"""
                    UPDATE trade_history 
                    SET {', '.join(update_fields)}
                    WHERE id = ?
                """, values)

                conn.commit()
                logger.info(f"Обновлена запись сделки {trade_id}")

    def get_user_trades_history(self, telegram_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Получение истории сделок пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT t.* FROM trade_history t
                JOIN users u ON t.user_id = u.id
                WHERE u.telegram_id = ?
                ORDER BY t.opened_at DESC
                LIMIT ?
            """, (telegram_id, limit))

            trades = cursor.fetchall()
            return [dict(trade) for trade in trades]


db = Database()
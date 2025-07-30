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

            # УПРОЩЕННАЯ ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ - объединяем пользователей и настройки
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

                    -- TP/SL настройки
                    take_profit REAL,
                    stop_loss REAL,
                    tp_sl_enabled INTEGER DEFAULT 0,

                    -- Таймфреймы (теперь только один - упрощаем)
                    timeframe TEXT,

                    -- Время работы бота
                    bot_duration_hours INTEGER,

                    -- Активная стратегия (встроили прямо в пользователя)
                    active_strategy_name TEXT,
                    strategy_status TEXT DEFAULT 'stopped',
                    strategy_started_at TEXT,
                    strategy_stopped_at TEXT,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # УПРОЩЕННАЯ ТАБЛИЦА СДЕЛОК - убираем лишние связи
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,  -- Прямая связь с пользователем
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

            # Миграция данных из старых таблиц если они существуют
            Database._migrate_from_old_tables(cursor)

            conn.commit()
            logger.info("Упрощенные таблицы базы данных созданы")

    @staticmethod
    def _migrate_from_old_tables(cursor):
        """Миграция данных из старых таблиц в новую упрощенную структуру"""
        try:
            # Проверяем существование старых таблиц
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = [str(table[0]) for table in cursor.fetchall()]

            if 'user_settings' in existing_tables:
                logger.info("Миграция данных из старых таблиц...")

                # Миграция пользователей и настроек
                cursor.execute("""
                    INSERT OR REPLACE INTO users (
                        telegram_id, username, bybit_api_key, bybit_secret_key,
                        trading_pair, leverage, position_size_type, position_size_value,
                        take_profit, stop_loss, tp_sl_enabled, timeframe, bot_duration_hours
                    )
                    SELECT 
                        u.telegram_id, u.username, us.bybit_api_key, us.bybit_secret_key,
                        us.trading_pair, us.leverage, us.position_size_type, us.position_size_value,
                        us.take_profit, us.stop_loss, us.tp_sl_enabled, 
                        us.entry_timeframe as timeframe, us.bot_duration_hours
                    FROM users u
                    LEFT JOIN user_settings us ON u.id = us.user_id
                    WHERE u.telegram_id IS NOT NULL
                """)

                # Миграция сделок
                if 'trade_history' in existing_tables:
                    cursor.execute("""
                        INSERT OR REPLACE INTO trades (
                            telegram_id, symbol, side, entry_price, exit_price,
                            quantity, pnl, order_id, opened_at, closed_at, status
                        )
                        SELECT 
                            u.telegram_id, th.symbol, th.side, th.entry_price, th.exit_price,
                            th.quantity, th.pnl, th.order_id, th.opened_at, th.closed_at, th.status
                        FROM trade_history th
                        JOIN users u ON th.user_id = u.id
                        WHERE u.telegram_id IS NOT NULL
                    """)

                logger.info("Миграция данных завершена")

        except Exception as e:
            logger.warning(f"Ошибка миграции данных: {e}")

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
                logger.info(f"Created new user: {telegram_id}")

            return dict(user)

    def get_user_settings(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()

            if user:
                # Преобразуем в формат старых настроек для совместимости
                result = dict(user)
                # Добавляем совместимость с старыми именами полей
                result['entry_timeframe'] = result.get('timeframe')
                result['exit_timeframe'] = result.get('timeframe')
                return result

            return None

    def update_user_settings(self, telegram_id: int, **kwargs) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Преобразуем новые поля в упрощенную схему
            if 'entry_timeframe' in kwargs or 'exit_timeframe' in kwargs:
                # Берем таймфрейм из entry_timeframe
                timeframe = kwargs.get('entry_timeframe') or kwargs.get('exit_timeframe')
                kwargs['timeframe'] = timeframe
                # Удаляем старые поля
                kwargs.pop('entry_timeframe', None)
                kwargs.pop('exit_timeframe', None)

            if kwargs:
                set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
                values = list(kwargs.values()) + [datetime.now(UTC).isoformat(), telegram_id]

                cursor.execute(f"""
                    UPDATE users 
                    SET {set_clause}, updated_at = ?
                    WHERE telegram_id = ?
                """, values)

                conn.commit()
                logger.info(f"Updated settings for user {telegram_id}")

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
                logger.info(f"Updated position size for user {telegram_id}: {size_type} = {size_value}")

        except Exception as e:
            logger.error(f"Ошибка обновления размера позиции: {e}")

    def get_position_size_info(self, telegram_id: int) -> Dict[str, Any]:
        """Получение информации о размере позиции"""
        user = self.get_user_settings(telegram_id)

        if not user:
            return {
                'type': None,
                'value': None,
                'display': 'не установлен'
            }

        size_type = user.get('position_size_type')
        size_value = user.get('position_size_value')

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
        user = self.get_user_settings(telegram_id)

        if not user:
            return {
                'enabled': False,
                'take_profit': None,
                'stop_loss': None,
                'display': 'не настроено'
            }

        enabled = bool(user.get('tp_sl_enabled', 0))
        take_profit = user.get('take_profit')
        stop_loss = user.get('stop_loss')

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

    def update_tp_sl_settings(self, telegram_id: int, take_profit: Optional[float] = None,
                              stop_loss: Optional[float] = None, enabled: Optional[bool] = None) -> None:
        """Обновление настроек TP/SL"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

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
                    values.extend([datetime.now(UTC).isoformat(), telegram_id])

                    query = f"""
                        UPDATE users 
                        SET {', '.join(updates)}
                        WHERE telegram_id = ?
                    """

                    cursor.execute(query, values)
                    conn.commit()

                    logger.info(f"Updated TP/SL settings for user {telegram_id}")

        except Exception as e:
            logger.error(f"Ошибка обновления TP/SL настроек: {e}")

    def get_api_keys(self, telegram_id: int) -> Dict[str, Any]:
        """Получение API ключей пользователя"""
        user = self.get_user_settings(telegram_id)
        if not user:
            return {'api_key': None, 'secret_key': None}

        return {
            'api_key': user.get('bybit_api_key'),
            'secret_key': user.get('bybit_secret_key')
        }

    # УПРОЩЕННЫЕ МЕТОДЫ ДЛЯ СТРАТЕГИЙ
    def create_active_strategy(self, user_id: int, strategy_name: str) -> int:
        """Создание записи активной стратегии - теперь встроено в пользователя"""
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
            """, (strategy_name, datetime.now(UTC).isoformat(), telegram_id))

            conn.commit()
            logger.info(f"Активирована стратегия {strategy_name} для пользователя {telegram_id}")

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
                values.append(datetime.now(UTC).isoformat())
                # Очищаем активную стратегию
                updates.append('active_strategy_name = NULL')

            # Можно добавить обработку error_message в будущем если понадобится
            if error_message:
                logger.warning(f"Strategy error for user {strategy_id}: {error_message}")

            values.append(strategy_id)

            cursor.execute(f"""
                UPDATE users 
                SET {', '.join(updates)}
                WHERE telegram_id = ?
            """, values)

            conn.commit()
            logger.info(f"Обновлен статус стратегии для пользователя {strategy_id}: {status}")

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

    # УПРОЩЕННЫЕ МЕТОДЫ ДЛЯ СДЕЛОК
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
                  datetime.now(UTC).isoformat()))

            trade_id = cursor.lastrowid
            conn.commit()

            logger.info(f"Создана запись сделки ID={trade_id}")
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
                    values.append(datetime.now(UTC).isoformat())

            if update_fields:
                values.append(trade_id)
                cursor.execute(f"""
                    UPDATE trades 
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
                SELECT * FROM trades 
                WHERE telegram_id = ?
                ORDER BY opened_at DESC
                LIMIT ?
            """, (telegram_id, limit))

            trades = cursor.fetchall()
            return [dict(trade) for trade in trades]

    @staticmethod
    def get_user_strategies_history(telegram_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение истории стратегий пользователя - упрощенная версия"""
        # Возвращаем пустой список, так как теперь история встроена в пользователя
        # Параметры оставлены для совместимости с существующим кодом
        _ = telegram_id, limit  # Подавляем предупреждения о неиспользуемых параметрах
        return []


db = Database()
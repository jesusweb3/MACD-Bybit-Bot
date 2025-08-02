# src/database/database.py
import sqlite3
from typing import Optional, Dict, Any, List
from ..utils.config import config
from ..utils.logger import logger
from ..utils.helpers import get_msk_time
from datetime import datetime, UTC


class Database:
    """Упрощенная база данных без пользователей Telegram"""

    def __init__(self):
        db_path = config.database_url.replace("sqlite:///", "")
        self.db_path = db_path

    def create_tables(self):
        """Создание упрощенных таблиц"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # ТАБЛИЦА СДЕЛОК - единственная нужная таблица
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,  -- LONG/SHORT
                    entry_price REAL,
                    exit_price REAL,
                    quantity TEXT NOT NULL,
                    pnl REAL,
                    order_id TEXT,
                    opened_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT,
                    status TEXT DEFAULT 'open'  -- open/closed
                )
            """)

            # ТАБЛИЦА СТАТУСА СТРАТЕГИИ - для отслеживания активности
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_status (
                    id INTEGER PRIMARY KEY,
                    strategy_name TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT FALSE,
                    started_at TEXT,
                    stopped_at TEXT,
                    error_message TEXT
                )
            """)

            # Вставляем единственную запись статуса если её нет
            cursor.execute("SELECT COUNT(*) FROM strategy_status")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO strategy_status (id, strategy_name, is_active) 
                    VALUES (1, 'MACD Strategy', FALSE)
                """)

            conn.commit()
            logger.info("✅ Таблицы базы данных созданы")

    # МЕТОДЫ ДЛЯ СТАТУСА СТРАТЕГИИ
    def set_strategy_active(self, strategy_name: str) -> None:
        """Установить стратегию как активную"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE strategy_status 
                SET strategy_name = ?, 
                    is_active = TRUE,
                    started_at = ?,
                    stopped_at = NULL,
                    error_message = NULL
                WHERE id = 1
            """, (strategy_name, get_msk_time().isoformat()))
            conn.commit()
            logger.info(f"✅ Стратегия '{strategy_name}' отмечена как активная")

    def set_strategy_inactive(self, reason: Optional[str] = None) -> None:
        """Установить стратегию как неактивную"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE strategy_status 
                SET is_active = FALSE,
                    stopped_at = ?,
                    error_message = ?
                WHERE id = 1
            """, (get_msk_time().isoformat(), reason))
            conn.commit()
            logger.info(f"⏹️ Стратегия отмечена как неактивная: {reason or 'Normal stop'}")

    def is_strategy_active(self) -> bool:
        """Проверить активна ли стратегия"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT is_active FROM strategy_status WHERE id = 1")
            result = cursor.fetchone()
            return bool(result['is_active']) if result else False

    def get_strategy_status(self) -> Dict[str, Any]:
        """Получить полный статус стратегии"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM strategy_status WHERE id = 1")
            result = cursor.fetchone()
            return dict(result) if result else {}

    # МЕТОДЫ ДЛЯ СДЕЛОК
    def create_trade_record(self, symbol: str, side: str, quantity: str, order_id: Optional[str] = None) -> int:
        """Создание записи сделки"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades 
                (symbol, side, quantity, order_id, opened_at)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, side, quantity, order_id, get_msk_time().isoformat()))

            trade_id = cursor.lastrowid
            conn.commit()
            logger.info(f"📝 Создана запись сделки ID={trade_id}: {side} {quantity} {symbol}")
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
                logger.info(f"📝 Обновлена сделка ID={trade_id}: {', '.join(update_fields)}")

    def get_trades_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Получение истории сделок"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades 
                ORDER BY opened_at DESC
                LIMIT ?
            """, (limit,))

            trades = cursor.fetchall()
            return [dict(trade) for trade in trades]

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики торговли"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Получаем все сделки
            cursor.execute("SELECT * FROM trades ORDER BY opened_at DESC")
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

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Получение открытых сделок"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades 
                WHERE status = 'open'
                ORDER BY opened_at DESC
            """)
            trades = cursor.fetchall()
            return [dict(trade) for trade in trades]

    def cleanup_old_data(self, days_to_keep: int = 30):
        """Очистка старых данных"""
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
        """Статистика базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Считаем сделки
                cursor.execute("SELECT COUNT(*) FROM trades")
                total_trades = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'open'")
                open_trades = cursor.fetchone()[0]

                # Проверяем статус стратегии
                cursor.execute("SELECT is_active FROM strategy_status WHERE id = 1")
                result = cursor.fetchone()
                strategy_active = bool(result[0]) if result else False

                return {
                    'total_trades': total_trades,
                    'open_trades': open_trades,
                    'strategy_active': strategy_active
                }

        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики БД: {e}")
            return {}

    def print_statistics(self):
        """Вывод статистики в консоль"""
        stats = self.get_statistics()
        strategy_status = self.get_strategy_status()

        print("\n" + "=" * 50)
        print("СТАТИСТИКА ТОРГОВЛИ")
        print("=" * 50)
        print(f"Статус стратегии: {'🟢 АКТИВНА' if strategy_status.get('is_active') else '🔴 ОСТАНОВЛЕНА'}")
        if strategy_status.get('strategy_name'):
            print(f"Название: {strategy_status['strategy_name']}")
        print(f"Всего сделок: {stats['total_trades']}")
        print(f"Закрытых сделок: {stats['closed_trades']}")
        print(f"Прибыльных: {stats['profitable_trades']}")
        print(f"Убыточных: {stats['losing_trades']}")
        print(f"Общий P&L: {stats['total_pnl']:.2f} USDT")
        print(f"Винрейт: {stats['win_rate']:.1f}%")
        print("=" * 50)


# Глобальный экземпляр базы данных
db = Database()
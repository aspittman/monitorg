import json
import sqlite3
from contextlib import contextmanager


class SnapshotStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS snapshots (
                timestamp TEXT NOT NULL, bot TEXT NOT NULL, positions INTEGER,
                realized_pl REAL, unrealized_pl REAL, equity_if_known REAL,
                daily_return REAL, monthly_return REAL, total_return REAL,
                trade_count_day INTEGER, trade_count_month INTEGER, trade_count_total INTEGER,
                details TEXT NOT NULL, PRIMARY KEY(timestamp, bot))''')
            existing={row[1] for row in db.execute('PRAGMA table_info(snapshots)')}
            for name in ('trade_roi_today','trade_roi_month','trade_roi_total'):
                if name not in existing:
                    db.execute(f'ALTER TABLE snapshots ADD COLUMN {name} REAL')
            db.execute('CREATE INDEX IF NOT EXISTS snapshots_bot_time ON snapshots(bot,timestamp)')
            db.execute('''CREATE TABLE IF NOT EXISTS broker_fills (
                account_identity TEXT NOT NULL, fill_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(account_identity,fill_id))''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def write(self, dashboard):
        with self.connect() as db:
            for bot in dashboard['bots']:
                db.execute('''INSERT OR IGNORE INTO snapshots
                    (timestamp,bot,positions,realized_pl,unrealized_pl,equity_if_known,daily_return,monthly_return,total_return,
                     trade_count_day,trade_count_month,trade_count_total,details,trade_roi_today,trade_roi_month,trade_roi_total)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                    dashboard['timestamp'], bot['bot_id'], bot['open_positions'], bot['realized_pl'],
                    bot['unrealized_pl'], None, bot['daily_return'], bot['monthly_return'], bot['total_return'],
                    bot['trades_today'], bot['trades_month'], bot['trades_total'], json.dumps(bot),
                    bot.get('trade_roi_today'),bot.get('trade_roi_month'),bot.get('trade_roi_total')))

    def history(self, bot, limit=2000):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in reversed(db.execute('''SELECT timestamp,bot,positions,realized_pl,unrealized_pl,
                equity_if_known,daily_return,monthly_return,trade_count_day,trade_count_month,trade_count_total,trade_roi_today,trade_roi_month,trade_roi_total
                FROM snapshots WHERE bot=? ORDER BY timestamp DESC LIMIT ?''', (bot, limit)).fetchall())]

    def cache_fills(self, identity, fills):
        with self.connect() as db:
            db.executemany('INSERT OR REPLACE INTO broker_fills VALUES (?,?,?)',
                           [(identity, f['id'], json.dumps(f)) for f in fills])

    def cached_fills(self, identity):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM broker_fills WHERE account_identity=?',(identity,))]

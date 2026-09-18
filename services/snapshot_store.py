import json
import sqlite3


class SnapshotStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS snapshots (
                timestamp TEXT NOT NULL, bot TEXT NOT NULL, positions INTEGER,
                realized_pl REAL, unrealized_pl REAL, equity_if_known REAL,
                daily_return REAL, monthly_return REAL, total_return REAL,
                trade_count_day INTEGER, trade_count_month INTEGER, trade_count_total INTEGER,
                details TEXT NOT NULL, PRIMARY KEY(timestamp, bot))''')
            db.execute('CREATE INDEX IF NOT EXISTS snapshots_bot_time ON snapshots(bot,timestamp)')
            db.execute('''CREATE TABLE IF NOT EXISTS broker_fills (
                account_identity TEXT NOT NULL, fill_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(account_identity,fill_id))''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def write(self, dashboard):
        with self.connect() as db:
            for bot in dashboard['bots']:
                db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                    dashboard['timestamp'], bot['bot_id'], bot['open_positions'], bot['realized_pl'],
                    bot['unrealized_pl'], None, bot['daily_return'], bot['monthly_return'], bot['total_return'],
                    bot['trades_today'], bot['trades_month'], bot['trades_total'], json.dumps(bot)))

    def history(self, bot, limit=2000):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in reversed(db.execute('''SELECT timestamp,bot,positions,realized_pl,unrealized_pl,
                equity_if_known,daily_return,monthly_return,trade_count_day,trade_count_month,trade_count_total
                FROM snapshots WHERE bot=? ORDER BY timestamp DESC LIMIT ?''', (bot, limit)).fetchall())]

    def cache_fills(self, identity, fills):
        with self.connect() as db:
            db.executemany('INSERT OR REPLACE INTO broker_fills VALUES (?,?,?)',
                           [(identity, f['id'], json.dumps(f)) for f in fills])

    def cached_fills(self, identity):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM broker_fills WHERE account_identity=?',(identity,))]

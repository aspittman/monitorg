import sqlite3,tempfile,unittest
from pathlib import Path
from services.snapshot_store import SnapshotStore

class SnapshotConcurrencyTests(unittest.TestCase):
    def test_reader_does_not_block_fill_cache_writer(self):
        with tempfile.TemporaryDirectory() as d:
            store=SnapshotStore(Path(d)/'monitor.db')
            with store.connect() as reader:
                reader.execute('BEGIN')
                self.assertEqual(reader.execute('SELECT count(*) FROM broker_fills').fetchone()[0],0)
                store.cache_fills('account',[{'id':'fill'}])
                self.assertEqual(reader.execute('SELECT count(*) FROM broker_fills').fetchone()[0],0)
            self.assertEqual(store.cached_fills('account'),[{'id':'fill'}])
            with self.assertRaises(sqlite3.ProgrammingError):reader.execute('SELECT 1')
    def test_trade_roi_migration_preserves_portfolio_returns(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'old.db'
            with sqlite3.connect(path) as db:
                db.execute('''CREATE TABLE snapshots (
                    timestamp TEXT, bot TEXT, positions INTEGER, realized_pl REAL, unrealized_pl REAL,
                    equity_if_known REAL, daily_return REAL, monthly_return REAL, total_return REAL,
                    trade_count_day INTEGER, trade_count_month INTEGER, trade_count_total INTEGER,
                    details TEXT, PRIMARY KEY(timestamp,bot))''')
                db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('2026-09-17','test',1,10,2,100,0.5,1,2,1,2,3,'{}'))
            store=SnapshotStore(path)
            SnapshotStore(path)  # Migration is idempotent.
            old=store.history('test')[0]
            self.assertEqual(old['daily_return'],0.5)
            self.assertEqual(old['realized_pl'],10)
            self.assertIsNone(old['trade_roi_total'])
            row=dict(bot_id='test',open_positions=0,realized_pl=20,unrealized_pl=0,daily_return=None,
                monthly_return=None,total_return=None,trades_today=2,trades_month=4,trades_total=4,
                trade_roi_today=10,trade_roi_month=5,trade_roi_total=3)
            store.write(dict(timestamp='2026-09-18',bots=[row]))
            new=store.history('test')[-1]
            self.assertEqual(new['trade_roi_total'],3)
            self.assertIsNone(new['daily_return'])

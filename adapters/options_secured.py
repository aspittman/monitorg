from adapters.base import Adapter
from models.records import position, timestamp
from config import SOURCE_TIMEZONE
from services.source_reader import sqlite_copy, table


class OptionsSecured(Adapter):
    asset_class = 'option'

    def read(self):
        path = self.env.get('DB_PATH', 'logs/options_secured.sqlite3')
        data = self.result(path, path+'-wal')
        with sqlite_copy(self.root/path) as db:
            orders = {r['client_id']: r for r in table(db, 'orders')}
            for row in table(db, 'fills'):
                order = orders.get(row['client_id'])
                if not order or not row['client_id'].startswith(('cash_secured_put_', 'os-')):
                    raise ValueError('Unattributable SQLite fill')
                data.trades.append(self.trade(row['timestamp'], row['symbol'], row['side'], row['qty'], row['price'],
                    order['broker_id'] or row['client_id'], f"secured:{row['_rowid']}", order['strategy'], row['_rowid']))
                if row['estimated_time']:
                    data.trades[-1]['estimated_time'] = True
                    data.warnings.append('Migrated fill timestamps are estimated; period counts unavailable.')
            self.calculate(data, short=True)
            data.positions = [position(r['symbol'], -r['qty'], r['credit'], 'SQLite owned short-put lots')
                              for r in table(db, 'lots') if r['qty'] > 0]
            data.pnl_events = [dict(timestamp=timestamp(r['timestamp'], SOURCE_TIMEZONE), realized_pl=float(r['realized']))
                               for r in table(db, 'pnl')]
            data.realized_pl = sum(r['realized_pl'] for r in data.pnl_events)
            assigned = [r for r in table(db, 'settlements') if r['outcome']=='assignment']
            if assigned:
                data.positions = None
                data.warnings.append('Option assignment exists; assigned stock ownership needs reconciliation.')
        data.warnings.append('Fill times are bot reconciliation times; broker execution times may differ near day boundaries.')
        return data

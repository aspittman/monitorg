from adapters.base import Adapter
from models.records import position
from services.source_reader import sqlite_copy, table, has_table


class OptionsCovered(Adapter):
    asset_class = 'equity / option'

    def read(self):
        path = self.env.get('LEDGER_PATH', 'logs/trades.sqlite3')
        data = self.result(path, path+'-wal')
        with sqlite_copy(self.root/path) as db:
            orders = {r['client_id']: r for r in table(db, 'orders')}
            for row in table(db, 'fills'):
                order = orders.get(row['client_id'])
                if not order or not row['client_id'].startswith('covered_call_'):
                    raise ValueError('Unattributable SQLite fill')
                data.trades.append(self.trade(row['timestamp'], row['symbol'],
                    'sell' if row['intent']=='sell_to_open' else 'buy', row['qty'], row['notional']/row['qty'],
                    order['broker_id'] or row['client_id'], f"covered:{row['id']}", 'covered_call', row['id']))
            self.calculate(data, short=True)
            stocks = {r['client_id']: r for r in table(db, 'stock_orders')} if has_table(db, 'stock_orders') else {}
            for row in table(db, 'stock_fills') if has_table(db, 'stock_fills') else []:
                order = stocks[row['client_id']]
                if not row['client_id'].startswith('covered_stock_'):
                    raise ValueError('Unattributable stock fill')
                data.trades.append(self.trade(row['timestamp'], row['symbol'], 'buy', row['qty'], row['notional']/row['qty'],
                    order['broker_id'] or row['client_id'], f"stock:{row['id']}", 'covered_stock', row['id']))
            if data.positions is not None:
                data.positions.extend(position(r['underlying'], r['shares'], r['cost_per_share'], 'SQLite explicit stock allocations')
                                      for r in table(db, 'stock_allocations') if r['shares'] > 0)
            if table(db, 'settlements') or table(db, 'stock_dispositions'):
                data.positions = None
                data.realized_pl = None
                data.warnings.append('Settlement/stock disposition detected; full lifecycle P/L and inventory need reconciliation.')
        return data

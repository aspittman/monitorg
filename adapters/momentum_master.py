from adapters.base import Adapter
from services.source_reader import read_csv


class MomentumMaster(Adapter):
    asset_class = 'equity / crypto'

    def read(self):
        data = self.result('logs/trades.csv', 'state/bot_state.json')
        rows = read_csv(self.root/'logs/trades.csv', ('order_id', 'filled_at', 'qty', 'symbol', 'side'))
        by_id = {}
        for row in rows:
            if not row['filled_at']:
                continue
            price = row['entry_price'] if row['side'].lower() == 'buy' else row['exit_price']
            t = self.trade(row['filled_at'], row['symbol'], row['side'], row['qty'], price, row['order_id'])
            by_id[t['order_id']] = t
        data.trades = list(by_id.values())
        data.history_reliable = False
        data.warnings.extend([
            'The reconciliation routine imports account orders by symbol, without checking bot order ownership. Counts and P/L are N/A.',
            'State entries do not contain owned quantities. Protective-stop state overlaps ETFEnhancer (SCHD/XLB). Position ownership is uncertain.',
            'Local records are retained for duplicate-order detection but excluded from the activity feed and bot aggregates.'
        ])
        return data

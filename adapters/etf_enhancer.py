from adapters.base import Adapter
from models.records import position
from services.source_reader import read_csv, read_json


class ETFEnhancer(Adapter):
    def read(self):
        mode = 'paper' if self.env.get('ALPACA_PAPER', 'true').lower() == 'true' else 'live'
        path, state = f'logs/trades_{mode}.csv', f'logs/position_state_{mode}.json'
        data = self.result(path, state)
        rows = read_csv(self.root/path, ('timestamp', 'environment', 'order_id', 'symbol', 'qty', 'price'))
        by_id, excluded = {}, 0
        for row in rows:
            if row['environment'] != mode:
                raise ValueError('Trade environment differs from configured account')
            if row['timestamp'][:10] < '2026-08-21':
                excluded += 1
                continue
            trade = self.trade(row['timestamp'], row['symbol'], row['side'], row['qty'], row['price'], row['order_id'])
            if trade['asset_class'] != 'equity':
                data.history_reliable = False
                data.warnings.append('Unexpected option/crypto execution in equity ledger; attribution requires review.')
            trade['entry_reason' if trade['side']=='buy' else 'exit_reason'] = row.get('reason') or None
            by_id[trade['order_id']] = trade
        data.trades = list(by_id.values())
        self.calculate(data)
        raw = read_json(self.root/state)
        data.positions = [position(s, p['qty'], p['entry_price'], state) for s,p in raw.items()
                          if p.get('entry_order_id') and float(p['qty']) != 0]
        if len(data.positions) != len(raw):
            data.positions = None
            data.warnings.append('Position state lacks reliable quantities or entry order IDs.')
        data.history_scope = 'Post-isolation ledger from 2026-08-21; total means this coverage window'
        data.combined_reliable = False
        data.warnings.append('Realized P/L starts 2026-08-21, but state may retain older entry bases; combined P/L is omitted to avoid mixing coverage periods.')
        data.warnings.append(f'{excluded} pre-2026-08-21 rows excluded: legacy shared-account attribution is unsafe.')
        return data

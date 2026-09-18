from adapters.base import Adapter
from services.source_reader import read_csv


class OptionsEvents(Adapter):
    asset_class = 'option'
    identity = ''
    kind = ''

    def read(self):
        data = self.result('logs/trade_analytics.csv')
        rows = read_csv(self.root/'logs/trade_analytics.csv', ('timestamp', 'event', 'option_symbol', 'order_id'))
        seen, unresolved = set(), set()
        lifecycle = []
        for i, row in enumerate(rows):
            owner = row.get('bot_id') or row.get('bot_strategy') or ''
            if owner and owner != self.identity:
                continue
            event, symbol = row['event'], row['option_symbol']
            if event == 'POSITION_MISSING':
                unresolved.add(symbol)
            elif event == 'POSITION_RECONCILED':
                unresolved.discard(symbol)
            if event not in ('ORDER_FILL', 'EXPIRATION_CONFIRMED'):
                continue
            if row.get('reason') == 'legacy_position' or row['order_id'].startswith('legacy-'):
                data.history_reliable = False
                data.warnings.append('Synthetic legacy position adoption is not an execution; excluded.')
                continue
            t = self.trade(row['timestamp'], symbol, row['order_side'], row['qty'], row['price'],
                           row['order_id'] or f'settlement:{i}', strategy=row.get('strategy'), sequence=i)
            if t['call_put'] != self.kind:
                data.history_reliable = False
                data.warnings.append('Contract type contradicts strategy attribution.')
                continue
            key = (t['order_id'], t['timestamp'], t['quantity'], t['price'])
            if key in seen:
                continue
            seen.add(key)
            lifecycle.append(t)
            if event == 'ORDER_FILL':
                data.trades.append(t)
        # Confirmed expirations affect inventory/P&L, but are not order executions.
        executable = data.trades
        data.trades = lifecycle
        self.calculate(data)
        data.trades = executable
        if unresolved:
            data.positions = None
            data.realized_pl = None
            data.warnings.append('Missing broker positions are unresolved, not assumed sales or worthless expirations: '+', '.join(sorted(unresolved)))
        data.history_scope = 'Active event ledger only; archives/backtests excluded'
        return data

from adapters.base import Adapter
from models.records import position
from services.source_reader import read_csv, read_json


class CCExchange(Adapter):
    asset_class = 'crypto'

    def read(self):
        data = self.result('paper_data/fills.csv', 'state/bot_state.json', 'logs/events.jsonl', 'paper_data/orders.csv')
        rows = read_csv(self.root/'paper_data/fills.csv', ('order_id', 'filled_at', 'quantity'))
        by_id = {}
        for row in rows:
            by_id[row['order_id']] = self.trade(row['filled_at'], row['symbol'], row['side'],
                row['quantity'], row['price'], row['order_id'])
        # Optional explanatory metadata must never invalidate the fill ledger.
        try:
            orders = read_csv(self.root/'paper_data/orders.csv', ('order_id','symbol','side','reason'))
            grouped = {}
            for row in orders:
                grouped.setdefault(row['order_id'], []).append(row)
            for oid, fill in by_id.items():
                matches = grouped.get(oid, [])
                if len(matches) == 1 and matches[0]['symbol'] == fill['symbol'] and matches[0]['side'].lower() == fill['side']:
                    order = matches[0]
                    fill['entry_reason' if fill['side']=='buy' else 'exit_reason'] = order['reason'] or None
                    fill['reason_source'] = 'Recorded paper_data/orders.csv; matched broker order ID, symbol and side'
                    fill['timeframe'] = order.get('timeframe') or None
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            data.warnings.append('Optional order reasons unavailable; fill accounting is unchanged.')
        data.trades = list(by_id.values())
        self.calculate(data)
        raw = read_json(self.root/'state/bot_state.json')['positions']
        tracked = [position(s, p['quantity'], p['entry_price'], 'state/bot_state.json') for s,p in raw.items() if float(p['quantity']) != 0]
        if data.positions != [] and not tracked:
            data.warnings.append('State is flat but fills retain inventory; crypto fees/dust or external activity need reconciliation. Gross P/L excludes fees.')
            data.positions = None
        else:
            data.positions = tracked
        data.warnings.append('paper_data/equity.csv contains account equity; excluded from bot returns.')
        return data

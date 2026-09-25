from adapters.base import Adapter
from services.source_reader import read_csv
from models.records import timestamp, parse_datetime
from config import SOURCE_TIMEZONE
from services.trade_stops import level


class OptionsEvents(Adapter):
    asset_class = 'option'
    identity = ''
    kind = ''

    def read(self):
        data = self.result('logs/trade_analytics.csv')
        rows = read_csv(self.root/'logs/trade_analytics.csv', ('timestamp', 'event', 'option_symbol', 'order_id'))
        seen, unresolved = set(), set()
        lifecycle = []
        stop_cycles = {}
        for i, row in enumerate(rows):
            owner = row.get('bot_id') or row.get('bot_strategy') or ''
            if owner and owner != self.identity:
                continue
            event, symbol = row['event'], row['option_symbol']
            if event == 'POSITION_MISSING':
                unresolved.add(symbol)
                stop_cycles = {k:v for k,v in stop_cycles.items() if k[1] != symbol}
            elif event == 'POSITION_RECONCILED':
                unresolved.discard(symbol)
            if event in ('OPTION_TRAIL_SNAPSHOT', 'RISK_SNAPSHOT'):
                # Follow the exact recorded opening-fill lifecycle, never nearest timestamps.
                cycle = stop_cycles.get((row.get('strategy'), symbol))
                if cycle and len(cycle['fill'].get('stop_history', [])) >= 10000:
                    cycle['fill']['stop_history_truncated'] = True
                elif cycle:
                    field = 'option_trailing_stop' if event == 'OPTION_TRAIL_SNAPSHOT' else 'underlying_trailing_stop'
                    try:
                        details = dict(item.strip().split('=', 1) for item in row.get('details', '').split(';') if '=' in item)
                        price = float(details.get(field, 'nan'))
                        stamp = timestamp(row['timestamp'], SOURCE_TIMEZONE)
                        if level(price) and cycle.get(field) != price and parse_datetime(stamp) >= parse_datetime(cycle['fill']['timestamp']):
                            cycle[field] = price
                            cycle['fill'].setdefault('stop_history', []).append(dict(
                                timestamp=stamp, price=price,
                                stop_id=row.get('strategy', '')+':'+field, label=field.replace('_', ' '),
                                price_basis='option' if event == 'OPTION_TRAIL_SNAPSHOT' else 'underlying',
                                provenance='RECORDED', source='trade_analytics.csv; recorded strategy/contract fill lifecycle'))
                    except (ValueError, TypeError):
                        pass
                continue
            if event not in ('ORDER_FILL', 'EXPIRATION_CONFIRMED'):
                continue
            if row.get('reason') == 'legacy_position' or row['order_id'].startswith('legacy-'):
                stop_cycles.pop((row.get('strategy'), symbol), None)
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
            cycle_key = (row.get('strategy'), symbol)
            if t['side'] == 'buy':
                cycle = stop_cycles.setdefault(cycle_key, {'fill': t, 'quantity': 0})
                cycle['quantity'] += t['quantity']
            elif cycle_key in stop_cycles:
                stop_cycles[cycle_key]['quantity'] -= t['quantity']
                if stop_cycles[cycle_key]['quantity'] <= 1e-8:
                    del stop_cycles[cycle_key]
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

"""Gross average-cost P/L. No account equity is assigned to a bot."""
from models.records import position


def reconstruct(trades, short=False):
    lots, events, trips = {}, [], 0
    opening_side = 'sell' if short else 'buy'
    for trade in sorted(trades, key=lambda x: (x['timestamp'], x.get('sequence', 0))):
        symbol, qty, price = trade['symbol'], trade['quantity'], trade['price']
        lot = lots.setdefault(symbol, {'qty': 0.0, 'cost': 0.0})
        if trade['side'] == opening_side:
            lot['qty'] += qty
            lot['cost'] += qty * price
        else:
            if qty > lot['qty'] + 1e-9 or lot['qty'] <= 0:
                raise ValueError(f'Unmatched closing fill for {symbol}; cost basis unavailable')
            average = lot['cost'] / lot['qty']
            pnl = (price-average) * qty * trade['multiplier'] * (-1 if short else 1)
            trade['realized_pl'] = pnl
            events.append({'timestamp': trade['timestamp'], 'realized_pl': pnl})
            lot['qty'] -= qty
            lot['cost'] -= average * qty
            if abs(lot['qty']) < 1e-9:
                lot['qty'], lot['cost'] = 0, 0
                trips += 1
    positions = [position(s, l['qty'] * (-1 if short else 1), l['cost']/l['qty'],
                          'Reconstructed local fill ledger') for s, l in lots.items() if l['qty'] > 1e-9]
    return positions, events, trips


def simple_return(start_equity, end_equity, net_flow=0):
    """Only valid with a verified bot baseline and no intervening cash flows.

    Caller must supply complete, period-aligned bot valuations. No current adapter
    has this evidence, so dashboard daily/month/total returns remain null.
    """
    if start_equity is None or end_equity is None or start_equity <= 0 or net_flow != 0:
        return None
    return 100 * (end_equity / start_equity - 1)

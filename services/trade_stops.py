"""Read stop evidence without evaluating strategies or submitting broker requests."""
import csv
import json
import math
from datetime import datetime, timezone


def level(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def event_stops(events):
    result = []
    for event in events:
        risk = event.get('risk', {})
        snapshots = risk.get('stops', [risk])
        if not isinstance(snapshots, list):
            continue
        for stop in snapshots[:20]:
            if not isinstance(stop, dict) or stop.get('price_basis') not in ('underlying', 'option'):
                continue
            price = stop.get('current_stop', stop.get('initial_stop'))
            inactive = stop.get('active') is False
            if not level(price) and not inactive:
                continue
            result.append(dict(timestamp=event['timestamp'], price=None if inactive else price,
                               stop_id=str(stop.get('stop_id', 'stop'))[:128],
                               label=str(stop.get('label', 'Stop loss'))[:128],
                               price_basis=stop['price_basis'], provenance=event['provenance'],
                               source=event.get('source', 'Bot decision telemetry')))
    return result


def legacy_stops(root, bot, trade):
    """Only exact order matches provide historical linkage; no symbol/time guessing."""
    if root is None:
        return []
    root = root / bot
    result = []
    ids = set(trade.get('order_ids', []))
    if bot == 'ccexchange':
        path = root / 'logs/events.jsonl'
        orders_path = root / 'paper_data/orders.csv'
        if not path.exists() or not orders_path.exists():
            return []
        # Optional sources are bounded independently of the trade ledger.
        if path.stat().st_size > 32 * 1024 * 1024 or orders_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Stop evidence source exceeds read limit')
        with orders_path.open() as stream:
            orders = {}
            for row in csv.DictReader(stream):
                if row.get('order_id') in ids and row.get('symbol') == trade['symbol']:
                    orders.setdefault(row['order_id'], []).append(row)
        with path.open() as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                    rows = orders.get(event.get('order_id'), [])
                    if len(rows) != 1 or event.get('symbol') != trade['symbol']:
                        continue
                    row = rows[0]
                    side = {'BUY_SUBMITTED': 'buy', 'SELL_SUBMITTED': 'sell'}.get(event.get('event'))
                    if side is None or side != row.get('side', '').lower():
                        continue
                    price = event.get('initial_stop') if side == 'buy' else event.get('stop')
                    stamp = row.get('submitted_at') or row.get('timestamp')
                    if not level(price) or not stamp:
                        continue
                    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                    if parsed.tzinfo is None:
                        continue
                    result.append(dict(timestamp=parsed.isoformat(), price=price, stop_id='atr',
                                       label='ATR stop', price_basis='underlying', provenance='RECORDED',
                                       source='events.jsonl stop matched to orders.csv submission by exact order ID; intermediate stop changes unavailable'))
                except (ValueError, TypeError, AttributeError):
                    continue
    elif bot == 'ETFEnhancer' and trade.get('status') == 'OPEN' and trade.get('current'):
        # Current state cannot tell us when this stop was created. Never backdate it.
        for mode in ('paper', 'live'):
            path = root / ('logs/position_state_' + mode + '.json')
            if not path.exists():
                continue
            if path.stat().st_size > 1024 * 1024:
                continue
            state = json.loads(path.read_text()).get(trade['symbol'], {})
            if state.get('entry_order_id') not in ids:
                continue
            price = state.get('current_structural_stop')
            if level(price):
                result.append(dict(timestamp=datetime.now(timezone.utc).isoformat(), price=price,
                                   stop_id='structural', label='Current structural stop', current_only=True,
                                   price_basis='underlying', provenance='RECORDED',
                                   source='Observed in '+path.name+'; creation time and historical changes unavailable'))
    elif bot == 'momentum_master' and trade.get('status') == 'OPEN' and trade.get('current'):
        path = root / 'state/bot_state.json'
        if path.exists() and path.stat().st_size <= 1024 * 1024:
            state = json.loads(path.read_text())
            # A current local reference only, never evidence about a historical entry.
            price = state.get('trailing_stops', {}).get(trade['symbol'])
            if level(price):
                result.append(dict(timestamp=datetime.now(timezone.utc).isoformat(), price=price,
                                   stop_id='trailing', label='Local current trailing stop', current_only=True,
                                   price_basis='underlying', provenance='RECORDED',
                                   source='Observed local bot_state.json for current owned symbol; creation time and broker stop acceptance unverified'))
    return result

from datetime import datetime
from models.records import parse_datetime


def counts(trades, now, timezone):
    """One distinct order with positive fill quantity, assigned to its first fill."""
    first = {}
    for trade in trades:
        order = trade['order_id']
        time = parse_datetime(trade.get('count_timestamp',trade['timestamp']))
        first[order] = min(time, first.get(order, time))
    dates = [t.astimezone(timezone).date() for t in first.values() if t <= now]
    today = now.astimezone(timezone).date()
    uncertain_time = any(t.get('estimated_time') for t in trades)
    return dict(trades_today=None if uncertain_time else sum(d == today for d in dates),
                trades_month=None if uncertain_time else sum((d.year,d.month) == (today.year,today.month) for d in dates),
                trades_total=len(dates))

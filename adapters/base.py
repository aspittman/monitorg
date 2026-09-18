from datetime import datetime, timezone
from pathlib import Path

from config import SOURCE_TIMEZONE
from models.records import BotData, asset, number, timestamp
from services.performance_service import reconstruct


class Adapter:
    asset_class = 'equity'

    def __init__(self, root, bot_id, env=None):
        self.root, self.bot_id, self.env = Path(root), bot_id, env or {}

    def result(self, *paths):
        data = BotData(self.bot_id, self.asset_class)
        files = [self.root / p for p in paths]
        data.source_files = [str(p) for p in files]
        stamps = [p.stat().st_mtime for p in files if p.exists()]
        if stamps:
            data.source_updated_at = datetime.fromtimestamp(max(stamps), timezone.utc).isoformat()
        return data

    def trade(self, stamp, symbol, side, qty, price, order_id, fill_id=None, strategy=None, sequence=0):
        qty, price = number(qty), number(price)
        if not symbol or side.lower() not in ('buy', 'sell') or qty is None or qty <= 0 or price is None or price < 0:
            raise ValueError('Invalid fill fields')
        if not order_id:
            raise ValueError('Fill lacks order identity; cannot deduplicate reliably')
        if asset(symbol)['multiplier'] is None:
            raise ValueError('Adjusted option contract needs explicit deliverable/multiplier data')
        return dict(bot_id=self.bot_id, timestamp=timestamp(stamp, SOURCE_TIMEZONE), symbol=symbol,
                    side=side.lower(), quantity=qty, price=price, premium=price if asset(symbol)['asset_class']=='option' else None,
                    order_id=str(order_id), fill_id=str(fill_id) if fill_id is not None else None,
                    strategy=strategy, realized_pl=None, sequence=sequence, **asset(symbol))

    def calculate(self, data, short=False):
        try:
            positions, events, trips = reconstruct(data.trades, short=short)
            data.positions, data.pnl_events, data.round_trips = positions, events, trips
            data.realized_pl = sum(e['realized_pl'] for e in events)
        except ValueError as exc:
            data.warnings.append(str(exc))
        return data

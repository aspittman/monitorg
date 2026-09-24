from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re

OPTION = re.compile(r'^([A-Z0-9.]+)(\d{6})([CP])(\d{8})$')


def number(value):
    if value is None or value == '':
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite numeric value')
    return result


def parse_datetime(value):
    text = str(value).replace('Z', '+00:00')
    # Python 3.10 only accepts 3/6 fractional digits. Alpaca sends 1–9.
    text = re.sub(r'(T| )(\d{2}:\d{2}:\d{2})\.(\d+)',
                  lambda m: m[1]+m[2]+'.'+m[3][:6].ljust(6,'0'), text)
    return datetime.fromisoformat(text)


def timestamp(value, naive_tz):
    result = parse_datetime(value)
    if result.tzinfo is None:
        # Reject ambiguous/nonexistent wall times instead of guessing a DST fold.
        first, second = result.replace(tzinfo=naive_tz, fold=0), result.replace(tzinfo=naive_tz, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError('Ambiguous or nonexistent local timestamp')
        result = first
    return result.astimezone(timezone.utc).isoformat()


def asset(symbol):
    match = OPTION.fullmatch(symbol)
    if match:
        root, expiry, kind, strike = match.groups()
        return dict(asset_class='option', underlying=root, contract_symbol=symbol,
                    expiration=datetime.strptime(expiry, '%y%m%d').date().isoformat(),
                    strike=int(strike)/1000, call_put='call' if kind == 'C' else 'put',
                    multiplier=None if any(c.isdigit() for c in root) else 100)
    return dict(asset_class='crypto' if '/' in symbol else 'equity', underlying=symbol,
                contract_symbol=None, expiration=None, strike=None, call_put=None, multiplier=1)


def position(symbol, qty, entry, source):
    return dict(symbol=symbol, quantity=number(qty), entry=number(entry), current_price=None,
                unrealized_pl=None, unrealized_percent=None, source=source, **asset(symbol))


@dataclass
class BotData:
    bot_id: str
    asset_class: str
    trades: list = field(default_factory=list)
    positions: list | None = None
    history_reliable: bool = True
    history_scope: str = 'Available local ledger (not guaranteed lifetime history)'
    realized_pl: float | None = None
    combined_reliable: bool = True
    round_trips: int | None = None
    pnl_events: list = field(default_factory=list)
    return_events: list = field(default_factory=list)
    return_error: str | None = None
    warnings: list = field(default_factory=list)
    source_files: list = field(default_factory=list)
    source_updated_at: str | None = None
    parse_error: bool = False

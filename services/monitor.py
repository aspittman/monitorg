import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

import config
from adapters.registry import ADAPTERS
from models.records import BotData, parse_datetime
from services.account_registry import discover
from services.alpaca_reader import AlpacaReader, activity_side
from services.process_monitor import inspect
from services.snapshot_store import SnapshotStore
from services.source_reader import signature
from services.trade_service import counts
from services.ownership_service import load_registry, reconcile


class Monitor:
    def __init__(self, bot_root=config.BOT_ROOT, data_dir=config.DATA_DIR, alpaca=config.ALPACA_ENABLED):
        self.bot_root, self.data_dir, self.alpaca = bot_root, data_dir, alpaca
        self.accounts, self.environments, self.membership = discover(bot_root, config.BOTS)
        self.store = SnapshotStore(data_dir/'botmonitor.db')
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.cache, self.account_data, self.dashboard = {}, {}, None
        self.last_snapshot = 0
        self.previous_status = {}
        registry = [dict(account=a['label'], paper=a['paper'], bots=a['bots'],
                        identity_basis='Same configured API key; live account ID checked when reachable') for a in self.accounts]
        (data_dir/'account_registry.json').write_text(json.dumps(registry, indent=2)+'\n')

    def read_bot(self, bot):
        adapter = ADAPTERS[bot](self.bot_root/bot, bot, self.environments[bot])
        old = self.cache.get(bot)
        if old and old[0] == [(p, signature(p)) for p in old[1].source_files]:
            return copy.deepcopy(old[1])
        try:
            result = adapter.read()
            self.cache[bot] = ([(p, signature(p)) for p in result.source_files], copy.deepcopy(result))
            return result
        except Exception as exc:
            result = BotData(bot, adapter.asset_class, history_reliable=False, parse_error=True)
            # Never include arbitrary config content or a broker response in an error.
            message = str(exc) if isinstance(exc, (ValueError, KeyError)) else type(exc).__name__
            result.warnings.append('Missing/unreadable data or parsing error: '+message[:200])
            return result

    def refresh_accounts(self):
        def fetch(account):
            public = dict(account=account['label'], bots=account['bots'], paper=account['paper'])
            try:
                reader = AlpacaReader(account)
                public.update(reader.snapshot())
                public['error'] = None
                try:
                    now = datetime.now(config.TIMEZONE)
                    after = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat()
                    self.store.cache_fills(public['identity'], reader.fills(after, max_pages=20))
                except Exception:
                    public['fill_warning'] = 'Broker fill history unavailable/incomplete; local timestamp limitations remain.'
                public['month_fills'] = self.store.cached_fills(public['identity'])
                try:
                    public['ownership_registry'] = load_registry(self.bot_root,self.data_dir,public['identity'])
                    if public['ownership_registry']:
                        public['crypto_fees'] = reader.activities('CFEE',public['ownership_registry']['observed_at'],max_pages=20)
                        for cid,owner in public['ownership_registry']['pending_clients']:
                            order = reader.get('/v2/orders:by_client_order_id', {'client_order_id':cid})
                            public['ownership_registry']['order_owners'][order['id']] = owner
                except Exception:
                    public['ownership_error'] = 'Ownership registry or pending order could not be verified.'
            except Exception as exc:
                public.update(error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
                              positions=None, equity=None, cash=None, observed_at=None)
            return account['label'], public
        if self.alpaca:
            with ThreadPoolExecutor(max_workers=4) as pool:
                values = dict(pool.map(fetch, self.accounts))
            with self.lock:
                self.account_data = values

    def refresh(self, now=None):
        now = now or datetime.now(timezone.utc)
        process = inspect(self.bot_root, config.BOTS)
        data = [self.read_bot(bot) for bot in config.BOTS]
        with self.lock:
            accounts = copy.deepcopy(self.account_data)
        # Alias separately keyed credentials only after matching actual account identity.
        aliases, identities = {}, {}
        for label, account in accounts.items():
            if account.get('identity'):
                canonical = identities.setdefault(account['identity'], label)
                aliases[label] = canonical
        for d in data:
            label = self.membership[d.bot_id]
            account = accounts.get(aliases.get(label,label), {})
            # Prefer broker execution time only when immutable order ID, side,
            # symbol and complete filled quantity match the attributable local order.
            for trade in d.trades:
                matches = [f for f in account.get('month_fills', []) if f.get('order_id')==trade['order_id']
                           and f.get('symbol')==trade['symbol'] and activity_side(f.get('side'))==trade['side']]
                same_order = [t for t in d.trades if t['order_id']==trade['order_id']]
                local_quantity = sum(t['quantity'] for t in same_order)
                if matches and abs(sum(float(f['qty']) for f in matches)-local_quantity) < 1e-9:
                    earliest = min(parse_datetime(f['transaction_time']) for f in matches)
                    # A migrated timestamp is the order creation time; do not accept
                    # an impossible earlier fill for that order.
                    if not trade.get('estimated_time') or earliest >= datetime.fromisoformat(trade['timestamp']):
                        trade['count_timestamp'] = earliest.astimezone(timezone.utc).isoformat()
                        if len(same_order)==1:
                            trade['source_timestamp'] = trade['timestamp']
                            trade['timestamp'] = trade['count_timestamp']
                        trade['estimated_time'] = False
                        trade['time_source'] = 'Verified Alpaca fill activity'
            if d.trades and not any(t.get('estimated_time') for t in d.trades):
                d.warnings = [w for w in d.warnings if not w.startswith('Migrated fill timestamps')]
        order_owners = {}
        reliable_owners = {d.bot_id for d in data if d.history_reliable}
        for d in data:
            for t in d.trades:
                key = (aliases.get(self.membership[d.bot_id], self.membership[d.bot_id]), t['order_id'])
                order_owners.setdefault(key, set()).add(d.bot_id)
        for d in data:
            duplicate = {b for t in d.trades for b in order_owners[(aliases.get(self.membership[d.bot_id], self.membership[d.bot_id]), t['order_id'])] if b != d.bot_id}
            if duplicate:
                d.warnings.append('Order IDs also occur in '+', '.join(sorted(duplicate))+'. Shared-account imports are excluded from aggregates.')
                if duplicate & reliable_owners and d.history_reliable:
                    # Do not arbitrarily choose an owner if both sources claim reliable ownership.
                    d.history_reliable = False
        bots, recent = [], []
        for d in data:
            label = self.membership[d.bot_id]
            label = aliases.get(label, label)
            account = accounts.get(label)
            if account and account.get('observed_at') and (now-datetime.fromisoformat(account['observed_at'])).total_seconds() > config.ACCOUNT_SECONDS*3:
                account = None
            if account and account.get('positions') is not None:
                reconcile(d, account)
            b = asdict(d)
            b.update(process[d.bot_id], account=label, daily_return=None, monthly_return=None, total_return=None,
                     unrealized_pl=None, combined_pl=None, open_positions=None, position_as_of=d.source_updated_at,
                     return_explanation='N/A: no complete period-aligned bot equity/cash-flow history. Account equity and current risk budgets are not bot return baselines.')
            if d.parse_error:
                b['monitor_status'] = 'ERROR'
            else:
                b['monitor_status'] = 'OK'
            if self.previous_status.get(d.bot_id) == 'RUNNING' and b['status'] == 'STOPPED':
                b['warnings'].append('Process disappeared since last refresh; whether this was scheduled is unknown.')
            self.previous_status[d.bot_id] = b['status']
            if label is None:
                b['warnings'].append('Missing Alpaca credentials/configuration; local data only.')
            if d.source_updated_at and (now-datetime.fromisoformat(d.source_updated_at)).total_seconds() > config.STALE_SECONDS:
                b['warnings'].append('Source files are stale; local records may not describe current broker holdings.')
                b['monitor_status'] = 'STALE' if not d.parse_error else 'ERROR'
            b.update(counts(d.trades, now, config.TIMEZONE) if d.history_reliable else
                     dict(trades_today=None, trades_month=None, trades_total=None))
            if not d.history_reliable:
                b['realized_pl'] = None
                b['round_trips'] = None
            if d.positions is not None:
                b['open_positions'] = len(d.positions)
                b['position_confidence'] = 'Local ledger/state; not broker reconciled'
                if account and account.get('positions') is not None:
                    broker_positions = {p['symbol']: p for p in account['positions']}
                    confirmed = True
                    for p in b['positions']:
                        market = broker_positions.get(p['symbol'])
                        owned = p['quantity']
                        if not market or market['quantity']*owned <= 0 or abs(market['quantity']) + 1e-8 < abs(owned):
                            confirmed = False
                            b['warnings'].append('Broker quantity does not support local ownership of '+p['symbol'])
                            continue
                        price = market['current_price']
                        p['current_price'] = price
                        if price is not None and p['entry'] is not None:
                            p['unrealized_pl'] = (price-p['entry'])*owned*p['multiplier']
                            cost = abs(p['entry']*owned*p['multiplier'])
                            p['unrealized_percent'] = 100*p['unrealized_pl']/cost if cost else None
                    if confirmed:
                        b['position_confidence'] = 'Bot-owned quantities checked against account; prices from broker'
                        b['position_as_of'] = account['observed_at']
                    else:
                        b['open_positions'] = None
                        b['position_confidence'] = 'Uncertain: local/broker mismatch'
                if b['positions'] == []:
                    b['unrealized_pl'] = 0.0
                elif b['open_positions'] is not None and all(p['unrealized_pl'] is not None for p in b['positions']):
                    b['unrealized_pl'] = sum(p['unrealized_pl'] for p in b['positions'])
            else:
                b['position_confidence'] = 'Unknown ownership'
            if d.combined_reliable and b['realized_pl'] is not None and b['unrealized_pl'] is not None:
                b['combined_pl'] = b['realized_pl']+b['unrealized_pl']
            # Detailed records remain available only where attribution is defensible.
            b['recent_trades'] = sorted(d.trades, key=lambda t:t['timestamp'], reverse=True)[:100] if d.history_reliable else []
            b.pop('trades')
            if d.history_reliable:
                recent.extend(d.trades)
            bots.append(b)
        # Check collectively claimed quantities, including multiple bots in the same account.
        claims = {}
        for b in bots:
            for p in b['positions'] or []:
                claims.setdefault((b['account'], p['symbol']), []).append((b,p))
        for (label, symbol), owners in claims.items():
            account = accounts.get(label)
            if len(owners) > 1:
                for b,p in owners:
                    b['warnings'].append(f'{symbol} is claimed by multiple bots; ownership is uncertain.')
                    b.update(open_positions=None, unrealized_pl=None, combined_pl=None, position_confidence='Overlapping bot ownership')
        public_accounts, handled = [], set()
        for a in self.accounts:
            label = aliases.get(a['label'], a['label'])
            if label in handled:
                continue
            handled.add(label)
            account = copy.deepcopy(accounts.get(label, dict(account=label, bots=a['bots'], paper=a['paper'],
                equity=None, cash=None, positions=None, observed_at=None,
                error='Alpaca disabled (local-only mode)' if not self.alpaca else 'Waiting for read-only Alpaca data')))
            account.pop('identity', None)
            account.pop('month_fills', None)
            account.pop('ownership_registry', None)
            account.pop('crypto_fees', None)
            account['bots'] = [b['bot_id'] for b in bots if b['account']==label]
            for p in account.get('positions') or []:
                p['claimed_by'] = [b['bot_id'] for b,pos in claims.get((label,p['symbol']), [])]
                p['ownership'] = 'Uncertain / account only' if not p['claimed_by'] else 'Local claim; see bot detail'
            public_accounts.append(account)
        def aggregate(field):
            values = [b[field] for b in bots]
            return dict(value=sum(values) if all(v is not None for v in values) else None,
                        known_subtotal=sum(v for v in values if v is not None), covered_bots=sum(v is not None for v in values))
        dashboard = dict(timestamp=now.isoformat(), timezone=str(config.TIMEZONE), refresh_seconds=config.REFRESH_SECONDS,
            snapshot_seconds=config.SNAPSHOT_SECONDS, bots=bots, accounts=public_accounts,
            recent_activity=sorted(recent, key=lambda t:t['timestamp'], reverse=True)[:80],
            summary=dict(running_bots=sum(b['status']=='RUNNING' for b in bots),
                         positions=aggregate('open_positions'), trades_today=aggregate('trades_today'), trades_month=aggregate('trades_month')),
            trade_definition='One distinct order with positive confirmed fill quantity, counted on its first recorded fill date. BUY + SELL = 2. Partial fills of the same order count once.',
            aggregate_pl=None,
            aggregate_pl_reason='Incomplete attribution and different ledger coverage windows prevent a valid portfolio P/L total.')
        if time.monotonic()-self.last_snapshot >= config.SNAPSHOT_SECONDS:
            try:
                self.store.write(dashboard)
                self.last_snapshot = time.monotonic()
            except Exception:
                dashboard['storage_error'] = 'Monitoring snapshot write failed; trading bots are unaffected.'
        with self.lock:
            self.dashboard = dashboard
        return dashboard

    def start(self):
        def local_loop():
            while not self.stop.is_set():
                try:
                    self.refresh()
                except Exception:
                    with self.lock:
                        if self.dashboard:
                            self.dashboard['refresh_error'] = 'Monitoring refresh failed; displayed data is from the last successful refresh.'
                self.stop.wait(config.REFRESH_SECONDS)
        def account_loop():
            while not self.stop.is_set():
                self.refresh_accounts()
                self.stop.wait(config.ACCOUNT_SECONDS)
        threading.Thread(target=local_loop, daemon=True, name='local-monitor').start()
        if self.alpaca:
            threading.Thread(target=account_loop, daemon=True, name='account-reader').start()

    def get_dashboard(self):
        with self.lock:
            return copy.deepcopy(self.dashboard)

"""Read-only use of audited ownership and the independent trading registry."""
import json
import sqlite3
from pathlib import Path
from models.records import position, parse_datetime


def key(symbol):
    return symbol.upper().replace('/', '')


def load_registry(bot_root, data_dir, identity):
    baseline_path = Path(data_dir)/'ownership_baseline.json'
    if not baseline_path.exists():
        return None
    seed = json.loads(baseline_path.read_text())['accounts'].get(identity)
    if not seed:
        return None
    result = dict(seed)
    result['claims'] = {s:dict(row) for s,row in seed['claims'].items()}
    result['seed_claims'] = seed['claims']
    result['order_owners'] = dict(seed['legacy_orders'])
    result['pending_clients'] = []
    db_path = Path(bot_root)/'trading_ownership/ownership.sqlite3'
    if db_path.exists():
        db = sqlite3.connect(db_path.as_uri()+'?mode=ro', uri=True, timeout=2)
        try:
            db.execute('PRAGMA query_only=ON')
            for symbol,owner in db.execute('SELECT symbol,owner FROM claims WHERE account=?',(identity,)):
                result['claims'].setdefault(symbol, {})['owner'] = owner
            for oid,owner in db.execute('SELECT broker_id,owner FROM verified_orders WHERE account=?',(identity,)):
                if owner: result['order_owners'][oid]=owner
            for cid,owner,oid in db.execute('SELECT client_id,owner,broker_id FROM requests WHERE account=?',(identity,)):
                if oid:
                    result['order_owners'][oid] = owner
                else:
                    result['pending_clients'].append((cid,owner))
        finally:
            db.close()
    return result


def reconcile(data, account):
    """Only repair adapters whose local ownership was previously unavailable.

    Net quantities must match the audited baseline plus attributable broker fill
    activity. Unknown intervening executions invalidate affected instruments.
    This never assigns an entire shared account to one bot.
    """
    if data.bot_id not in ('ccexchange','momentum_master','ETFEnhancerLT'):
        return
    registry = account.get('ownership_registry')
    if not registry:
        return
    if account.get('ownership_error') or account.get('fill_warning'):
        data.positions = None
        data.warnings.append('Ownership reconciliation unavailable/incomplete; no position estimate substituted.')
        return
    claims = registry['claims']
    broker = {key(p['symbol']):p for p in account['positions']}
    expected = {(s,row['owner']):float(row.get('quantity',0)) for s,row in registry.get('seed_claims',claims).items()}
    unknown = set()
    fill_owners = {}
    for fill in account.get('month_fills',[]):
        if parse_datetime(fill['transaction_time']) <= parse_datetime(registry['observed_at']):
            continue
        symbol=key(fill['symbol']); owner=registry['order_owners'].get(fill['order_id'])
        if symbol not in claims or owner is None:
            unknown.add(symbol)
            continue
        fill_owners.setdefault(symbol,set()).add(owner)
        pair=(symbol,owner)
        expected[pair] = expected.get(pair,0) + float(fill['qty'])*(1 if fill['side']=='buy' else -1)
    for fee in account.get('crypto_fees',[]):
        if not fee.get('symbol') or not fee.get('qty') or parse_datetime(fee['created_at'])<=parse_datetime(registry['observed_at']):
            continue
        symbol=key(fee['symbol']); owners=fill_owners.get(symbol,set())
        if len(owners)!=1:
            unknown.add(symbol);continue
        pair=(symbol,next(iter(owners)))
        expected[pair]=expected.get(pair,0)+float(fee['qty'])
    owned=[]
    for symbol,row in claims.items():
        if row['owner'] != data.bot_id:
            continue
        market=broker.get(symbol); quantity=market['quantity'] if market else 0
        other_inventory=any(s==symbol and owner!=data.bot_id and abs(qty)>1e-8 for (s,owner),qty in expected.items())
        if symbol in unknown or other_inventory or abs(quantity-expected.get((symbol,data.bot_id),0))>1e-8:
            data.positions=None
            data.warnings.append('Audited ownership no longer reconciles for '+symbol+'; review intervening fills/settlements.')
            return
        if quantity:
            owned.append(position(market['symbol'],quantity,market['entry'],'Verified account/instrument registry and broker fills'))
    unassigned = set(broker)-set(claims)
    # A formerly untagged equity bot could own new unassigned stock holdings.
    relevant = [s for s in unassigned if (broker[s]['asset_class']=='crypto') == (data.bot_id=='ccexchange')]
    if relevant:
        data.positions=None
        data.warnings.append('Unassigned account holdings prevent complete ownership reconciliation: '+', '.join(sorted(relevant)))
        return
    if data.bot_id=='ccexchange':
        evidence=registry.get('crypto_reconciliation') or {}
        if not evidence.get('flat_verified'):
            return
        # The original remainder was three broker-recorded BTC fee debits.
        # Future orders need registry attribution, not this historical exception.
        if any(t['order_id'] not in evidence['order_ids'] and registry['order_owners'].get(t['order_id'])!='ccexchange' for t in data.trades):
            return
        data.warnings=[w for w in data.warnings if not w.startswith('State is flat but fills retain')]
        data.warnings.append('BTC inventory reconciled with broker crypto fees: 0.000479421 BTC deducted on September 3. Displayed realized P/L remains gross; fee-adjusted P/L is not yet calculated.')
        data.combined_reliable=False
    elif data.bot_id=='momentum_master':
        data.warnings=[w for w in data.warnings if not w.startswith('State entries do not contain')]
        data.warnings.append('Positions reconciled from broker-verified CRWD/NVDA entry IDs plus registered subsequent fills. Older mixed-account trade history remains excluded.')
    else:
        data.warnings=[w for w in data.warnings if not w.startswith(('live_positions.csv','No bot-specific'))]
        data.warnings.append('Position ownership uses the audited account/instrument registry. Backtest and shared-account logs remain excluded from bot performance.')
    data.positions=owned

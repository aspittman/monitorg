"""Evidence-only trade journal and snapshot audit; no strategy reimplementation."""
import hashlib
from models.records import parse_datetime


def identity(*parts):
    return hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()[:24]


def journal_from_fills(bot, fills, public):
    """Average-cost position cycles, preserving partial fills and unknown bases.

    This is ledger reconstruction, never a historical strategy reconstruction.
    """
    rows, active = [], {}
    if public.get('history_reliable'):
        for f in sorted(fills,key=lambda x:(x['timestamp'],x.get('sequence',0))):
            symbol=f['symbol']
            short=bot in ('options_secured','options_covered') and f.get('asset_class')=='option'
            opening='sell' if short else 'buy'
            t=active.get(symbol)
            if f['side']==opening:
                if t is None:
                    t=dict(trade_id='ledger-'+identity(bot,symbol,f['order_id']),symbol=symbol,status='OPEN',
                           entry_time=f['timestamp'],exit_time=None,entry_price=None,exit_price=None,
                           quantity=0,opening_value=0,remaining=0,pnl=0,capital=0,return_percent=None,
                           direction='SHORT' if short else 'LONG',provenance='RECONSTRUCTED',
                           source='Reconstructed from attributable fill ledger; decisions unavailable',
                           entry_reason=None,exit_reason=None,order_ids=[],fills=[],cost=0,close_value=0,closed_qty=0,
                           asset_class=f.get('asset_class'),underlying=f.get('underlying'),
                           contract={k:f.get(k) for k in ('contract_symbol','call_put','strike','expiration','multiplier')})
                    active[symbol]=t
                t['quantity']+=f['quantity'];t['remaining']+=f['quantity'];t['cost']+=f['quantity']*f['price']
                t['opening_value']+=f['quantity']*f['price']
                t['entry_price']=t['opening_value']/t['quantity']
            elif t is None or f['quantity']>t['remaining']+1e-8:
                rows.append(dict(trade_id='unmatched-'+identity(bot,f['order_id'],f.get('sequence',0)),symbol=symbol,
                                 status='INCOMPLETE',entry_time=None,exit_time=f['timestamp'],pnl=None,
                                 provenance='INCOMPLETE',source='Closing fill without a matched entry',order_ids=[f['order_id']],fills=[f]))
                if t:
                    t['status']='INCOMPLETE';t['pnl']=None;rows.append(t);active.pop(symbol)
                continue
            else:
                q=f['quantity'];average=t['cost']/t['remaining'];mult=f['multiplier']
                t['pnl']+=(f['price']-average)*q*mult*(-1 if short else 1)
                capital=(f.get('strike')*q*mult if f.get('call_put')=='put' else None) if short else average*q*mult
                t['capital']=None if capital is None or t['capital'] is None else t['capital']+capital
                t['cost']-=average*q;t['remaining']-=q;t['closed_qty']+=q;t['close_value']+=f['price']*q
                t['exit_price']=t['close_value']/t['closed_qty']
                if t['remaining']<1e-8:
                    t['status']='CLOSED';t['exit_time']=f['timestamp'];active.pop(symbol);rows.append(t)
            t['fills'].append(f);t['order_ids'].append(f['order_id'])
            if f.get('entry_reason'):t['entry_reason']=f['entry_reason']
            if f.get('exit_reason'):t['exit_reason']=f['exit_reason']
            t['return_percent']=100*t['pnl']/t['capital'] if t['capital'] else None
            t['estimated_time']=t.get('estimated_time',False) or f.get('estimated_time',False)
    rows.extend(active.values())
    positions={p['symbol']:p for p in public.get('positions') or []}
    for t in rows:
        if t['status']=='OPEN':
            # Do not call remaining ledger inventory a current broker position.
            t['current']=positions.get(t['symbol'])
            t['current_as_of']=public.get('position_as_of')
            t['position_confidence']=public.get('position_confidence')
            if public.get('position_confidence') in ('Overlapping bot ownership','Uncertain: local/broker mismatch'):
                t['current']=None
            if t['current'] is None or abs(abs(t['current']['quantity'])-t['remaining'])>1e-8:
                t['status']='UNRECONCILED'
        if t.get('entry_time') and t.get('exit_time') and not t.get('estimated_time'):
            t['hold_seconds']=(parse_datetime(t['exit_time'])-parse_datetime(t['entry_time'])).total_seconds()
    for symbol,p in positions.items():
        if not any(t['symbol']==symbol and t['status'] in ('OPEN','UNRECONCILED') for t in rows):
            rows.append(dict(trade_id='position-'+identity(bot,symbol),symbol=symbol,status='UNRECONCILED' if public.get('position_confidence') in ('Overlapping bot ownership','Uncertain: local/broker mismatch') else 'OPEN',
                             entry_time=None,entry_price=p.get('entry'),pnl=None,asset_class=p.get('asset_class'),
                             direction='SHORT' if p['quantity']<0 else 'LONG',quantity=abs(p['quantity']),remaining=abs(p['quantity']),
                             contract={k:p.get(k) for k in ('contract_symbol','call_put','strike','expiration','multiplier')},current=p,current_as_of=public.get('position_as_of'),
                             position_confidence=public.get('position_confidence'),order_ids=[],fills=[],provenance='INCOMPLETE',
                             source='Current owned position; historical entry linkage unavailable'))
    return rows


def audit(events, closed=False):
    results=[]
    for phase,kind in (('ENTRY','ENTRY_DECISION'),('EXIT','EXIT_DECISION')):
        snapshots=[e for e in events if e['event_type']==kind]
        if not snapshots:
            results.append(dict(phase=phase,status='INCOMPLETE DATA',reason='Decision snapshot unavailable'))
            continue
        for e in snapshots:
            conditions=e.get('conditions',[])
            complete=e.get('conditions_complete') is True and e.get('provenance')=='RECORDED'
            known=conditions and all(type(c.get('passed')) is bool and type(c.get('required')) is bool for c in conditions)
            status,reason='INCOMPLETE DATA','Complete recorded rule snapshot and explicit action required'
            if complete and known and e.get('decision') in ('BUY','SELL','APPROVE','EXIT'):
                if phase=='ENTRY':
                    failed=[c['name'] for c in conditions if c.get('required') and not c['passed']]
                    if failed:status,reason='POSSIBLE RULE VIOLATION','Approved despite failed required rules: '+', '.join(failed)
                    elif any(c.get('required') for c in conditions):status,reason='VALID','Recorded approval satisfies all recorded required rules'
                elif e.get('exit_policy')=='ANY_TRIGGER':
                    status,reason=('VALID','At least one recorded exit condition triggered') if any(c['passed'] for c in conditions) else ('UNEXPLAINED','No recorded exit condition triggered')
            results.append(dict(phase=phase,status=status,reason=reason,event_id=e['event_id']))
    return results


def diagnostics(events):
    """Only explicit completed evaluation evidence can imply a missed order."""
    result=[]
    for e in events:
        p=e.get('pipeline',{})
        if (e['event_type']=='ENTRY_DECISION' and e.get('provenance')=='RECORDED'
            and e.get('conditions_complete') is True and e.get('decision') in ('BUY','SELL','APPROVE')
            and any(c.get('required') for c in e.get('conditions',[]))
            and all(c.get('passed') is True for c in e['conditions'] if c.get('required'))
            and all(type(c.get('required')) is bool for c in e['conditions'])
            and p.get('evaluation_complete') is True and p.get('capital_sufficient') is True
            and p.get('risk_allowed') is True and p.get('order_submitted') is False):
            result.append(dict(status='POSSIBLE MISSED TRADE',event_id=e['event_id'],reason='Bot explicitly recorded complete evaluation, sufficient capital, risk approval, and no submission. Investigate; this is not proof of a bug.'))
        if e['event_type'] in ('ORDER_REJECTED','ORDER_CANCELLED','ORDER_EXPIRED'):
            result.append(dict(status=e['event_type'],event_id=e['event_id'],reason=e.get('reason') or 'Recorded terminal order outcome; fill quantity may be partial or unknown'))
    return result


class ExplainService:
    def __init__(self, store):
        self.store=store

    def sync(self, bot, fills, public):
        import json
        with self.store.connect() as db:
            version=db.execute('SELECT max(seq) FROM events WHERE bot_id=?',(bot,)).fetchone()[0]
        signature=identity(json.dumps([fills,public.get('positions'),public.get('history_reliable'),public.get('position_as_of'),public.get('position_confidence'),version],sort_keys=True))
        self._synced=getattr(self,'_synced',{})
        if self._synced.get(bot)==signature:return
        trades=journal_from_fills(bot,fills,public)
        with self.store.connect() as db:
            linked=set()
            for t in trades:
                for oid in set(t['order_ids']):
                    for row in db.execute('SELECT payload FROM events WHERE bot_id=? AND order_id=? ORDER BY timestamp,seq',(bot,oid)):
                        e=json.loads(row[0])
                        if e.get('trade_id'):linked.add(e['trade_id'])
                        phase='entry' if oid in {f['order_id'] for f in t['fills'] if f['side']==('sell' if t.get('direction')=='SHORT' else 'buy')} else 'exit'
                        if e.get('reason') and e['event_type'] in ('ENTRY_DECISION','EXIT_DECISION','ORDER_SUBMITTED','EXIT_ORDER_SUBMITTED','ORDER_FILLED','EXIT_FILLED'):
                            t[phase+'_reason']=e['reason']
            # A telemetry-only position is explicitly bot-reported, never a broker fill.
            for r in db.execute("SELECT trade_id, min(timestamp) FROM events WHERE bot_id=? AND trade_id IS NOT NULL AND event_type='POSITION_OPENED' GROUP BY trade_id",(bot,)):
                tid=r[0]
                if tid in linked:continue
                opened=db.execute("SELECT payload FROM events WHERE bot_id=? AND trade_id=? AND event_type='POSITION_OPENED' ORDER BY timestamp,seq LIMIT 1",(bot,tid)).fetchone()
                closed=db.execute("SELECT payload FROM events WHERE bot_id=? AND trade_id=? AND event_type='POSITION_CLOSED' ORDER BY timestamp DESC,seq DESC LIMIT 1",(bot,tid)).fetchone()
                e=json.loads(opened[0]);end=json.loads(closed[0]) if closed else None
                trades.append(dict(trade_id=tid,symbol=e['symbol'],status='REPORTED CLOSED' if end else 'REPORTED OPEN',
                                   entry_time=e['timestamp'],exit_time=end['timestamp'] if end else None,
                                   pnl=None,order_ids=[],fills=[],provenance=e['provenance'],
                                   source='Bot-reported lifecycle; execution/cost basis not independently verified',
                                   entry_reason=e.get('reason'),exit_reason=end.get('reason') if end else None))
        self.store.replace_journal(bot,trades)
        self._synced[bot]=signature

    def inspector(self, bot, trade_id, limit=100, offset=0):
        trade=self.store.trade(bot,trade_id)
        if not trade:return None
        # Only immutable IDs correlate events, never symbol/time proximity.
        with self.store.connect() as db:
            ids=trade.get('order_ids',[])
            linked={trade_id}
            for oid in set(ids):
                linked.update(r[0] for r in db.execute('SELECT DISTINCT trade_id FROM events WHERE bot_id=? AND order_id=? AND trade_id IS NOT NULL',(bot,oid)))
            clauses=['trade_id IN ('+','.join('?' for _ in linked)+')'];args=[bot]+sorted(linked)
            if ids:
                clauses.append('order_id IN ('+','.join('?' for _ in set(ids))+')');args+=sorted(set(ids))
            where='bot_id=? AND ('+' OR '.join(clauses)+')'
            total=db.execute('SELECT count(*) FROM events WHERE '+where,args).fetchone()[0]
            import json
            events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM events WHERE '+where+' ORDER BY timestamp,seq LIMIT ? OFFSET ?',args+[limit,offset])]
        return dict(trade=trade,events=events,total=total,offset=offset,limit=limit,
                    audit=audit(events,trade['status']=='CLOSED'),diagnostics=diagnostics(events),
                    audit_scope='Displayed event page only; snapshot checks are not an independent strategy re-evaluation or execution verification.',
                    explanation='Detailed decision data unavailable for this historical trade.' if not events else 'Only explicitly linked recorded/reconstructed events are shown.')

    def import_legacy(self, bot, root):
        """Existing long-option reason/order rows, not inferred decisions."""
        if bot not in ('options_direct','options_inverted'):return
        import csv
        import io
        import json
        import os
        from models.records import timestamp, number
        from config import SOURCE_TIMEZONE
        path=root/'logs/trade_analytics.csv'
        if not path.exists():return
        mapping={'SKIP':'SIGNAL_REJECTED','ORDER_SUBMIT':'ORDER_SUBMITTED',
                 'ORDER_SUBMITTED':'ORDER_SUBMITTED','ORDER_FILL':'ORDER_FILLED',
                 'ORDER_CANCEL':'ORDER_CANCELLED','ORDER_CANCELLED':'ORDER_CANCELLED',
                 'ORDER_REJECTED':'ORDER_REJECTED'}
        owner='long_call' if bot=='options_direct' else 'long_put'
        with path.open('rb') as f, self.store.connect() as db:
            stat=os.fstat(f.fileno());inode=str((stat.st_dev,stat.st_ino))
            saved=db.execute('SELECT * FROM legacy_cursors WHERE bot_id=?',(bot,)).fetchone()
            offset=saved['offset'] if saved and saved['inode']==inode and saved['offset']<=stat.st_size else 0
            rejected=saved['rejected'] if saved else 0
            if offset:
                header=json.loads(saved['header']);f.seek(offset)
            else:
                raw=f.readline(65537)
                if not raw.endswith(b'\n') or len(raw)>65536:raise ValueError('Invalid legacy CSV header')
                header=next(csv.reader([raw.decode('utf-8-sig')],strict=True))
                if not {'timestamp','event','order_id'}.issubset(header):raise ValueError('Invalid legacy CSV header')
                offset=f.tell()
            start=offset
            for _ in range(500):
                if f.tell()-start>=1048576:break
                # CSV records may contain quoted newlines. Bound each complete record.
                raw=b''
                while True:
                    line=f.readline(65537-len(raw))
                    if not line:break
                    raw+=line
                    if len(raw)>65536:break
                    if not line.endswith(b'\n'):break
                    try:
                        parsed=list(csv.reader(io.StringIO(raw.decode('utf-8')),strict=True))
                        if len(parsed)==1:break
                    except (csv.Error,UnicodeError):
                        continue
                if not raw:break
                if len(raw)>65536:
                    # Fail this optional legacy import visibly, without blocking the journal.
                    raise ValueError('Oversize legacy record')
                if not raw.endswith(b'\n'):break
                try:
                    parsed=list(csv.reader(io.StringIO(raw.decode('utf-8')),strict=True))
                except (csv.Error,UnicodeError):
                    if f.tell()==stat.st_size:break  # writer may still be appending
                    rejected+=1;offset=f.tell();continue
                offset=f.tell()
                if len(parsed)!=1 or len(parsed[0])!=len(header):
                    rejected+=1;continue
                row=dict(zip(header,parsed[0]))
                if (row.get('bot_id') or row.get('bot_strategy'))!=owner:continue
                kind=mapping.get(row['event']);symbol=row.get('option_symbol') or row.get('underlying')
                if not kind or not symbol or row.get('reason')=='legacy_position':continue
                try:
                    e=dict(schema_version=1,event_id='legacy-'+identity(json.dumps(row,sort_keys=True)),
                           bot_id=bot,strategy=row.get('strategy') or owner,symbol=symbol,
                           timestamp=timestamp(row['timestamp'],SOURCE_TIMEZONE),event_type=kind,
                           provenance='RECORDED',source='Legacy trade_analytics.csv; row timestamp is logging time; complete conditions and decision correlation unavailable',
                           reason=row.get('reason') or None,legacy_details=row.get('details') or None,legacy_event=row['event'],
                           order_status=row.get('order_status') or None,order_side=row.get('order_side') or None,
                           market={},option={})
                    if row.get('order_id'):e['order_id']=row['order_id']
                    if row.get('underlying_price'):e['market']['price']=number(row['underlying_price'])
                    if row.get('underlying'):e['market']['symbol']=row['underlying']
                    if row.get('price'):e['option']['price']=number(row['price'])
                    self.store.insert(db,e,bot)
                except (ValueError,TypeError,KeyError):rejected+=1
            db.execute('INSERT OR REPLACE INTO legacy_cursors VALUES (?,?,?,?,?)',(bot,inode,offset,json.dumps(header),rejected))
            return dict(bytes_imported=offset,source_bytes=stat.st_size,rejected=rejected)

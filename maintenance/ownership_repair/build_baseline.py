import csv,json
from decimal import Decimal as D
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
evidence=json.loads((HERE/'broker_evidence.json').read_text())
out={'version':1,'accounts':{}}
for a in evidence:
    snap=a['snapshot']; orders={o['id']:o for o in a['orders']}
    claims={}; legacy={}
    if 'momentum_master' in a['bots']:
        etf=json.loads((ROOT/'ETFEnhancer/logs/position_state_paper.json').read_text())
        print('ETF state keys',list(etf))
        rows=list(csv.DictReader((ROOT/'momentum_master/logs/trades.csv').open()))
        state=json.loads((ROOT/'momentum_master/state/bot_state.json').read_text())
        for p in snap['positions']:
            s=p['symbol']
            if s in etf:
                local=etf[s];oid=local.get('entry_order_id') or local.get('order_id')
                o=orders[oid]
                assert o['client_order_id'].startswith('etfenhancer-') and o['symbol']==s
                assert D(o['filled_qty'])==D(str(p['quantity']))==D(str(local['qty']))
                owner='ETFEnhancer'
            elif s in state['entries']:
                candidates=[r for r in rows if r['symbol']==s and r['side']=='buy' and r['entry_reason']=='momentum_entry' and D(r['qty'])==D(str(p['quantity']))]
                assert len(candidates)==1
                r=candidates[0];o=orders[r['order_id']];oid=o['id']
                assert o['symbol']==s and o['side']=='buy' and D(o['filled_qty'])==D(r['qty'])
                assert D(o['filled_avg_price'])==D(str(p['entry']))==D(str(state['entries'][s]['price']))
                assert not [n for n in a['orders'] if n['symbol']==s and n['filled_at'] and n['filled_at']>o['filled_at'] and D(n['filled_qty'])>0]
                owner='momentum_master';legacy[oid]=owner
            else: raise ValueError('Unattributed holding '+s)
            claims[s]={'owner':owner,'quantity':p['quantity'],'entry':p['entry'],'entry_order_id':oid}
        for s,row in state['protective_stops'].items():
            o=orders.get(row['order_id'])
            if s in claims and claims[s]['owner']=='momentum_master' and o and o['symbol']==s:
                legacy[o['id']]='momentum_master'
        fills=list(csv.DictReader((ROOT/'ccexchange/paper_data/fills.csv').open()))
        residual=sum(D(r['quantity'])*(1 if r['side']=='buy' else -1) for r in fills)
        fee=sum(D(r.get('qty','0')) for r in a['activities'] if r['activity_type']=='CFEE' and r.get('symbol')=='BTCUSD')
        assert residual+fee==0
        crypto={'order_ids':[r['order_id'] for r in fills],'fee_quantity':str(fee),'gross_inventory_remainder':str(residual),'flat_verified':True}
    else:
        crypto=None
        for p in snap['positions']:
            candidates=[o for o in a['orders'] if o['symbol']==p['symbol'] and D(o['filled_qty'])>0]
            assert candidates and all(o['client_order_id'].startswith(('cash_secured_put_','os-')) for o in candidates)
            assert sum(D(o['filled_qty'])*(1 if o['side']=='buy' else -1) for o in candidates)==D(str(p['quantity']))
            claims[p['symbol']]={'owner':'options_secured','quantity':p['quantity'],'entry':p['entry'],'entry_order_id':candidates[0]['id']}
    out['accounts'][snap['identity']]={'bots':a['bots'],'observed_at':snap['observed_at'],'claims':claims,'legacy_orders':legacy,'crypto_reconciliation':crypto}
(HERE/'trading_ownership/baseline.json').write_text(json.dumps(out,indent=2)+'\n')
print('Baseline:',[(a['bots'],a['claims']) for a in out['accounts'].values()])

"""Validate against GET-only broker data, then install isolated ownership guards.

Never starts/stops bots and never submits, cancels or replaces an order.
"""
import hashlib,json,os,shutil,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace as N
HERE=Path(__file__).resolve().parent;PROJECT=HERE.parents[1];ROOT=HERE.parents[2]
sys.path.insert(0,str(PROJECT));sys.path.insert(0,str(HERE))
from services.account_registry import discover
from services.alpaca_reader import AlpacaReader,ALLOWED
from config import BOTS
from trading_ownership.guard import GuardedClient

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def main():
    manifest=json.loads((HERE/'manifest.json').read_text())
    results=json.loads((HERE/'test_results.json').read_text())
    assert len(results)==8 and all(r.get('exit_code')==0 for r in results),'Bot integration tests have not all passed'
    for row in manifest:
        assert digest(ROOT/row['path'])==row['before_sha256'],'Source changed: '+row['path']
        assert digest(HERE/'staged'/row['path'])==row['after_sha256'],'Staged file changed'
    assert not (ROOT/'trading_ownership').exists(),'Existing registry requires a migration; refusing overwrite'
    ALLOWED.add('/v2/orders') # This process only: GET preflight; monitor still prohibits list-orders.
    report={'validated_at':datetime.now(timezone.utc).isoformat(),'bots':{},'broker_mutations':0}
    with tempfile.TemporaryDirectory(prefix='ownership-preflight-') as d:
        registry=Path(d)/'trading_ownership';shutil.copytree(HERE/'trading_ownership',registry,ignore=shutil.ignore_patterns('__pycache__'))
        for account in discover(ROOT,BOTS)[0]:
            reader=AlpacaReader(account);raw_account=reader.get('/v2/account');raw_positions=reader.get('/v2/positions')
            cache={}
            class ReadOnlyBroker:
                def get_account(self):return N(id=raw_account['id'])
                def get_all_positions(self):return [N(**p) for p in raw_positions]
                def get_order_by_id(self,oid):
                    if oid not in cache:cache[oid]=reader.get('/v2/orders/'+oid)
                    return N(**cache[oid])
                def get(self,path,data):
                    k=(path,json.dumps(data,sort_keys=True))
                    if k not in cache:cache[k]=reader.get('/v2'+path,data)
                    return cache[k]
            total=0
            for bot in account['bots']:
                guard=GuardedClient(ReadOnlyBroker(),bot,registry)
                positions=guard.get_all_positions();total+=len(positions)
                report['bots'][bot]={'trader_id':bot,'positions':[{'symbol':p.symbol,'quantity':p.qty} for p in positions]}
            assert total==len(raw_positions),'Unassigned or overlapping broker holdings; deployment refused'
            opened=reader.get('/v2/orders',{'status':'open','limit':500,'nested':'true'})
            assert len(opened)<500,'Incomplete open orders'
            seed=json.loads((registry/'baseline.json').read_text())['accounts'][raw_account['id']]
            def check_order(order):
                owners=[b for b in account['bots'] if GuardedClient(ReadOnlyBroker(),b,registry).owns_order(N(**order))]
                assert len(owners)==1,'Unknown/shared open order '+order['symbol']
                for leg in order.get('legs') or []:check_order(leg)
            for order in opened:check_order(order)
        (HERE/'live_preflight.json').write_text(json.dumps(report,indent=2)+'\n')
        if '--install' not in sys.argv:
            print(json.dumps(report,indent=2));return
        # All validation precedes the first external write.
        for row in manifest:assert digest(ROOT/row['path'])==row['before_sha256'],'Source changed during preflight'
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup=ROOT/'ownership_backups'/stamp;backup.mkdir(parents=True)
        for row in manifest:
            src=ROOT/row['path']
            if src.exists():
                dest=backup/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        shutil.copy2(HERE/'manifest.json',backup/'manifest.json')
        shutil.copytree(registry,ROOT/'trading_ownership')
        (ROOT/'trading_ownership/baseline.json').chmod(0o600)
        (ROOT/'trading_ownership/ownership.sqlite3').chmod(0o600)
        for row in sorted(manifest,key=lambda r:not r['path'].endswith('bot_ownership.py')):
            dest=ROOT/row['path'];stage=HERE/'staged'/row['path']
            temporary=dest.with_name(dest.name+'.ownership-install')
            shutil.copyfile(stage,temporary)
            temporary.chmod(dest.stat().st_mode & 0o777 if dest.exists() else 0o644)
            os.replace(temporary,dest)
        for row in manifest:assert digest(ROOT/row['path'])==row['after_sha256']
        report.update(installed_at=datetime.now(timezone.utc).isoformat(),backup=str(backup),activation='Next normal cron restart. No trading process was restarted.')
        (HERE/'deployment.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
if __name__=='__main__':main()

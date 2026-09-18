"""Restart only this local BotMonitor server; never signal trading processes."""
import json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from services.process_monitor import inspect
from config import BOT_ROOT,BOTS,PORT
before=inspect(BOT_ROOT,BOTS)
pids=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        args=p.joinpath('cmdline').read_bytes().split(b'\0');args=[a.decode() for a in args if a]
        if len(args)!=2 or not Path(args[0]).name.startswith('python'):continue
        if Path(os.readlink(p/'cwd')).resolve()!=ROOT:continue
        script=Path(args[1]);script=script if script.is_absolute() else ROOT/script
        if script.resolve()!=ROOT/'app.py':continue
        if p.stat().st_uid!=os.getuid():continue
        pids.append(int(p.name))
    except (OSError,UnicodeError):continue
if len(pids)>1:raise RuntimeError('Multiple monitor processes; refusing ambiguous restart')
for pid in pids:
    descriptor=os.pidfd_open(pid)
    try:signal.pidfd_send_signal(descriptor,signal.SIGINT)
    finally:os.close(descriptor)
    for _ in range(100):
        if not Path('/proc',str(pid)).exists():break
        time.sleep(.1)
    else:raise RuntimeError('Monitor did not exit; no other process signalled')
log=(ROOT/'data/server.log').open('ab')
child=subprocess.Popen([str(ROOT/'venv/bin/python'),str(ROOT/'app.py')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
log.close()
for _ in range(60):
    if child.poll() is not None:raise RuntimeError('Monitor exited; inspect data/server.log')
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/dashboard',timeout=2) as response:dashboard=json.load(response)
        if dashboard and all(a.get('observed_at') for a in dashboard['accounts']):break
    except (OSError,ValueError,TypeError):pass
    time.sleep(1)
else:raise RuntimeError('Monitor account refresh did not complete')
after=inspect(BOT_ROOT,BOTS)
report={'monitor_pid':child.pid,'dashboard_timestamp':dashboard['timestamp'],'bot_processes_unchanged':before==after,
        'bots':[{k:b[k] for k in ('bot_id','status','pids','open_positions','unrealized_pl','position_confidence')} for b in dashboard['bots']]}
(ROOT/'maintenance/ownership_repair/dashboard_validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))

"""Copy source and test staged integrations with all socket connections denied."""
import json,os,shutil,subprocess,tempfile,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
bots=sys.argv[1:] or [p.name for p in (HERE/'staged').iterdir()]
results=[r for r in json.loads((HERE/'test_results.json').read_text()) if r['bot'] not in bots] if (HERE/'test_results.json').exists() else []
with tempfile.TemporaryDirectory(prefix='ownership-tests-') as d:
    base=Path(d)
    shutil.copytree(HERE/'trading_ownership',base/'trading_ownership',ignore=shutil.ignore_patterns('__pycache__'))
    runner=base/'run_tests.py'
    runner.write_text('''import socket,sys,unittest\nfrom pathlib import Path\ndef deny(*args,**kwargs): raise RuntimeError("Network disabled in ownership validation")\nsocket.socket.connect=deny\nsys.path.insert(0,str(Path.cwd()))\nsys.path.insert(0,str(Path.cwd()/"src"))\nif (Path.cwd()/"tests").is_dir() and Path.cwd().name in ("ccexchange","ETFEnhancerLT"):\n    import pytest\n    sys.exit(pytest.main(["tests","-q","-p","no:cacheprovider"]))\nsuite=unittest.defaultTestLoader.discover("tests" if (Path.cwd()/"tests").is_dir() else ".")\nresult=unittest.TextTestRunner(verbosity=1).run(suite)\nsys.exit(not result.wasSuccessful())\n''')
    for bot in bots:
        source=ROOT/bot;dest=base/bot
        shutil.copytree(source,dest,ignore=shutil.ignore_patterns('venv','.venv','.git','__pycache__','.env','logs','state','paper_data','data','*.parquet','*.pkl','*.db','*.sqlite3','*.sqlite3-wal','*.sqlite3-shm'))
        shutil.copytree(HERE/'staged'/bot,dest,dirs_exist_ok=True)
        python=next((source/v/'bin/python' for v in ('venv','.venv') if (source/v/'bin/python').exists()),None)
        if bot=='ccexchange':
            (dest/'.venv/bin').mkdir(parents=True)
            (dest/'.venv/bin/python').symlink_to(python.resolve())
        result=subprocess.run([str(python),str(runner)],cwd=dest,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1',**{k:'test-credential' for k in ('API_KEY','SECRET_KEY','ALPACA_API_KEY','ALPACA_SECRET_KEY','APCA_API_KEY_ID','APCA_API_SECRET_KEY')}},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
        (HERE/(bot+'_tests.log')).write_text(result.stdout)
        results.append({'bot':bot,'exit_code':result.returncode,'tail':result.stdout[-1700:]})
        print(bot,result.returncode,result.stdout[-400:],flush=True)
(HERE/'test_results.json').write_text(json.dumps(results,indent=2))

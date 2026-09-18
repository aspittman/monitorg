"""Exercise scheduling with harmless temporary Python processes only."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

spec=importlib.util.spec_from_file_location('scheduler',Path(__file__).with_name('market_bot_scheduler.py'))
scheduler=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduler)


class SchedulerTests(unittest.TestCase):
    def test_environment_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(FileNotFoundError):scheduler.python_for(root)
            (root/'.venv/bin').mkdir(parents=True)
            (root/'.venv/bin/python').symlink_to(sys.executable)
            self.assertEqual(scheduler.python_for(root),root/'.venv/bin/python')
            (root/'venv/bin').mkdir(parents=True)
            (root/'venv/bin/python').symlink_to(sys.executable)
            self.assertEqual(scheduler.python_for(root),root/'venv/bin/python')

    def test_exact_process_identity(self):
        root=Path('/tmp/example-bot')
        self.assertTrue(scheduler.matches(dict(args=['python',str(root/'main.py')],cwd=root),root))
        for args in [['python','-c','main.py'],['python','other.py','main.py'],
                     ['python','main.py','--backtest'],['python','/tmp/other/main.py']]:
            self.assertFalse(scheduler.matches(dict(args=args,cwd=root),root))
        # Irrelevant processes must not require permission to read their cwd.
        self.assertFalse(scheduler.matches(dict(args=['firefox','--contentproc'],pid=999999),root))
        self.assertTrue(scheduler.matches(dict(args=['python',str(root/'main.py')],pid=999999),root))

    def test_stale_pid_does_not_target_unrelated_process(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            (base/'pids').mkdir();(base/'cron_logs').mkdir();(base/'fake').mkdir()
            unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
            try:
                (base/'pids/fake.pid').write_text(str(unrelated.pid))
                self.assertTrue(scheduler.stop_bot(base,'fake',timeout=.1))
                self.assertIsNone(unrelated.poll())
            finally:
                unrelated.terminate();unrelated.wait(timeout=5)

    def test_no_duplicate_and_stops_launcher_and_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'fake'
            (root/'.venv/bin').mkdir(parents=True)
            (root/'.venv/bin/python').symlink_to(sys.executable)
            (base/'pids').mkdir();(base/'cron_logs').mkdir()
            (root/'main.py').write_text('import time\nwhile True: time.sleep(1)\n')
            (root/'launcher.py').write_text('import subprocess, sys\nsubprocess.run([sys.executable,"main.py"])\n')
            try:
                self.assertTrue(scheduler.start_bot(base,'fake'))
                before=scheduler.find_processes(root)
                self.assertEqual(len(before),2)
                (base/'pids/fake.pid').unlink()
                self.assertTrue(scheduler.start_bot(base,'fake'))
                self.assertEqual({p['pid'] for p in before},{p['pid'] for p in scheduler.find_processes(root)})
                self.assertTrue(scheduler.stop_bot(base,'fake',timeout=1))
                self.assertEqual(scheduler.find_processes(root),[])
            finally:
                scheduler.stop_bot(base,'fake',timeout=.2)


if __name__=='__main__':unittest.main(verbosity=2)

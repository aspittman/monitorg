"""Optional standalone bot helper. Copy into a bot; never import MonitorG.

Nonblocking enqueue; a daemon writes locally. Queue-full and I/O failures drop
telemetry, never delay execution. Not an execution ledger or delivery guarantee.
"""
import json
import queue
import threading
from datetime import datetime, timezone
from uuid import uuid4


class MonitorEvents:
    def __init__(self, path, bot_id, strategy, capacity=256):
        self.path, self.bot_id, self.strategy = path, bot_id, strategy
        self.dropped=0
        self.queue=queue.Queue(maxsize=capacity)
        self.enabled=False
        try:
            threading.Thread(target=self._write,daemon=True,name='monitor-telemetry').start()
            self.enabled=True
        except Exception:
            self.dropped+=1

    def emit(self, event_type, symbol, **snapshot):
        try:
            if not self.enabled:return False
            event=dict(snapshot,schema_version=1,event_id=snapshot.get('event_id') or str(uuid4()),
                       bot_id=self.bot_id,strategy=self.strategy,event_type=event_type,symbol=symbol,
                       timestamp=snapshot.get('timestamp') or datetime.now(timezone.utc).isoformat(),provenance='RECORDED')
            line=(json.dumps(event,allow_nan=False,separators=(',',':'))+'\n').encode()
            if len(line)>65536:raise ValueError('Snapshot too large')
            self.queue.put_nowait(line)
            return True
        except Exception:
            self.dropped+=1
            return False

    def _write(self):
        import os
        from pathlib import Path
        while True:
            line=self.queue.get()
            try:
                path=Path(self.path)
                path.parent.mkdir(parents=True,exist_ok=True)
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
                try:
                    if os.write(fd,line)!=len(line):raise OSError('Partial telemetry write')
                finally:os.close(fd)
            except Exception:
                self.dropped+=1
            finally:self.queue.task_done()

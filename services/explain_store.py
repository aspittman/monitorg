"""Independent additive store. Bot sources are read only; imports are bounded."""
import json
import sqlite3
from contextlib import contextmanager
from models.decision_event import validate_event, MAX_EVENT_BYTES


class ExplainStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, bot_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    trade_id TEXT, decision_id TEXT, order_id TEXT, symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(bot_id,event_id));
                CREATE INDEX IF NOT EXISTS event_trade ON events(bot_id,trade_id,timestamp);
                CREATE INDEX IF NOT EXISTS event_decision ON events(bot_id,decision_id,timestamp);
                CREATE INDEX IF NOT EXISTS event_order ON events(bot_id,order_id,timestamp);
                CREATE INDEX IF NOT EXISTS event_symbol ON events(bot_id,symbol,timestamp);
                CREATE INDEX IF NOT EXISTS event_type ON events(bot_id,event_type,timestamp);
                CREATE INDEX IF NOT EXISTS event_time ON events(bot_id,timestamp);
                CREATE TABLE IF NOT EXISTS cursors (
                    bot_id TEXT PRIMARY KEY, inode TEXT, offset INTEGER, rejected INTEGER DEFAULT 0, skipping INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS legacy_cursors (
                    bot_id TEXT PRIMARY KEY, inode TEXT, offset INTEGER, header TEXT, rejected INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS journal (
                    bot_id TEXT, trade_id TEXT, symbol TEXT, timestamp TEXT, status TEXT,
                    pnl REAL, payload TEXT, PRIMARY KEY(bot_id,trade_id));
                CREATE INDEX IF NOT EXISTS journal_time ON journal(bot_id,timestamp);
                CREATE INDEX IF NOT EXISTS journal_symbol ON journal(bot_id,symbol,timestamp);
            ''')
            if 'skipping' not in {r[1] for r in db.execute('PRAGMA table_info(cursors)')}:
                db.execute('ALTER TABLE cursors ADD COLUMN skipping INTEGER DEFAULT 0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def insert(self, db, value, bot):
        e = validate_event(value, bot)
        payload = json.dumps(e, sort_keys=True, allow_nan=False)
        old = db.execute('SELECT payload FROM events WHERE bot_id=? AND event_id=?', (bot,e['event_id'])).fetchone()
        if old:
            if old['payload'] != payload:
                raise ValueError('Conflicting duplicate event ID')
            return False
        db.execute('''INSERT INTO events(bot_id,event_id,trade_id,decision_id,order_id,symbol,timestamp,event_type,payload)
                      VALUES (?,?,?,?,?,?,?,?,?)''',
                   (bot,e['event_id'],e.get('trade_id'),e.get('decision_id'),e.get('order_id'),e['symbol'],e['timestamp'],e['event_type'],payload))
        return True

    def ingest(self, bot, path):
        """At most 1 MiB / 500 lines per bot per refresh; partial lines retried."""
        if not path.exists():
            return
        with path.open('rb') as f, self.connect() as db:
            import os
            stat = os.fstat(f.fileno())
            identity = str((stat.st_dev, stat.st_ino))
            row = db.execute('SELECT * FROM cursors WHERE bot_id=?', (bot,)).fetchone()
            offset = row['offset'] if row and row['inode']==identity and row['offset']<=stat.st_size else 0
            rejected = row['rejected'] if row else 0
            skipping = bool(row['skipping']) if row and row['inode']==identity and row['offset']<=stat.st_size else False
            f.seek(offset)
            start = offset
            for _ in range(500):
                if f.tell()-start >= 1048576:
                    break
                line = f.readline(MAX_EVENT_BYTES+2)
                if not line:
                    break
                if skipping:
                    offset=f.tell()
                    skipping=not line.endswith(b'\n')
                    continue
                if not line.endswith(b'\n'):
                    if len(line)>MAX_EVENT_BYTES:
                        rejected += 1
                        offset=f.tell()
                        skipping=True
                        continue
                    break
                offset=f.tell()
                try:
                    self.insert(db, json.loads(line), bot)
                except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
                    rejected += 1
            db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?,?,?)', (bot,identity,offset,rejected,int(skipping)))

    def events(self, bot, trade_id=None, limit=100, offset=0):
        where, args = 'bot_id=?', [bot]
        if trade_id is not None:
            where += ' AND trade_id=?'; args.append(trade_id)
        with self.connect() as db:
            total = db.execute('SELECT count(*) FROM events WHERE '+where,args).fetchone()[0]
            rows = db.execute('SELECT payload FROM events WHERE '+where+' ORDER BY timestamp '+('ASC' if trade_id else 'DESC')+', seq LIMIT ? OFFSET ?',args+[limit,offset])
            return dict(items=[json.loads(r[0]) for r in rows], total=total, limit=limit, offset=offset)

    def replace_journal(self, bot, trades):
        with self.connect() as db:
            db.execute('DELETE FROM journal WHERE bot_id=?',(bot,))
            db.executemany('INSERT INTO journal VALUES (?,?,?,?,?,?,?)',[(bot,t['trade_id'],t['symbol'],t.get('entry_time') or '',t['status'],t.get('pnl'),json.dumps(t,allow_nan=False)) for t in trades])

    def journal(self, bot, params):
        where, args = ['bot_id=?'], [bot]
        for key, column in (('symbol','symbol'),('status','status')):
            if params.get(key):
                where.append(column+'=?');args.append(params[key])
        for key, op in (('from','>='),('to','<=')):
            if params.get(key):
                where.append('substr(timestamp,1,10)'+op+'?');args.append(params[key])
        if params.get('outcome') in ('winners','losers'):
            where.append('pnl'+('>0' if params['outcome']=='winners' else '<0'))
        limit, offset = params.get('limit',50), params.get('offset',0)
        with self.connect() as db:
            clause=' AND '.join(where)
            total=db.execute('SELECT count(*) FROM journal WHERE '+clause,args).fetchone()[0]
            rows=db.execute('SELECT payload FROM journal WHERE '+clause+' ORDER BY timestamp '+('ASC' if params.get('sort')=='oldest' else 'DESC')+',trade_id LIMIT ? OFFSET ?',args+[limit,offset])
            rejected=db.execute('SELECT rejected FROM cursors WHERE bot_id=?',(bot,)).fetchone()
            return dict(items=[json.loads(r[0]) for r in rows],total=total,limit=limit,offset=offset,rejected_events=rejected[0] if rejected else 0)

    def trade(self, bot, trade_id):
        with self.connect() as db:
            row=db.execute('SELECT payload FROM journal WHERE bot_id=? AND trade_id=?',(bot,trade_id)).fetchone()
            return json.loads(row[0]) if row else None

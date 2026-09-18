"""Read stable source files; copy SQLite + WAL before opening any database.

No bot module is imported and no SQLite connection touches a bot's database.
"""
import csv
import io
import json
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path


def signature(path):
    try:
        s = Path(path).stat()
        return (s.st_ino, s.st_size, s.st_mtime_ns)
    except FileNotFoundError:
        return None


def stable_text(path):
    path = Path(path)
    for _ in range(3):
        before = signature(path)
        text = path.read_text(encoding='utf-8-sig')
        if before == signature(path):
            return text
    raise ValueError('Source changed during read; retry next refresh')


def read_csv(path, required=()):
    text = stable_text(path)
    if text and not text.endswith('\n'):
        raise ValueError('CSV final record is incomplete')
    reader = csv.DictReader(io.StringIO(text))
    if not set(required).issubset(reader.fieldnames or []):
        raise ValueError('CSV header missing required fields')
    rows = []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError('CSV row does not match header')
        rows.append(row)
    return rows


def read_json(path):
    return json.loads(stable_text(path))


@contextmanager
def sqlite_copy(path):
    path = Path(path)
    wal = Path(str(path) + '-wal')
    with tempfile.TemporaryDirectory(prefix='botmonitor-') as directory:
        dest = Path(directory) / 'source.sqlite3'
        for _ in range(3):
            before = (signature(path), signature(wal))
            if before[0] is None:
                raise FileNotFoundError(path.name)
            shutil.copyfile(path, dest)
            local_wal = Path(str(dest) + '-wal')
            local_wal.unlink(missing_ok=True)
            try:
                if before[1] is not None:
                    shutil.copyfile(wal, local_wal)
            except FileNotFoundError:
                continue
            if before == (signature(path), signature(wal)):
                break
        else:
            raise ValueError('SQLite source changed during copy; retry next refresh')
        connection = sqlite3.connect(dest)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        try:
            yield connection
        finally:
            connection.close()


def table(connection, name):
    allowed = {'fills', 'orders', 'lots', 'pnl', 'settlements', 'metadata',
               'stock_allocations', 'stock_fills', 'stock_orders', 'stock_dispositions'}
    if name not in allowed:
        raise ValueError('Table is not allowlisted')
    return [dict(row) for row in connection.execute(f'SELECT rowid AS _rowid, * FROM {name}')]


def has_table(connection, name):
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

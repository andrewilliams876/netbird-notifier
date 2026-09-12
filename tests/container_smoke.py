"""Executed explicitly inside a hardened container twice with one test volume."""
from contextlib import closing
import os
from pathlib import Path
from unittest.mock import Mock

from notifier import app

assert os.getuid() == 10001
status = Path('/proc/self/status').read_text()
assert 'CapEff:\t0000000000000000' in status
assert 'NoNewPrivs:\t1' in status
try:
    Path('/app/should-not-write').write_text('test')
except OSError:
    pass
else:
    raise AssertionError('root filesystem writable')
os.umask(0o077)
config = app.Config.load()
with closing(app.open_state(config)) as db:
    before = db.execute('SELECT count(*) FROM sent').fetchone()[0]
    send = Mock()
    count = app.poll(config, db, lambda _: [{'id': 'smoke-user'}], send)
    assert count == (0 if before else 1)
    assert send.call_count == count
    assert db.execute('SELECT count(*) FROM sent').fetchone()[0] == 1
assert app.healthy(config)
print('PASS non-root, no capabilities, no-new-privileges, read-only root, persistent state; accepted=', count)

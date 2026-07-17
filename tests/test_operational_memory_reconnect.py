"""
Regression for a real production symptom: every learning-loop write failed
with "learning update failed: connection already closed" for the rest of a
long chat session, after the first occurrence. Root cause: OperationalMemory
caches ONE _Backend (and therefore one psycopg2 connection) for the entire
process's life (see get_operational_memory()'s module-level singleton), but
a pooled Postgres connection (Supabase's pgbouncer, etc.) can be closed
server-side between calls once its idle timeout passes — trivially exceeded
by real think-time between chat messages. Once that happened, EVERY later
write raised the same error forever, silently disabling recurring-failure
detection/learning for the rest of the session.

_Backend.execute()/query() now detect a connection-closed error and
transparently reconnect once before retrying, instead of raising forever.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.intelligence.operational_memory import _Backend


class _FakeCursor:
    def __init__(self, conn, should_fail):
        self._conn = conn
        self._should_fail = should_fail
        self.description = None

    def execute(self, sql, params=()):
        if self._should_fail():
            raise _FakeOperationalError("connection already closed")
        self._conn.executed.append((sql, params))

    def fetchall(self):
        return []


class _FakeOperationalError(Exception):
    pass


class _FakeInterfaceError(Exception):
    pass


class _FakeConnection:
    """Simulates a psycopg2 connection that has gone stale server-side:
    the FIRST cursor().execute() after `poison()` raises a connection-closed
    error; a freshly reconnected connection (a new _FakeConnection) works."""
    def __init__(self, dsn):
        self.dsn = dsn
        self.autocommit = False
        self.executed = []
        self._poisoned = False
        self._closed = False

    def poison(self):
        self._poisoned = True

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self, lambda: self._poisoned)

    def close(self):
        self._closed = True


def _fake_psycopg2_module():
    mod = types.ModuleType("psycopg2")
    mod.OperationalError = _FakeOperationalError
    mod.InterfaceError = _FakeInterfaceError
    mod.extras = types.SimpleNamespace(RealDictCursor=object())
    mod.connect = lambda dsn: _FakeConnection(dsn)
    return mod


def _backend_with_fake_pg(monkeypatch):
    fake_pg = _fake_psycopg2_module()
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_pg.extras)
    be = _Backend(dsn="postgresql://fake/db")
    assert be.is_postgres
    return be


def test_execute_transparently_reconnects_after_a_stale_connection(monkeypatch):
    be = _backend_with_fake_pg(monkeypatch)
    original_conn = be._conn

    original_conn.poison()
    # Must NOT raise — should reconnect once and succeed on the new connection.
    be.execute("INSERT INTO memory_events (id) VALUES (?)", ("ev1",))

    assert be._conn is not original_conn          # reconnected to a fresh connection
    assert original_conn._closed is True            # old one was cleaned up
    assert ("INSERT INTO memory_events (id) VALUES (%s)", ("ev1",)) in be._conn.executed


def test_query_transparently_reconnects_after_a_stale_connection(monkeypatch):
    be = _backend_with_fake_pg(monkeypatch)
    be._conn.poison()

    result = be.query("SELECT * FROM memory_events WHERE device = ?", ("10.0.0.1",))

    assert result == []   # fake cursor always returns no rows; the point is it didn't raise
    assert be._conn._closed is False   # this IS the reconnected (unpoisoned) connection


def test_non_connection_errors_are_not_swallowed(monkeypatch):
    """A genuine SQL/programming error must still raise — only connection-
    closed errors trigger a reconnect-and-retry."""
    be = _backend_with_fake_pg(monkeypatch)

    def _boom(sql, params=()):
        raise ValueError("syntax error at or near")

    be._conn.cursor = lambda cursor_factory=None: types.SimpleNamespace(execute=_boom)
    try:
        be.execute("BAD SQL", ())
        assert False, "expected the non-connection error to propagate"
    except ValueError:
        pass

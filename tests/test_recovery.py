import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from specprobe.storage.audit import AuditLog
from specprobe.storage.db import create_database, session_factory
from specprobe.storage.models import AuditLogRow
from specprobe.storage.repository import create_workspace


def test_concurrent_audit_writers_preserve_chain(tmp_path: Path):
    engine = create_database("sqlite:///" + str(tmp_path / "concurrent.db"))
    factory = session_factory(engine)
    with factory() as session:
        create_workspace(session, "one", "secret-key")

    def append(index):
        with factory() as session:
            AuditLog(session).append("one", "concurrent", "engineer", {"index": index})
            session.commit()

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(append, range(30)))
    with factory() as session:
        assert len(list(session.scalars(select(AuditLogRow)))) == 30
        assert AuditLog(session).verify_chain()


def test_audit_contention_rolls_back_and_retry_preserves_chain(tmp_path):
    import pytest

    path = tmp_path / "locked.db"
    engine = create_database("sqlite:///" + str(path))
    factory = session_factory(engine)
    with factory() as session:
        create_workspace(session, "one", "secret-key")
    lock = sqlite3.connect(path)
    lock.execute("BEGIN IMMEDIATE")
    try:
        with factory() as session:
            session.connection().exec_driver_sql("PRAGMA busy_timeout=1")
            with pytest.raises(OperationalError):
                AuditLog(session).append("one", "blocked", "engineer", {})
            session.rollback()
    finally:
        lock.rollback()
        lock.close()
    with factory() as session:
        AuditLog(session).append("one", "retried", "engineer", {})
        session.commit()
        assert AuditLog(session).verify_chain()

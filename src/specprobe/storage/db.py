from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
  SELECT RAISE(ABORT, 'audit_log is append-only');
END
"""
_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
  SELECT RAISE(ABORT, 'audit_log is append-only');
END
"""


def create_database(url: str = "sqlite:///:memory:") -> Engine:
    options: dict[str, object] = {}
    if url == "sqlite:///:memory:":
        options = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    else:
        options = {"connect_args": {"check_same_thread": False, "timeout": 30}}
    engine = create_engine(url, **options)
    if engine.dialect.name != "sqlite":
        raise ValueError("This migration and audit implementation supports SQLite only")

    @event.listens_for(engine, "connect")
    def configure(connection: object, record: object) -> None:
        from typing import Any, cast

        cursor = cast(Any, connection).cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    with engine.connect() as connection:
        version = connection.exec_driver_sql("PRAGMA user_version").scalar()
        if version is not None and version > 3:
            raise ValueError("Database schema is newer than this application")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(_UPDATE_TRIGGER)
        connection.exec_driver_sql(_DELETE_TRIGGER)
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS audit_mutex "
            "(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)"
        )
        connection.exec_driver_sql("INSERT OR IGNORE INTO audit_mutex VALUES (1, 0)")
        connection.exec_driver_sql("PRAGMA user_version=3")
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)

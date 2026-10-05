from sqlalchemy import Engine, create_engine
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
    engine = create_engine(url, **options)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(_UPDATE_TRIGGER)
        connection.exec_driver_sql(_DELETE_TRIGGER)
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)

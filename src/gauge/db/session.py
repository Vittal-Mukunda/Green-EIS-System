"""Engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from gauge.db import models  # noqa: F401  (registers tables on Base.metadata)
from gauge.db.base import Base


def make_engine(url: str) -> Engine:
    """Create an engine; SQLite gets foreign-key enforcement (off by default in SQLite)."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_db(engine: Engine) -> list[str]:
    """Create all tables that do not exist yet; return the table names in dependency order."""
    Base.metadata.create_all(engine)
    return [t.name for t in Base.metadata.sorted_tables]


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back on error."""
    session = sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.config import DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite:")

engine_kwargs = {"echo": False, "future": True}
if IS_SQLITE:
    # SQLite demo mode is intended for a single web worker. WAL and busy timeout
    # reduce lock failures, but they are not a multi-worker production database.
    engine_kwargs["connect_args"] = {"timeout": 10}

engine = create_engine(DATABASE_URL, **engine_kwargs)


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Provide a transactional scope."""
    session: Session = SessionLocal()
    try:
        with session.begin():
            yield session
    finally:
        session.close()

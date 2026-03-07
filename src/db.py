from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False, future=True)
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

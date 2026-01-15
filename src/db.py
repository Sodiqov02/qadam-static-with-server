from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings

# Default to SQLite for quick local runs if DATABASE_URL is not provided.
DATABASE_URL = settings.DATABASE_URL if hasattr(settings, "DATABASE_URL") else ""
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./qadam_demo.db"

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Provide a transactional scope."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

import json
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import settings


def _alembic_config() -> Config:
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def _current_revision(database_url: str) -> str | None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()


def main() -> None:
    config = _alembic_config()
    head_revision = ScriptDirectory.from_config(config).get_current_head()
    before = _current_revision(settings.DATABASE_URL)

    if before != head_revision:
        command.upgrade(config, "head")

    after = _current_revision(settings.DATABASE_URL)
    print(
        json.dumps(
            {
                "status": "ok",
                "before_revision": before,
                "head_revision": head_revision,
                "after_revision": after,
                "upgraded": before != head_revision,
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()

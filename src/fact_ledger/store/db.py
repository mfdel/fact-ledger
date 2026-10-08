"""Engine and declarative base. SQLite first; a Postgres URL works unchanged."""

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all tables. Alembic reads ``Base.metadata``."""


def make_engine(database_url: str) -> Engine:
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def ping(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(connection.execute(text("SELECT 1")).scalar_one() == 1)


def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

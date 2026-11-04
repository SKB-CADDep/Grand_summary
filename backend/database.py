from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.paths import db_path


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    override = os.environ.get("GRAND_SUMMARY_DB")
    if not override:
        return f"sqlite:///{db_path()}"
    if "://" in override:
        return override
    return f"sqlite:///{override}"


def make_engine(url: str | None = None):
    resolved = url or _database_url()
    kwargs: dict = {"future": True}
    if resolved.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(resolved, **kwargs)

    if resolved.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def reset_engine(url: str | None = None) -> None:
    """Для тестов: пересоздать engine на другой файл БД."""
    global engine, SessionLocal
    engine.dispose()
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate_sqlite() -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    statements = [
        "ALTER TABLE workbooks ADD COLUMN extra_parameters_json TEXT DEFAULT '[]'",
        "ALTER TABLE workbooks ADD COLUMN parameter_overrides_json TEXT DEFAULT '{}'",
        "ALTER TABLE workbooks ADD COLUMN deleted_parameters_json TEXT DEFAULT '[]'",
        "ALTER TABLE cells ADD COLUMN locked BOOLEAN DEFAULT 0",
        "ALTER TABLE cells ADD COLUMN updated_at DATETIME",
        "ALTER TABLE cells ADD COLUMN updated_by VARCHAR(128)",
    ]
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception:
                pass


def init_db() -> None:
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()

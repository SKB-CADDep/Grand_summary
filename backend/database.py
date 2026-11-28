from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.paths import db_path


class Base(DeclarativeBase):
    pass


def _database_url() -> str | URL:
    override = os.environ.get("GRAND_SUMMARY_DB")
    if not override:
        return URL.create("sqlite", database=str(db_path()))
    if "://" in override:
        return override
    return URL.create("sqlite", database=override)


def make_engine(url: str | URL | None = None):
    resolved = url or _database_url()
    is_sqlite = (resolved.drivername if isinstance(resolved, URL) else resolved).startswith("sqlite")
    kwargs: dict = {"future": True}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(resolved, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            journal_mode = (
                "DELETE"
                if os.environ.get("GRAND_SUMMARY_SQLITE_JOURNAL_MODE", "").upper() == "DELETE"
                else "WAL"
            )
            cursor.execute(f"PRAGMA journal_mode={journal_mode}")
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


def _export_sqlite_json() -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    try:
        from src.services.db_json import export_database_json

        export_database_json()
    except Exception:
        return


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        changed = bool(session.new or session.dirty or session.deleted)
        session.commit()
        if changed:
            _export_sqlite_json()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate_sqlite() -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    statements = [
        "ALTER TABLE workbooks ADD COLUMN column_overrides_json TEXT DEFAULT '{}'",
        "ALTER TABLE workbooks ADD COLUMN deleted_columns_json TEXT DEFAULT '[]'",
        "ALTER TABLE workbooks ADD COLUMN extra_parameters_json TEXT DEFAULT '[]'",
        "ALTER TABLE workbooks ADD COLUMN parameter_overrides_json TEXT DEFAULT '{}'",
        "ALTER TABLE workbooks ADD COLUMN deleted_parameters_json TEXT DEFAULT '[]'",
        "ALTER TABLE workbooks ADD COLUMN parent_workbook_id VARCHAR(36)",
        "ALTER TABLE workbooks ADD COLUMN sheet_name VARCHAR(255) DEFAULT 'Исходные данные'",
        "ALTER TABLE workbooks ADD COLUMN sheet_order INTEGER DEFAULT 0",
        "ALTER TABLE workbooks ADD COLUMN is_primary BOOLEAN DEFAULT 0",
        "ALTER TABLE workbooks ADD COLUMN is_issued BOOLEAN DEFAULT 0",
        "ALTER TABLE workbooks ADD COLUMN issued_kind VARCHAR(32) DEFAULT ''",
        "ALTER TABLE workbooks ADD COLUMN is_base BOOLEAN DEFAULT 0",
        "ALTER TABLE workbooks ADD COLUMN show_change_highlight BOOLEAN DEFAULT 1",
        "ALTER TABLE workbooks ADD COLUMN issued_snapshot_json TEXT DEFAULT '[]'",
        "ALTER TABLE workbooks ADD COLUMN report_notes_json TEXT DEFAULT '[]'",
        "ALTER TABLE cells ADD COLUMN locked BOOLEAN DEFAULT 0",
        "ALTER TABLE cells ADD COLUMN unified BOOLEAN DEFAULT 0",
        "ALTER TABLE cells ADD COLUMN excel_highlight BOOLEAN DEFAULT 0",
        "ALTER TABLE cells ADD COLUMN updated_at DATETIME",
        "ALTER TABLE cells ADD COLUMN updated_by VARCHAR(128)",
        "ALTER TABLE cell_changes ADD COLUMN user_journal BOOLEAN NOT NULL DEFAULT 1",
    ]
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception:
                pass
        conn.execute(text(
            "UPDATE workbooks AS current SET is_primary = 1 "
            "WHERE current.id = ("
            "SELECT candidate.id FROM workbooks AS candidate "
            "WHERE COALESCE(candidate.parent_workbook_id, candidate.id) = "
            "COALESCE(current.parent_workbook_id, current.id) "
            "ORDER BY candidate.sheet_order, candidate.created_at, candidate.id LIMIT 1) "
            "AND NOT EXISTS (SELECT 1 FROM workbooks AS candidate "
            "WHERE COALESCE(candidate.parent_workbook_id, candidate.id) = "
            "COALESCE(current.parent_workbook_id, current.id) AND candidate.is_primary = 1)"
        ))
        conn.execute(text(
            "UPDATE workbooks SET sheet_name = 'Исходные данные' "
            "WHERE parent_workbook_id IS NULL AND sheet_name = 'Основной лист'"
        ))


def init_db() -> None:
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
    _export_sqlite_json()

"""JSON-копия рабочей SQLite-базы рядом с файлом .db."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

JSON_FILE_NAME = "grand_summary.json"


def json_database_path(database: Path | None = None) -> Path | None:
    source = database
    if source is None:
        from src.services.db_backup import sqlite_database_path

        source = sqlite_database_path()
    if source is None:
        return None
    return source.with_suffix(".json")


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def dump_sqlite_tables(database: Path) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables: dict[str, list[dict]] = {}
        for name in names:
            tables[name] = [
                {key: _json_value(item) for key, item in dict(row).items()}
                for row in connection.execute(f'SELECT * FROM "{name}"')
            ]
        return {"database": database.name, "tables": tables}
    finally:
        connection.close()


def export_database_json(database: Path | None = None) -> Path | None:
    source = database
    if source is None:
        from src.services.db_backup import sqlite_database_path

        source = sqlite_database_path()
    target = json_database_path(source)
    if source is None or target is None or not source.is_file():
        return None
    payload = dump_sqlite_tables(source)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target

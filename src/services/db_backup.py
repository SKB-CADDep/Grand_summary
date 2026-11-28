"""Снимки базы SQLite: текущие, дневные, недельные и месячные.

Раскладка как в трекере задач: папка «бекап» рядом с файлом базы, контрольная
сумма в manifest.json, запись через временный каталог.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from src.paths import db_path
from src.services.db_json import JSON_FILE_NAME, export_database_json, json_database_path

BACKUP_DIR_NAME = "бекап"
DAILY_DIR_NAME = "дневные"
WEEKLY_DIR_NAME = "недельные"
MONTHLY_DIR_NAME = "месячные"
CURRENT_KEEP = 5
DAILY_KEEP = 5
WEEKLY_KEEP = 3
MONTHLY_KEEP = 2
DATA_FILE_NAME = "grand_summary.db"
_STAMP_RE = re.compile(r"^(\d{4}\.\d{2}\.\d{2})(?:_(\d{2}-\d{2}-\d{2}))?(?:-(\d+))?$")
_RESERVED_DIRS = {DAILY_DIR_NAME, WEEKLY_DIR_NAME, MONTHLY_DIR_NAME}
_DIR_REPLACE_ATTEMPTS = 8


class BackupError(RuntimeError):
    """Снимок не удалось записать или проверить."""


def sqlite_database_path() -> Path | None:
    override = str(os.environ.get("GRAND_SUMMARY_DB") or "").strip()
    if not override:
        return db_path()
    if "://" not in override:
        return Path(override).expanduser()
    if not override.startswith("sqlite:"):
        return None
    from sqlalchemy.engine import make_url

    database = make_url(override).database
    if not database or database == ":memory:":
        return None
    return Path(database)


def backup_dir(database: Path | None = None) -> Path:
    source = database or sqlite_database_path()
    if source is None:
        raise BackupError("Рабочая база не SQLite, снимок не создаётся.")
    return source.parent / BACKUP_DIR_NAME


def daily_backup_dir(database: Path | None = None) -> Path:
    return backup_dir(database) / DAILY_DIR_NAME


def weekly_backup_dir(database: Path | None = None) -> Path:
    return backup_dir(database) / WEEKLY_DIR_NAME


def monthly_backup_dir(database: Path | None = None) -> Path:
    return backup_dir(database) / MONTHLY_DIR_NAME


def backup_stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y.%m.%d_%H-%M-%S")


def date_stamp(value: date | datetime) -> str:
    moment = value.date() if isinstance(value, datetime) else value
    return moment.strftime("%Y.%m.%d")


def add_calendar_month(value: date) -> date:
    if value.month == 12:
        year, month = value.year + 1, 1
    else:
        year, month = value.year, value.month + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_snapshot_stamp(name: str) -> datetime | None:
    match = _STAMP_RE.fullmatch(str(name or "").strip())
    if match is None:
        return None
    day = match.group(1)
    clock = match.group(2) or "00-00-00"
    try:
        return datetime.strptime(f"{day}_{clock}", "%Y.%m.%d_%H-%M-%S")
    except ValueError:
        return None


def list_snapshot_dirs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    rows: list[Path] = []
    for item in folder.iterdir():
        if not item.is_dir():
            continue
        if item.name in _RESERVED_DIRS or item.name.startswith(".") or item.name.endswith(".tmp"):
            continue
        if parse_snapshot_stamp(item.name) is None:
            continue
        rows.append(item)
    return sorted(rows, key=lambda item: item.name, reverse=True)


def last_snapshot_date(folder: Path) -> date | None:
    rows = list_snapshot_dirs(folder)
    if not rows:
        return None
    parsed = parse_snapshot_stamp(rows[0].name)
    return parsed.date() if parsed else None


def prune_snapshots(folder: Path, keep: int) -> None:
    leftovers = list_snapshot_dirs(folder)[max(0, int(keep)) :]
    for old in leftovers:
        shutil.rmtree(old, ignore_errors=True)


def _commit_snapshot_dir(tmp: Path, folder: Path) -> None:
    last: OSError | None = None
    for attempt in range(_DIR_REPLACE_ATTEMPTS):
        try:
            if folder.exists():
                shutil.rmtree(folder)
            os.rename(tmp, folder)
            return
        except OSError as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    try:
        if folder.exists():
            shutil.rmtree(folder)
        shutil.copytree(tmp, folder)
        shutil.rmtree(tmp, ignore_errors=True)
    except OSError:
        if last is not None:
            raise last
        raise


def _copy_database(source: Path, destination: Path) -> None:
    source_conn = sqlite3.connect(source)
    dest_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()


def verify_snapshot(folder: Path) -> dict:
    manifest_path = Path(folder) / "manifest.json"
    if not manifest_path.is_file():
        raise BackupError(f"Нет manifest.json в снимке {folder.name}.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"Повреждён manifest.json в снимке {folder.name}.") from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict):
        raise BackupError(f"В снимке {folder.name} нет списка файлов.")
    for name, meta in files.items():
        path = Path(folder) / str(name)
        if not path.is_file():
            raise BackupError(f"В снимке {folder.name} нет файла {name}.")
        expected = str(meta.get("sha256") or "") if isinstance(meta, dict) else ""
        if expected and file_sha256(path) != expected:
            raise BackupError(f"Контрольная сумма {name} в снимке {folder.name} не совпала.")
    return manifest


def write_data_snapshot(
    database: Path,
    dest_parent: Path,
    *,
    stamp: str,
    kind: str,
    now: datetime | None = None,
) -> Path:
    if not database.is_file():
        raise BackupError(f"Нет файла базы {database}.")
    dest_parent.mkdir(parents=True, exist_ok=True)
    folder = dest_parent / stamp
    suffix = 1
    while folder.exists() or Path(str(folder) + ".tmp").exists():
        folder = dest_parent / f"{stamp}-{suffix}"
        suffix += 1
    tmp = Path(str(folder) + ".tmp")
    try:
        tmp.mkdir(parents=True)
        try:
            export_database_json(database)
        except Exception:
            pass
        target = tmp / DATA_FILE_NAME
        _copy_database(database, target)
        files = {DATA_FILE_NAME: {"sha256": file_sha256(target), "size": target.stat().st_size}}
        json_source = json_database_path(database)
        if json_source is not None and json_source.is_file():
            json_target = tmp / JSON_FILE_NAME
            shutil.copy2(json_source, json_target)
            files[JSON_FILE_NAME] = {"sha256": file_sha256(json_target), "size": json_target.stat().st_size}
        payload = {
            "kind": kind,
            "created_at": (now or datetime.now()).isoformat(timespec="seconds"),
            "files": files,
        }
        (tmp / "manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _commit_snapshot_dir(tmp, folder)
        return folder
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def write_current_snapshot(now: datetime | None = None) -> Path | None:
    database = sqlite_database_path()
    if database is None or not database.is_file():
        return None
    moment = now or datetime.now()
    folder = write_data_snapshot(
        database,
        backup_dir(database),
        stamp=backup_stamp(moment),
        kind="current",
        now=moment,
    )
    prune_snapshots(backup_dir(database), CURRENT_KEEP)
    return folder


def rotate_tiered_backups(now: datetime | None = None) -> list[Path]:
    """Дневной — первый запуск за дату; недельный — через 7 суток; месячный — та же дата следующего месяца."""
    database = sqlite_database_path()
    if database is None or not database.is_file():
        return []
    moment = now or datetime.now()
    today = moment.date()
    created: list[Path] = []

    daily_root = daily_backup_dir(database)
    if last_snapshot_date(daily_root) != today:
        created.append(
            write_data_snapshot(database, daily_root, stamp=date_stamp(today), kind="daily", now=moment)
        )
        prune_snapshots(daily_root, DAILY_KEEP)

    weekly_root = weekly_backup_dir(database)
    last_weekly = last_snapshot_date(weekly_root)
    if last_weekly is None or today >= last_weekly + timedelta(days=7):
        created.append(
            write_data_snapshot(database, weekly_root, stamp=date_stamp(today), kind="weekly", now=moment)
        )
        prune_snapshots(weekly_root, WEEKLY_KEEP)

    monthly_root = monthly_backup_dir(database)
    last_monthly = last_snapshot_date(monthly_root)
    if last_monthly is None or today >= add_calendar_month(last_monthly):
        created.append(
            write_data_snapshot(database, monthly_root, stamp=date_stamp(today), kind="monthly", now=moment)
        )
        prune_snapshots(monthly_root, MONTHLY_KEEP)
    return created

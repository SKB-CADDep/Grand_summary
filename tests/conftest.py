from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bootstrap import ensure_python_packages

ensure_python_packages()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "grand_summary.db"
    catalog_file = tmp_path / "objects.json"
    catalog_file.write_text(
        '[{"ID_projects": "101", "factory_number": "T-101", '
        '"turbine_name": "К-200", "station_name": "ТЭЦ-1", '
        '"station_number": "3", "series_turbines": "К-200", "kind": "steam", '
        '"hidden": false, "object_version": 1, "updated_by": "test", '
        '"updated_at": "2026-01-01T00:00:00+00:00"}]',
        encoding="utf-8",
    )
    materials_dir = tmp_path / "materials"
    materials_data_dir = materials_dir / "data"
    materials_data_dir.mkdir(parents=True)
    for name in ("12Х18Н10Т", "15Х11МФ", "20Х13", "source"):
        (materials_data_dir / f"{name}.json").touch()
    monkeypatch.setenv("GRAND_SUMMARY_DB", str(db_file))
    monkeypatch.setenv("GRAND_SUMMARY_OBJECTS_FILE", str(catalog_file))
    monkeypatch.setenv("GRAND_SUMMARY_MATERIALS_DIR", str(materials_dir))

    from backend.database import init_db, reset_engine

    reset_engine()
    init_db()

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client

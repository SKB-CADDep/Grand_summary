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
    monkeypatch.setenv("GRAND_SUMMARY_DB", str(db_file))

    from backend.database import init_db, reset_engine

    reset_engine()
    init_db()

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client

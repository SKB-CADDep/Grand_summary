"""Общие фикстуры pytest для Material Library."""
import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

from backend.main import app
from backend.dependencies import get_app_state

# Корень репозитория — родитель каталога tests/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = str("C:/Users/Лиза/Desktop/jbsidian/data")

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def reset_workspace():
    state = get_app_state()
    state.repository = None
    state.storage = None
    yield
    state.repository = None
    state.storage = None
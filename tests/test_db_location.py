from pathlib import Path


def test_frozen_data_dir_uses_the_shared_release_folder(monkeypatch, tmp_path: Path):
    share = tmp_path / "share"
    share.mkdir()
    exe = tmp_path / "GrandSummary.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(exe))
    monkeypatch.delenv("GRAND_SUMMARY_DATA_DIR", raising=False)
    monkeypatch.setenv("GRAND_SUMMARY_UPDATES_DIR", str(share))

    from src.paths import data_dir, default_working_data_dir

    assert default_working_data_dir() == share / "data"
    assert data_dir() == share / "data"


def test_frozen_catalogs_live_in_the_work_folder(monkeypatch, tmp_path: Path):
    share = tmp_path / "share"
    share.mkdir()
    exe = tmp_path / "GrandSummary.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(exe))
    monkeypatch.delenv("GRAND_SUMMARY_DATA_DIR", raising=False)
    monkeypatch.delenv("GRAND_SUMMARY_OBJECTS_FILE", raising=False)
    monkeypatch.delenv("GRAND_SUMMARY_OBJECTS_DIR", raising=False)
    monkeypatch.delenv("GRAND_SUMMARY_MATERIALS_DIR", raising=False)
    monkeypatch.setenv("GRAND_SUMMARY_UPDATES_DIR", str(share))

    from src.paths import materials_database_dir, objects_database_path, work_root

    assert work_root() == share
    assert objects_database_path() == share / "временно бд объектов для тестов" / "projects.json"
    assert materials_database_dir() == share / "Библиотека материалов"


def test_frozen_data_dir_is_next_to_the_exe(monkeypatch, tmp_path: Path):
    exe = tmp_path / "GrandSummary.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(exe))
    monkeypatch.delenv("GRAND_SUMMARY_DATA_DIR", raising=False)

    from src import paths

    folder = paths.data_dir()
    assert folder == tmp_path / "data"
    assert folder.is_dir()


def test_json_copy_is_written_next_to_sqlite(tmp_path: Path, monkeypatch):
    database = tmp_path / "grand_summary.db"
    monkeypatch.setenv("GRAND_SUMMARY_DB", str(database))
    from backend.database import init_db, reset_engine
    from src.services.db_json import JSON_FILE_NAME, export_database_json

    reset_engine()
    init_db()
    json_copy = tmp_path / JSON_FILE_NAME
    assert json_copy.is_file()
    assert export_database_json() == json_copy

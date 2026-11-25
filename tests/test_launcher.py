from pathlib import Path

from desktop.launcher import _app_exe


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_launcher_starts_the_newest_release_exe(tmp_path: Path):
    older = tmp_path / "releases" / "0.0.1" / "GrandSummary" / "GrandSummary.exe"
    newer = tmp_path / "releases" / "0.0.10" / "GrandSummary.exe"
    _touch(older)
    _touch(newer)
    assert _app_exe(tmp_path) == newer


def test_launcher_accepts_exe_dropped_into_the_version_folder(tmp_path: Path):
    dropped = tmp_path / "releases" / "0.0.2" / "GrandSummary.exe"
    _touch(dropped)
    assert _app_exe(tmp_path) == dropped

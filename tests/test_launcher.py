import sys
from pathlib import Path

from desktop.launcher import _app_exe
from desktop.run import ensure_windowed_stdio


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_launcher_starts_the_newest_release_exe(tmp_path: Path):
    older = tmp_path / "releases" / "0.0.1" / "GrandSummary" / "GrandSummary.exe"
    newer = tmp_path / "releases" / "0.0.10" / "GrandSummary.exe"
    _touch(older)
    _touch(newer)
    assert _app_exe(tmp_path) == newer


def test_windowed_stdio_lets_uvicorn_start_without_a_console(monkeypatch):
    from uvicorn.logging import DefaultFormatter

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    ensure_windowed_stdio()
    DefaultFormatter()
    assert sys.stdout.isatty() is False
    assert sys.stderr.isatty() is False


def test_launcher_accepts_exe_dropped_into_the_version_folder(tmp_path: Path):
    dropped = tmp_path / "releases" / "0.0.2" / "GrandSummary.exe"
    _touch(dropped)
    assert _app_exe(tmp_path) == dropped

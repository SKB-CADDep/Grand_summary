from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _version_key(name: str) -> tuple[int, ...] | None:
    parts: list[int] = []
    for piece in name.split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    return tuple(parts) or None


def _app_exe(here: Path | None = None) -> Path:
    if here is None:
        here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    found: list[tuple[tuple[int, ...], Path]] = []
    version_root = here / "releases"
    if version_root.is_dir():
        for folder in version_root.iterdir():
            if not folder.is_dir():
                continue
            key = _version_key(folder.name)
            if key is None:
                continue
            for path in (folder / "GrandSummary" / "GrandSummary.exe", folder / "GrandSummary.exe"):
                if path.is_file():
                    found.append((key, path))
                    break
    found.sort(key=lambda item: item[0], reverse=True)
    candidates = [path for _, path in found]
    candidates.extend(
        [
            here / "releases" / "GrandSummary" / "GrandSummary.exe",
            here / "GrandSummary" / "GrandSummary.exe",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0] if candidates else here / "releases" / "GrandSummary" / "GrandSummary.exe"


def _here() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _show_error(message: str) -> None:
    text = str(message or "").strip() or "Ошибка."
    if os.name != "nt":
        sys.stderr.write(text + "\n")
        return
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, text, "Гранд сводка ИД", 0x10)


def _ask_update(current: str, latest: str) -> bool:
    text = (
        f"Доступна новая версия Гранд сводки.\n\n"
        f"Установлена: {current}\n"
        f"На шаре:     {latest}\n\n"
        f"Скачать её сейчас? Если отказаться, откроется текущая версия."
    )
    if os.name != "nt":
        return True
    import ctypes

    return ctypes.windll.user32.MessageBoxW(0, text, "Гранд сводка ИД", 0x04 | 0x20) == 6


class _ProgressDialog:
    """Запоминает ход копирования, пока лаунчер забирает релиз с шары."""

    def __init__(self, title: str, text: str) -> None:
        self.title = title
        self._text = text

    def report(self, message: str, current: int = 0, total: int = 0) -> None:
        if message:
            self._text = str(message)

    def __enter__(self) -> "_ProgressDialog":
        return self

    def __exit__(self, *_exc) -> None:
        return None


def _install_launcher(app_root: Path) -> None:
    if not getattr(sys, "frozen", False):
        return
    import shutil

    source = Path(sys.executable).resolve()
    destination = app_root / source.name
    if source == destination:
        return
    try:
        app_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    except OSError:
        return


def _start(exe: Path) -> None:
    from src.app_info import local_app_root

    os.environ.setdefault("GRAND_SUMMARY_DATA_DIR", str(local_app_root() / "data"))
    os.chdir(str(exe.parent))
    raise SystemExit(subprocess.call([str(exe), *sys.argv[1:]]))


def main() -> None:
    from src.app_info import FORCE_UPDATE_ENV, local_app_root
    from src.services.release_sync import dist_root, installed_version, published_version, release_exe, resolve_app_exe, version_key

    here = _here()
    app_root = local_app_root()
    dist = dist_root(here)
    force = str(os.environ.get(FORCE_UPDATE_ENV) or "") == "1"
    remote = published_version(dist) if dist is not None and dist.is_dir() else None
    local = installed_version(app_root)
    try:
        if remote and local and version_key(remote) > version_key(local) and not force:
            current = release_exe(local, app_root)
            if current is not None and not _ask_update(local, remote):
                _install_launcher(app_root)
                _start(current)
        needs_copy = bool(remote) and release_exe(remote, app_root) is None
        if needs_copy:
            with _ProgressDialog("Гранд сводка ИД", f"Загрузка версии {remote}…") as dialog:
                exe = resolve_app_exe(dist=dist, app_root=app_root, progress=dialog.report)
        else:
            exe = resolve_app_exe(dist=dist, app_root=app_root)
    except Exception as exc:
        fallback = _app_exe(here)
        if fallback.is_file():
            _start(fallback)
        _show_error(str(exc))
        raise SystemExit(1)
    _install_launcher(app_root)
    _start(exe)


if __name__ == "__main__":
    main()

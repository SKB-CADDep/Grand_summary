from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

WINDOW_TITLE = "Гранд сводка ИД"


class _NullStream:
    """Поток без консоли. На Windows файл nul сам отвечает isatty() == True."""

    def write(self, text: str = "") -> int:
        return len(text or "")

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def ensure_windowed_stdio() -> None:
    """В exe без консоли stdout/stderr равны None, и uvicorn падает на isatty()."""
    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()


ensure_windowed_stdio()
_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
_SHUTDOWN_REQUESTED = threading.Event()


def request_shutdown() -> None:
    _SHUTDOWN_REQUESTED.set()


if str(_ROOT) not in sys.path and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(_ROOT))


def _project_root() -> Path:
    from src.paths import project_root

    return project_root()


def _fatal(message: str) -> None:
    print(message, file=sys.stderr)
    if getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, WINDOW_TITLE, 0x10)
        except Exception:
            pass
    raise SystemExit(1)


def _missing_dependency(exc: ModuleNotFoundError) -> None:
    python = sys.executable
    req = _project_root() / "requirements.txt"
    name = exc.name or "зависимость"
    own_module = name.startswith("src.") or name.startswith("backend.") or name.startswith("desktop.")
    hint = (
        "В проекте нет этого модуля. Обновите исходники Гранд сводки и запустите снова."
        if own_module
        else "Для окна нужен PyQt6 (без WebEngine)."
    )
    print(
        f"В этом Python нет пакета «{name}». {hint}\n"
        f"Интерпретатор: {python}\n"
        f"Установите зависимости именно в него:\n"
        f"  \"{python}\" -m pip install -r \"{req}\"\n"
        f"В PyCharm: Settings → Python Interpreter → интерпретатор этого проекта Grand_summary, не PythonProject.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def open_window() -> None:
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
    except ModuleNotFoundError as exc:
        _missing_dependency(exc)

    try:
        from desktop.client import ApiClient
        from desktop.ui.style import APP_QSS, install_rounded_popups
        from desktop.ui.window import MainWindow
    except ModuleNotFoundError as exc:
        _missing_dependency(exc)

    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName(WINDOW_TITLE)
    qt_app.setStyleSheet(APP_QSS)
    install_rounded_popups(qt_app)
    client = ApiClient()
    window = MainWindow(client)
    window.show()

    def finish_update() -> None:
        if not _SHUTDOWN_REQUESTED.is_set():
            return
        window.close()
        qt_app.quit()

    shutdown_timer = QTimer()
    shutdown_timer.timeout.connect(finish_update)
    shutdown_timer.start(100)
    sys.exit(qt_app.exec())


def main() -> None:
    _SHUTDOWN_REQUESTED.clear()
    if getattr(sys, "frozen", False):
        from src.app_info import local_app_root
        from src.paths import default_working_data_dir

        data = default_working_data_dir()
        local_prefs = local_app_root() / "data"
        os.environ["GRAND_SUMMARY_DESKTOP"] = "1"
        os.environ.setdefault("GRAND_SUMMARY_DATA_DIR", str(data))
        os.environ.setdefault(
            "GRAND_SUMMARY_USER_PREFERENCES", str(local_prefs / "user_preferences.json")
        )
        os.environ.setdefault("GRAND_SUMMARY_GUIDE", str(local_prefs / "guide_seen.json"))
        os.environ["GRAND_SUMMARY_SQLITE_JOURNAL_MODE"] = "DELETE"
    else:
        from src.bootstrap import ensure_environment

        ensure_environment(frontend=False, build_frontend=False)
    open_window()


if __name__ == "__main__":
    main()

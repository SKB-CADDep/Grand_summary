from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
PREFERRED_PORT = 8765
WINDOW_TITLE = "Гранд сводка ИД"
_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
_API_SERVER = None
_SHUTDOWN_REQUESTED = threading.Event()


def request_shutdown() -> None:
    _SHUTDOWN_REQUESTED.set()


if str(_ROOT) not in sys.path and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(_ROOT))


def _project_root() -> Path:
    from src.paths import project_root

    return project_root()


def dist_dir() -> Path:
    from src.paths import frontend_dist

    return frontend_dist()


def _fatal(message: str) -> None:
    print(message, file=sys.stderr)
    if getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, WINDOW_TITLE, 0x10)
        except Exception:
            pass
    raise SystemExit(1)


def require_frontend_build() -> Path:
    path = dist_dir()
    index = path / "index.html"
    if not index.is_file():
        if getattr(sys, "frozen", False):
            _fatal("Не найден интерфейс внутри программы. Пересоберите exe командой py -3 compile.py")
        print(
            "Не найден собранный интерфейс (frontend/dist).\n"
            "Один раз соберите его:\n"
            "  cd frontend\n"
            "  npm install\n"
            "  npm run build\n"
            "Затем снова: py -3 run_desktop.py",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return path


def pick_port(preferred: int = PREFERRED_PORT) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        try:
            sock.bind((HOST, preferred))
            return preferred
        except OSError:
            sock.bind((HOST, 0))
            return int(sock.getsockname()[1])


def wait_until_ready(port: int, attempts: int = 50) -> None:
    url = f"http://{HOST}:{port}/api/health"
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if 200 <= response.status < 300:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"Сервер Гранд сводки не ответил на {url}: {last_error}")


def _missing_dependency(exc: ModuleNotFoundError) -> None:
    python = sys.executable
    req = _project_root() / "requirements.txt"
    name = exc.name or "зависимость"
    print(
        f"В этом Python нет пакета «{name}». Для окна нужны PyQt6 и PyQt6-WebEngine.\n"
        f"Интерпретатор: {python}\n"
        f"Установите зависимости именно в него:\n"
        f"  \"{python}\" -m pip install -r \"{req}\"\n"
        f"В PyCharm: Settings → Python Interpreter → Python этого проекта.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def start_api(port: int) -> None:
    global _API_SERVER
    try:
        import uvicorn
        from backend.main import app
    except ModuleNotFoundError as exc:
        _missing_dependency(exc)

    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    _API_SERVER = server
    server.install_signal_handlers = False
    thread = threading.Thread(target=server.run, name="grand-summary-api", daemon=True)
    thread.start()
    wait_until_ready(port)


def _configure_webengine_rendering() -> None:
    if sys.platform != "win32" or os.environ.get("GRAND_SUMMARY_ENABLE_WEBENGINE_GPU") == "1":
        return

    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if "--disable-gpu" not in flags.split():
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} --disable-gpu".strip()


def open_window(port: int) -> None:
    try:
        from PyQt6.QtCore import QSize, QTimer, QUrl
        from PyQt6.QtGui import QResizeEvent
        from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except ModuleNotFoundError as exc:
        _missing_dependency(exc)

    class GrandSummaryWindow(QMainWindow):
        def __init__(self, url: str) -> None:
            super().__init__()
            self.setWindowTitle(WINDOW_TITLE)
            self.resize(1280, 800)
            self.setMinimumSize(QSize(960, 640))
            self.view = QWebEngineView(self)
            self.setCentralWidget(self.view)
            self.view.page().profile().downloadRequested.connect(self._on_download)
            self._resize_refresh_timer = QTimer(self)
            self._resize_refresh_timer.setSingleShot(True)
            self._resize_refresh_timer.setInterval(140)
            self._resize_refresh_timer.timeout.connect(self._refresh_viewport)
            self.view.load(QUrl(url))

        def resizeEvent(self, event: QResizeEvent) -> None:
            super().resizeEvent(event)
            timer = getattr(self, "_resize_refresh_timer", None)
            if timer is not None:
                timer.start()

        def _refresh_viewport(self) -> None:
            self.view.update()
            self.view.page().runJavaScript(
                "window.dispatchEvent(new Event('resize'))"
            )

        def _on_download(self, item: QWebEngineDownloadRequest) -> None:
            suggested = item.suggestedFileName() or "grand_summary.docx"
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить сводку", suggested)
            if not path:
                item.cancel()
                return
            target = Path(path)
            item.setDownloadDirectory(str(target.parent))
            item.setDownloadFileName(target.name)
            item.accept()

    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName(WINDOW_TITLE)
    window = GrandSummaryWindow(f"http://{HOST}:{port}/")
    window.show()

    def finish_update() -> None:
        if not _SHUTDOWN_REQUESTED.is_set():
            return
        if _API_SERVER is not None:
            _API_SERVER.should_exit = True
        window.close()
        qt_app.quit()

    shutdown_timer = QTimer()
    shutdown_timer.timeout.connect(finish_update)
    shutdown_timer.start(100)
    sys.exit(qt_app.exec())


def main() -> None:
    _SHUTDOWN_REQUESTED.clear()
    _configure_webengine_rendering()
    if getattr(sys, "frozen", False):
        from src.app_info import local_app_root

        local_data = local_app_root() / "data"
        os.environ["GRAND_SUMMARY_DESKTOP"] = "1"
        os.environ.setdefault("GRAND_SUMMARY_DATA_DIR", str(_ROOT / "data"))
        os.environ.setdefault(
            "GRAND_SUMMARY_USER_PREFERENCES", str(local_data / "user_preferences.json")
        )
        os.environ.setdefault("GRAND_SUMMARY_GUIDE", str(local_data / "guide_seen.json"))
        os.environ["GRAND_SUMMARY_SQLITE_JOURNAL_MODE"] = "DELETE"
    else:
        from src.bootstrap import ensure_environment

        ensure_environment(frontend=True, build_frontend=True)
    require_frontend_build()
    port = pick_port()
    start_api(port)
    open_window(port)


if __name__ == "__main__":
    main()

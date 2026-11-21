# -*- coding: utf-8 -*-
"""Сборка окна «Гранд сводка ИД» в папку dist/GrandSummary/."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from src.app_info import APP_NAME, APP_VERSION, LAUNCHER_EXE_NAME
from src.services.updates import write_manifest

PROJECT = Path(__file__).resolve().parent
DIST = PROJECT / "dist"
BUILD = PROJECT / "build"
NAME = "GrandSummary"
ENTRY = PROJECT / "run_desktop.py"

SEP = ";" if sys.platform == "win32" else ":"

HIDDEN = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "pydantic",
    "openpyxl",
    "docx",
    "multipart",
    "httpx",
    "httpx._transports.asgi",
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "backend.main",
    "backend.routers.health",
    "backend.routers.objects",
    "backend.routers.updates",
    "backend.routers.workbooks",
    "desktop.client",
    "desktop.history",
    "desktop.ui.window",
    "desktop.ui.table_page",
    "desktop.ui.object_page",
    "desktop.ui.triangle_page",
    "desktop.ui.report_page",
    "desktop.ui.dialogs",
    "desktop.ui.style",
]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("[compile]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(cwd or PROJECT))
    if result.returncode != 0:
        sys.exit(result.returncode)


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def main() -> None:
    if not ENTRY.is_file():
        print("Нет run_desktop.py")
        sys.exit(1)
    from src.bootstrap import ensure_python_packages

    ensure_python_packages()
    ensure_pyinstaller()
    for folder in (DIST, BUILD):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
    app_output = BUILD / "app-output"
    app_work = BUILD / "app-work"
    launcher_work = BUILD / "launcher-work"
    app_output.mkdir(parents=True)
    DIST.mkdir(parents=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        NAME,
        "--paths",
        str(PROJECT),
        "--distpath",
        str(app_output),
        "--workpath",
        str(app_work),
        "--add-data",
        f"{PROJECT / 'templates'}{SEP}templates",
        "--add-data",
        f"{PROJECT / 'docs'}{SEP}docs",
        "--add-data",
        f"{PROJECT / 'data' / 'acl.json'}{SEP}data",
        "--collect-all",
        "PyQt6",
        "--exclude-module",
        "PyQt6.QtWebEngineCore",
        "--exclude-module",
        "PyQt6.QtWebEngineWidgets",
        "--exclude-module",
        "PyQt6.QtWebEngineQuick",
        "--exclude-module",
        "PyQt6.QtWebEngine",
        "--collect-all",
        "docx",
    ]
    for name in HIDDEN:
        cmd.extend(["--hidden-import", name])
    cmd.append(str(ENTRY))
    run(cmd)

    app_bundle = app_output / NAME
    if not (app_bundle / f"{NAME}.exe").is_file():
        raise SystemExit(f"Нет {app_bundle / f'{NAME}.exe'}")
    release_bundle = DIST / "releases" / APP_VERSION / APP_NAME
    release_bundle.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(app_bundle, release_bundle)

    launcher_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        LAUNCHER_EXE_NAME.removesuffix(".exe"),
        "--paths",
        str(PROJECT),
        "--distpath",
        str(DIST),
        "--workpath",
        str(launcher_work),
        str(PROJECT / "desktop" / "launcher.py"),
    ]
    run(launcher_cmd)
    launcher = DIST / LAUNCHER_EXE_NAME
    if not launcher.is_file():
        raise SystemExit(f"Нет {launcher}")
    write_manifest(DIST, APP_VERSION)
    print(f"[compile] релиз {APP_VERSION}: {release_bundle}")
    print(f"[compile] лаунчер: {launcher}")
    print("[compile] dist готов; на шару обновлений автоматически не копировалось.")


if __name__ == "__main__":
    main()

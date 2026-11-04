# -*- coding: utf-8 -*-
"""Сборка окна «Гранд сводка ИД» в папку dist/GrandSummary/."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
DIST = PROJECT / "dist"
BUILD = PROJECT / "build"
NAME = "GrandSummary"
ENTRY = PROJECT / "run_desktop.py"
FRONTEND_DIST = PROJECT / "frontend" / "dist"

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
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "backend.main",
    "backend.routers.health",
    "backend.routers.objects",
    "backend.routers.workbooks",
]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("[compile]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(cwd or PROJECT))
    if result.returncode != 0:
        sys.exit(result.returncode)


def ensure_frontend() -> None:
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        print("[compile] frontend/dist уже есть")
        return
    print("[compile] собираю интерфейс npm run build")
    npm = shutil.which("npm")
    if not npm:
        print("Нет npm. Соберите frontend вручную: cd frontend && npm run build")
        sys.exit(1)
    run([npm, "run", "build"], cwd=PROJECT / "frontend")


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
    ensure_frontend()
    ensure_pyinstaller()
    for folder in (DIST, BUILD):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

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
        "--add-data",
        f"{FRONTEND_DIST}{SEP}frontend/dist",
        "--add-data",
        f"{PROJECT / 'templates'}{SEP}templates",
        "--add-data",
        f"{PROJECT / 'docs'}{SEP}docs",
        "--add-data",
        f"{PROJECT / 'data' / 'objects.json'}{SEP}data",
        "--add-data",
        f"{PROJECT / 'data' / 'acl.json'}{SEP}data",
        "--collect-all",
        "PyQt6",
        "--collect-all",
        "PyQt6.QtWebEngineCore",
        "--collect-all",
        "docx",
    ]
    for name in HIDDEN:
        cmd.extend(["--hidden-import", name])
    cmd.append(str(ENTRY))
    run(cmd)

    exe = DIST / NAME / f"{NAME}.exe"
    print(f"[compile] готово: {exe}")


if __name__ == "__main__":
    main()

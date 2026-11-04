"""Установка зависимостей в текущий интерпретатор (в т.ч. при запуске из PyCharm)."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

CORE_MODULES = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "openpyxl",
    "docx",
    "pytest",
    "httpx",
    "PyQt6",
    "PyQt6.QtWebEngineWidgets",
)


def _project_root() -> Path:
    from src.paths import project_root

    return project_root()


def requirements_path() -> Path:
    return _project_root() / "requirements.txt"


def _marker_path() -> Path:
    digest = hashlib.sha256(sys.prefix.encode("utf-8", "replace")).hexdigest()[:16]
    folder = _project_root() / ".bootstrap"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.sha256"


def _requirements_hash() -> str:
    raw = requirements_path().read_bytes() if requirements_path().is_file() else b""
    return hashlib.sha256(raw).hexdigest()


def _core_missing() -> list[str]:
    import importlib.util

    missing: list[str] = []
    for name in CORE_MODULES:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    return missing


def _write_marker() -> None:
    _marker_path().write_text(f"{_requirements_hash()}\n{sys.executable}\n", encoding="utf-8")


def _marker_matches() -> bool:
    marker = _marker_path()
    if not marker.is_file():
        return False
    expected = f"{_requirements_hash()}\n{sys.executable}\n"
    return marker.read_text(encoding="utf-8") == expected


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("[env]", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ensure_python_packages(*, force: bool = False) -> None:
    if getattr(sys, "frozen", False):
        return
    if os.environ.get("GRAND_SUMMARY_SKIP_BOOTSTRAP") == "1" and not force:
        return
    req = requirements_path()
    if not req.is_file():
        print("[env] нет requirements.txt — пропускаю установку пакетов", flush=True)
        return
    missing = _core_missing()
    if not force and not missing and _marker_matches():
        return
    if not force and not missing and not _marker_path().is_file():
        _write_marker()
        return
    print(f"[env] интерпретатор: {sys.executable}", flush=True)
    if missing:
        print("[env] нет пакетов: " + ", ".join(missing), flush=True)
    print("[env] устанавливаю зависимости из requirements.txt…", flush=True)
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    _run([sys.executable, "-m", "pip", "install", "-r", str(req)])
    still = _core_missing()
    if still:
        print("[env] не установились: " + ", ".join(still), file=sys.stderr, flush=True)
        raise SystemExit(1)
    _write_marker()
    print("[env] пакеты готовы", flush=True)


def ensure_frontend(*, build: bool = True) -> None:
    if getattr(sys, "frozen", False):
        return
    if os.environ.get("GRAND_SUMMARY_SKIP_BOOTSTRAP") == "1":
        return
    root = _project_root()
    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        return
    index = frontend / "dist" / "index.html"
    modules = frontend / "node_modules"
    need_build = build and not index.is_file()
    need_modules = not modules.is_dir() and (need_build or not build)
    if not need_modules and not need_build:
        return
    npm = shutil.which("npm")
    if not npm:
        if index.is_file() and not need_modules:
            return
        print(
            "[env] Нет npm. Для сборки интерфейса поставьте Node.js, затем:\n"
            "  cd frontend\n  npm install\n  npm run build",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
    if need_modules:
        _run([npm, "install"], cwd=frontend)
    if need_build:
        _run([npm, "run", "build"], cwd=frontend)


def ensure_environment(*, frontend: bool = True, build_frontend: bool = True) -> None:
    ensure_python_packages()
    if frontend:
        ensure_frontend(build=build_frontend)

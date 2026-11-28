"""Копирование релиза с общей папки в локальный каталог пользователя."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.app_info import (
    APP_EXE_NAME,
    APP_NAME,
    APP_VERSION,
    FORCE_UPDATE_ENV,
    LAUNCHER_EXE_NAME,
    SHARED_UPDATES_DIR,
    UPDATES_DIR_ENV,
    local_app_root,
)


def version_key(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(text or "").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def launcher_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def is_local_install(exe_dir: Path | None = None) -> bool:
    here = (exe_dir or launcher_dir()).resolve()
    root = local_app_root().resolve()
    return here == root or root in here.parents


def dist_root(exe_dir: Path | None = None) -> Path | None:
    """Папка обновлений: env, каталог лаунчера на шаре или общая папка."""
    configured = str(os.environ.get(UPDATES_DIR_ENV) or "").strip()
    if configured:
        return Path(configured)
    here = (exe_dir or launcher_dir()).resolve()
    if not is_local_install(here) and (here / "manifest.json").is_file() and (here / "releases").is_dir():
        return here
    if not getattr(sys, "frozen", False):
        return None
    return SHARED_UPDATES_DIR


def _same_file_contents(first: Path, second: Path) -> bool:
    if first.stat().st_size != second.stat().st_size:
        return False
    digests = []
    for path in (first, second):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digests.append(digest.digest())
    return digests[0] == digests[1]


def read_manifest(root: Path | None) -> dict | None:
    if root is None:
        return None
    path = Path(root) / "manifest.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    active = str(raw.get("active_version") or raw.get("version") or "").strip()
    if not active:
        return None
    releases = str(raw.get("releases_subdir") or "releases").strip() or "releases"
    exe_name = str(raw.get("exe_name") or APP_EXE_NAME).strip() or APP_EXE_NAME
    return {
        "active_version": active,
        "releases_subdir": releases,
        "exe_name": exe_name,
        "raw": raw,
    }


def write_manifest(dist_dir: Path, version: str, *, exe_name: str = APP_EXE_NAME) -> Path:
    root = Path(dist_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": APP_NAME,
        "version": version,
        "active_version": version,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "releases_subdir": "releases",
        "exe_name": exe_name,
    }
    path = root / "manifest.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _numeric_version(name: str) -> bool:
    parts = name.split(".")
    return bool(parts) and all(part.isdigit() for part in parts)


def release_exe(
    version: str,
    root: Path,
    exe_name: str = APP_EXE_NAME,
    *,
    releases_subdir: str = "releases",
) -> Path | None:
    folder = Path(root) / releases_subdir / version
    for path in (folder / exe_name, folder / APP_NAME / exe_name):
        if path.is_file():
            return path
    return None


def published_version(dist: Path) -> str | None:
    """Версия с шары: более новая папка в releases, иначе версия из manifest.json."""
    manifest = read_manifest(dist)
    chosen = manifest["active_version"] if manifest else ""
    exe_name = manifest["exe_name"] if manifest else APP_EXE_NAME
    releases_name = manifest["releases_subdir"] if manifest else "releases"
    releases = Path(dist) / releases_name
    if releases.is_dir():
        for child in releases.iterdir():
            if not child.is_dir() or not _numeric_version(child.name):
                continue
            if release_exe(child.name, dist, exe_name, releases_subdir=releases_name) is None:
                continue
            if version_key(child.name) > version_key(chosen):
                chosen = child.name
    return chosen or None


def installed_version(app_root: Path) -> str | None:
    manifest = read_manifest(app_root)
    if manifest and release_exe(manifest["active_version"], app_root, manifest["exe_name"]):
        return manifest["active_version"]
    releases = Path(app_root) / "releases"
    chosen = ""
    if releases.is_dir():
        for child in releases.iterdir():
            if not child.is_dir() or not _numeric_version(child.name):
                continue
            if release_exe(child.name, app_root) is None:
                continue
            if version_key(child.name) > version_key(chosen):
                chosen = child.name
    return chosen or None


def copy_release_version(
    version: str,
    *,
    dist: Path,
    app_root: Path,
    exe_name: str = APP_EXE_NAME,
    progress=None,
) -> Path:
    report = progress or (lambda *_args: None)
    manifest = read_manifest(dist)
    releases_name = manifest["releases_subdir"] if manifest else "releases"
    source = Path(dist) / releases_name / version
    if not source.is_dir():
        raise FileNotFoundError(f"Каталог версии не найден:\n{source}")
    destination = Path(app_root) / "releases" / version
    temporary = destination.with_name(f"{version}.tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    files = [path for path in source.rglob("*") if path.is_file()]
    total = sum(path.stat().st_size for path in files) or 1
    done = 0
    report(f"Копирование {version}…", 0, total)
    for path in files:
        target = temporary / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        done += path.stat().st_size
        report(f"Копирование {version}… ({int(done * 100 / total)}%)", done, total)
    if not ((temporary / exe_name).is_file() or (temporary / APP_NAME / exe_name).is_file()):
        shutil.rmtree(temporary, ignore_errors=True)
        raise FileNotFoundError(f"В релизе нет {exe_name}:\n{source}")
    if destination.exists():
        shutil.rmtree(destination)
    temporary.rename(destination)
    report(f"Версия {version} скопирована.", total, total)
    return destination


def cleanup_older_releases(app_root: Path, keep_version: str) -> None:
    releases = Path(app_root) / "releases"
    if not releases.is_dir():
        return
    keep = version_key(keep_version)
    for child in releases.iterdir():
        if not child.is_dir() or not _numeric_version(child.name):
            continue
        if version_key(child.name) == keep:
            continue
        shutil.rmtree(child, ignore_errors=True)


def resolve_app_exe(*, dist: Path | None, app_root: Path, progress=None) -> Path:
    """Копирует опубликованную версию с шары, если её ещё нет локально."""
    root = Path(app_root)
    remote_version = published_version(dist) if dist is not None and Path(dist).is_dir() else None
    manifest = read_manifest(dist) if dist is not None else None
    exe_name = manifest["exe_name"] if manifest else APP_EXE_NAME
    local_version = installed_version(root)
    refresh_same_version = False
    if remote_version and local_version and version_key(remote_version) == version_key(local_version):
        source_exe = release_exe(remote_version, Path(dist), exe_name, releases_subdir=(manifest["releases_subdir"] if manifest else "releases"))
        local_exe = release_exe(local_version, root, exe_name)
        refresh_same_version = bool(
            source_exe and local_exe and not _same_file_contents(source_exe, local_exe)
        )
    if remote_version and (
        local_version is None
        or version_key(remote_version) > version_key(local_version)
        or refresh_same_version
    ):
        if release_exe(remote_version, root, exe_name) is None or refresh_same_version:
            copy_release_version(remote_version, dist=Path(dist), app_root=root, exe_name=exe_name, progress=progress)
        write_manifest(root, remote_version, exe_name=exe_name)
        cleanup_older_releases(root, remote_version)
        exe = release_exe(remote_version, root, exe_name)
        if exe is None:
            raise FileNotFoundError(f"Не найден {root / 'releases' / remote_version / exe_name}")
        return exe
    if local_version:
        exe = release_exe(local_version, root, exe_name)
        if exe is None:
            raise FileNotFoundError(f"Локальный exe не найден для версии {local_version}.")
        return exe
    raise FileNotFoundError("Нет manifest.json ни на шаре обновлений, ни локально.")


def check_for_update(dist: Path | None = None) -> tuple[str, str] | None:
    root = dist if dist is not None else dist_root()
    if root is None or not Path(root).is_dir():
        return None
    latest = published_version(Path(root))
    if latest and version_key(latest) > version_key(APP_VERSION):
        return (APP_VERSION, latest)
    return None


def launch_launcher_for_update() -> Path:
    launcher = local_app_root() / LAUNCHER_EXE_NAME
    if not launcher.is_file():
        source = dist_root()
        candidate = source / LAUNCHER_EXE_NAME if source is not None else None
        if candidate is not None and candidate.is_file():
            launcher = candidate
    if not launcher.is_file():
        raise FileNotFoundError(f"Лаунчер не найден:\n{launcher}")
    env = os.environ.copy()
    env[FORCE_UPDATE_ENV] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(launcher)],
        cwd=str(launcher.parent),
        env=env,
        creationflags=flags,
        close_fds=True,
    )
    return launcher

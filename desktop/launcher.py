from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _app_exe() -> Path:
    here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    candidates = [
        here / "GrandSummary" / "GrandSummary.exe",
        here / "releases" / "GrandSummary" / "GrandSummary.exe",
    ]
    version_root = here / "releases"
    if version_root.is_dir():
        for folder in sorted(version_root.iterdir(), reverse=True):
            candidates.append(folder / "GrandSummary" / "GrandSummary.exe")
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def main() -> None:
    exe = _app_exe()
    if not exe.is_file():
        raise SystemExit(f"Не найден {exe}")
    os.chdir(str(exe.parent))
    raise SystemExit(subprocess.call([str(exe), *sys.argv[1:]]))


if __name__ == "__main__":
    main()

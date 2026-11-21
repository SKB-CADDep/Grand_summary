from __future__ import annotations

from src.paths import materials_database_dir

SKIP_NAMES = {"source"}


def list_material_names() -> list[str]:
    root = materials_database_dir() / "data"
    if not root.is_dir():
        root = materials_database_dir()
    if not root.is_dir():
        return []
    names = []
    for path in root.glob("*.json"):
        name = path.stem.strip()
        if name and name.casefold() not in SKIP_NAMES:
            names.append(name)
    return sorted(names, key=lambda item: item.casefold())

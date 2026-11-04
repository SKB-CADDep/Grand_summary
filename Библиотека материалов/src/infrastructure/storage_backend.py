import json
from pathlib import Path

SOURCE_JSON_NAME = "source.json"


class LocalDirectoryStorage:
    """Хранение JSON-файлов материалов в рабочей директории."""

    def __init__(self, directory: Path):
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        return self._directory

    def list_material_paths(self) -> list[Path]:
        """Пути к *.json в директории, кроме source.json."""
        if not self._directory.is_dir():
            return []

        paths = [
            path
            for path in self._directory.glob("*.json")
            if path.name != SOURCE_JSON_NAME
        ]
        return sorted(paths, key=lambda p: p.name.lower())

    def read_json(self, path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Ожидался JSON-объект в {path}")
        return data

    def write_json(self, path: Path, data: dict) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def exists(self, path: Path) -> bool:
        return Path(path).is_file()

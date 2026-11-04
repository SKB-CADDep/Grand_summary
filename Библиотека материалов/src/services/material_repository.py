from __future__ import annotations

from pathlib import Path

from src.core.models.material import Material
from src.core.schema_keys import Schema
from src.infrastructure.storage_backend import LocalDirectoryStorage
from src.services.source_service import SourceService


class MaterialRepository:
    """Состояние рабочей папки: материалы, области применения, источники."""

    def __init__(
        self,
        source_service: SourceService | None = None,
        storage: LocalDirectoryStorage | None = None,
    ):
        self.work_dir: str = ""
        self.materials: list[Material] = []
        self.application_areas: list[str] = []
        self.current_material: Material | None = None
        self.source_manager = source_service or SourceService()
        self._storage = storage

    def load_materials_from_dir(self, directory: str | Path) -> None:
        directory = Path(directory)
        self.work_dir = str(directory)
        self.materials.clear()
        self._storage = LocalDirectoryStorage(directory)

        if not directory.is_dir():
            self.application_areas = []
            return

        for path in self._storage.list_material_paths():
            try:
                self.materials.append(Material(filepath=str(path)))
            except Exception as e:
                print(f"Ошибка чтения {path.name}: {e}")

        self.materials.sort(key=lambda m: m.get_display_name())
        self.load_application_areas()

    def load_application_areas(self) -> None:
        all_areas: set[str] = set()
        for m in self.materials:
            all_areas.update(m.data.get(Schema.METADATA, {}).get(Schema.APP_AREA, []))
        self.application_areas = sorted(all_areas)

    def get_by_id(self, material_id: str) -> Material | None:
        for m in self.materials:
            if m.data.get("material_id") == material_id:
                return m
        return None

    def list_summary(self) -> list[dict]:
        result = []
        for m in self.materials:
            meta = m.data.get(Schema.METADATA, {})
            result.append({
                "id": m.data.get("material_id"),
                "name": m.get_display_name(),
                "areas": meta.get(Schema.APP_AREA, []),
                "filename": m.filename,
            })
        return result

    def save_material(self, material: Material) -> None:
        if not material.filepath:
            raise ValueError("Путь для сохранения не указан")
        material.save()
        if self._storage and not self._storage.exists(Path(material.filepath)):
            self.materials.append(material)
            self.materials.sort(key=lambda m: m.get_display_name())
            self.load_application_areas()


AppData = MaterialRepository

import json

from src.infrastructure.paths import config_dir
from src.core.math.interpolation import MathUtils


class HardnessTable:
    """Пересчёт твёрдости по config/hardness_table.json через линейную интерполяцию."""

    SYSTEM_UNIT = "HB"

    def _load_json(self, filename: str) -> dict:
        path = config_dir() / filename
        if not path.is_file():
            raise FileNotFoundError(f"Не найден config/hardness_table.json: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def __init__(self):
        data = self._load_json("hardness_table.json")
        self._columns = data["columns"]
        self._rows = data["rows"]
        self._idx = {name: i for i, name in enumerate(self._columns)}

    def convert(self, value, from_unit, to_unit):
        """Перевод value из from_unit в to_unit."""
        if value is None:
            return None
        if from_unit == to_unit:
            return float(value)
        return self._interpolate(float(value), from_unit, to_unit)

    def _interpolate(self, value, col_source_name, col_target_name):
        """
        Ищет значение в таблице, используя линейную интерполяцию.
        Если значение выходит за пределы известных данных для этой пары единиц — возвращает None.
        """
        idx_src = self._idx.get(col_source_name)
        idx_tgt = self._idx.get(col_target_name)

        if idx_src is None or idx_tgt is None:
            return None

        points = []
        for row in self._rows:
            x = row[idx_src]
            y = row[idx_tgt]
            if x is not None and y is not None:
                points.append((float(x), float(y)))

        return MathUtils.linear_interpolate(points, value)

    def column_names(self):
        return list(self._columns)

    columns_name = column_names

    def is_supported_unit(self, unit):
        return unit in self._idx

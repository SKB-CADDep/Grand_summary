"""Тесты схемы property_groups."""
import unittest

from src.core.models.material import Material
from src.core.schema_keys import Schema


class PropertyGroupsSchemaTests(unittest.TestCase):
    def test_empty_structure(self):
        data = Material.get_empty_structure()
        types = [g[Schema.PROPERTY_TYPE] for g in data[Schema.PROPERTY_GROUPS]]
        self.assertEqual(types, [Schema.TYPE_PHYSICAL, Schema.TYPE_MECHANICAL, Schema.TYPE_CHEMICAL])

    def test_load_new_format_fixture(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "БД материалов" / "08Х13 — копия.json"
        if not path.is_file():
            self.skipTest("fixture missing")
        mat = Material(filepath=str(path))
        self.assertEqual(mat.get_interpolated_property("density", 20), 7760.0)
        self.assertEqual(mat.get_interpolated_property("yield_strength", 20, 0), 392.0)
        cats = mat.get_strength_categories()
        self.assertEqual(Material.category_name(cats[0]), "КП40")
        self.assertEqual(Material.get_hardness_entries(cats[0])[0]["min_value"], 187.0)
        self.assertEqual(mat.get_compositions()[0]["composition_source"], "ГОСТ 5632-2014")

    def test_normalize_legacy(self):
        legacy = {
            "material_id": "x",
            Schema.METADATA: {Schema.NAME_STD: "T"},
            Schema.PHYSICAL: {
                "density": {Schema.TEMP_PAIRS: [[20.0, 7800.0]], "value_unit": "кг/м3"},
            },
            Schema.MECHANICAL: {
                "strength_category": [
                    {
                        "value_strength_category": "КП1",
                        "hardness": [{"unit_value": "HB", "min_value": 100, "max_value": 120}],
                        "yield_strength": {Schema.TEMP_PAIRS: [[20.0, 300.0]]},
                    }
                ]
            },
            Schema.CHEMICAL: {
                Schema.COMPOSITION: [
                    {"composition_source": "G", "other_elements": [{"element": "C", "max_value": 0.1}]}
                ]
            },
        }
        mat = Material(data=legacy)
        self.assertNotIn(Schema.PHYSICAL, mat.data)
        self.assertEqual(mat.get_interpolated_property("density", 20), 7800.0)
        self.assertEqual(mat.get_interpolated_property("yield_strength", 20, 0), 300.0)
        self.assertEqual(Material.get_hardness_unit(mat.get_strength_categories()[0]), "HB")
        self.assertEqual(mat.get_compositions()[0]["composition_source"], "G")

    def test_set_physical_and_hardness(self):
        mat = Material()
        mat.set_physical_data("density", {Schema.TEMP_PAIRS: [[20.0, 7900.0]]})
        self.assertEqual(mat.get_physical_data("density")[Schema.TEMP_PAIRS][0][1], 7900.0)
        cat = Material.empty_strength_group("КП2")
        mat.ensure_group(Schema.TYPE_MECHANICAL)[Schema.STRENGTH_GROUPS].append(cat)
        Material.set_hardness_entries(cat, [{"unit_value": "HB", "min_value": 1, "max_value": 2}], unit="HB")
        self.assertEqual(Material.get_hardness_entries(cat)[0]["max_value"], 2)


if __name__ == "__main__":
    unittest.main()

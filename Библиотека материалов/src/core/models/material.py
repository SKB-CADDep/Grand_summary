import json
import os
from datetime import datetime
import uuid

from src.core.schema_keys import Schema
from src.core.math.interpolation import MathUtils


class Material:
    """
    Материал на схеме property_groups:

      property_groups[]:
        - property_type: physical  → properties[{property_name, data}]
        - property_type: mechanical → strength_groups[{strength_category, properties[…]}]
        - property_type: chemical  → properties[{property_name: composition, data}]

    Legacy physical_properties / mechanical_properties / chemical_properties
    нормализуются при загрузке.
    """

    def __init__(self, filepath=None, data=None):
        self.filepath = filepath
        if filepath:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        elif data:
            self.data = data
        else:
            self.data = self.get_empty_structure()
        self.filename = os.path.basename(self.filepath) if self.filepath else "Новый материал.json"
        self.normalize_schema()

    def get_name(self):
        return self.data.get(Schema.METADATA, {}).get(Schema.NAME_STD, "Без имени")

    def get_display_name(self):
        meta = self.data.get(Schema.METADATA, {})
        std = meta.get(Schema.NAME_STD, "Без имени")
        alts = [a.strip() for a in meta.get(Schema.NAME_ALT, []) if a.strip()]
        return f"{std} ({', '.join(alts)})" if alts else std

    @staticmethod
    def get_empty_structure():
        return {
            "material_id": str(uuid.uuid4()),
            Schema.METADATA: {
                Schema.NAME_STD: "", Schema.NAME_ALT: [], Schema.APP_AREA: [], "comment": "",
                "classification": {
                    "classification_category": "",
                    "classification_class": "",
                    "classification_subclass": "",
                },
            },
            Schema.PROPERTY_GROUPS: [
                {Schema.PROPERTY_TYPE: Schema.TYPE_PHYSICAL, Schema.PROPERTIES: []},
                {Schema.PROPERTY_TYPE: Schema.TYPE_MECHANICAL, Schema.STRENGTH_GROUPS: []},
                {Schema.PROPERTY_TYPE: Schema.TYPE_CHEMICAL, Schema.PROPERTIES: []},
            ],
        }

    @staticmethod
    def empty_strength_group(name=""):
        return {
            Schema.STRENGTH_CAT: name,
            "comment": "",
            Schema.PROPERTIES: [],
        }

    # ------------------------------------------------------------------
    # property_groups helpers
    # ------------------------------------------------------------------

    def get_property_groups(self):
        groups = self.data.get(Schema.PROPERTY_GROUPS)
        return groups if isinstance(groups, list) else []

    def get_group(self, property_type):
        for g in self.get_property_groups():
            if isinstance(g, dict) and g.get(Schema.PROPERTY_TYPE) == property_type:
                return g
        return None

    def ensure_group(self, property_type):
        g = self.get_group(property_type)
        if g is not None:
            return g
        if property_type == Schema.TYPE_MECHANICAL:
            g = {Schema.PROPERTY_TYPE: property_type, Schema.STRENGTH_GROUPS: []}
        else:
            g = {Schema.PROPERTY_TYPE: property_type, Schema.PROPERTIES: []}
        if Schema.PROPERTY_GROUPS not in self.data or not isinstance(
            self.data.get(Schema.PROPERTY_GROUPS), list
        ):
            self.data[Schema.PROPERTY_GROUPS] = []
        self.data[Schema.PROPERTY_GROUPS].append(g)
        return g

    @staticmethod
    def find_named_prop(props, prop_name):
        if not isinstance(props, list):
            return None
        for item in props:
            if isinstance(item, dict) and item.get(Schema.PROP_NAME) == prop_name:
                return item
        return None

    @staticmethod
    def get_prop_data(prop_entry):
        if not isinstance(prop_entry, dict):
            return None
        data = prop_entry.get(Schema.DATA)
        return data if isinstance(data, dict) else None

    @staticmethod
    def upsert_named_prop(props, prop_name, data):
        if not isinstance(props, list):
            props = []
        payload = {Schema.PROP_NAME: prop_name, Schema.DATA: dict(data) if data else {}}
        for i, item in enumerate(props):
            if isinstance(item, dict) and item.get(Schema.PROP_NAME) == prop_name:
                props[i] = payload
                return props
        props.append(payload)
        return props

    @staticmethod
    def remove_named_prop(props, prop_name):
        if not isinstance(props, list):
            return []
        return [
            p for p in props
            if not (isinstance(p, dict) and p.get(Schema.PROP_NAME) == prop_name)
        ]

    @staticmethod
    def category_name(cat):
        if not isinstance(cat, dict):
            return ""
        return (
            cat.get(Schema.STRENGTH_CAT)
            or cat.get(Schema.VAL_STR_CAT)
            or ""
        )

    # ------------------------------------------------------------------
    # Physical
    # ------------------------------------------------------------------

    def get_physical_properties_list(self):
        g = self.get_group(Schema.TYPE_PHYSICAL)
        if not g:
            return []
        props = g.get(Schema.PROPERTIES)
        return props if isinstance(props, list) else []

    def get_physical_data(self, prop_name):
        entry = self.find_named_prop(self.get_physical_properties_list(), prop_name)
        return self.get_prop_data(entry)

    def set_physical_data(self, prop_name, data):
        g = self.ensure_group(Schema.TYPE_PHYSICAL)
        props = g.get(Schema.PROPERTIES)
        if not isinstance(props, list):
            props = []
        g[Schema.PROPERTIES] = self.upsert_named_prop(props, prop_name, data)

    def remove_physical_data(self, prop_name):
        g = self.get_group(Schema.TYPE_PHYSICAL)
        if not g:
            return
        g[Schema.PROPERTIES] = self.remove_named_prop(
            g.get(Schema.PROPERTIES, []), prop_name
        )

    # ------------------------------------------------------------------
    # Mechanical / strength groups
    # ------------------------------------------------------------------

    def get_strength_categories(self):
        """Список strength_groups (категорий прочности)."""
        g = self.get_group(Schema.TYPE_MECHANICAL)
        if not g:
            return []
        groups = g.get(Schema.STRENGTH_GROUPS)
        return groups if isinstance(groups, list) else []

    @staticmethod
    def get_category_prop_data(cat, prop_name):
        if not isinstance(cat, dict):
            return None
        entry = Material.find_named_prop(cat.get(Schema.PROPERTIES), prop_name)
        return Material.get_prop_data(entry)

    @staticmethod
    def set_category_prop_data(cat, prop_name, data):
        if not isinstance(cat, dict):
            return
        props = cat.get(Schema.PROPERTIES)
        if not isinstance(props, list):
            props = []
        cat[Schema.PROPERTIES] = Material.upsert_named_prop(props, prop_name, data)

    @staticmethod
    def remove_category_prop_data(cat, prop_name):
        if not isinstance(cat, dict):
            return
        cat[Schema.PROPERTIES] = Material.remove_named_prop(
            cat.get(Schema.PROPERTIES, []), prop_name
        )

    @staticmethod
    def get_hardness_entries(cat):
        data = Material.get_category_prop_data(cat, Schema.HARDNESS)
        if data and isinstance(data.get(Schema.HARDNESS_VALUES), list):
            return data[Schema.HARDNESS_VALUES]
        # legacy fallbacks
        if isinstance(cat, dict):
            if isinstance(cat.get(Schema.HARDNESS), list):
                return cat[Schema.HARDNESS]
            hard_entry = Material.find_named_prop(cat.get(Schema.PROPERTIES), Schema.HARDNESS)
            if hard_entry:
                d = Material.get_prop_data(hard_entry) or {}
                if isinstance(d.get("values"), list):
                    return d["values"]
        return []

    @staticmethod
    def get_hardness_unit(cat, default="HB"):
        data = Material.get_category_prop_data(cat, Schema.HARDNESS)
        if data:
            unit = data.get(Schema.HARDNESS_UNIT) or data.get("property_unit") or data.get("value_unit")
            if unit:
                return unit
            vals = data.get(Schema.HARDNESS_VALUES) or []
            if vals and isinstance(vals[0], dict) and vals[0].get("unit_value"):
                return vals[0]["unit_value"]
        if isinstance(cat, dict):
            if cat.get(Schema.HARDNESS_UNIT):
                return cat[Schema.HARDNESS_UNIT]
            legacy = cat.get(Schema.HARDNESS)
            if isinstance(legacy, list) and legacy:
                return legacy[0].get("unit_value") or default
        return default

    @staticmethod
    def set_hardness_entries(cat, values_list, unit="HB", comment=""):
        Material.set_category_prop_data(
            cat,
            Schema.HARDNESS,
            {
                Schema.HARDNESS_VALUES: values_list or [],
                Schema.HARDNESS_UNIT: unit,
                "comment": comment or "",
            },
        )
        if isinstance(cat, dict):
            cat.pop(Schema.HARDNESS_UNIT, None)
            if isinstance(cat.get(Schema.HARDNESS), list):
                del cat[Schema.HARDNESS]

    # ------------------------------------------------------------------
    # Chemical
    # ------------------------------------------------------------------

    def get_compositions(self):
        """Список data-объектов composition (мутабельные ссылки на JSON)."""
        g = self.get_group(Schema.TYPE_CHEMICAL)
        if not g:
            return []
        result = []
        for item in g.get(Schema.PROPERTIES) or []:
            if not isinstance(item, dict):
                continue
            if item.get(Schema.PROP_NAME) != Schema.COMPOSITION:
                continue
            data = self.get_prop_data(item)
            if data is not None:
                result.append(data)
        return result

    def get_composition_entries(self):
        """Список обёрток {property_name, data} для composition."""
        g = self.get_group(Schema.TYPE_CHEMICAL)
        if not g:
            return []
        return [
            item for item in (g.get(Schema.PROPERTIES) or [])
            if isinstance(item, dict) and item.get(Schema.PROP_NAME) == Schema.COMPOSITION
        ]

    def set_compositions(self, composition_data_list):
        g = self.ensure_group(Schema.TYPE_CHEMICAL)
        props = [
            {Schema.PROP_NAME: Schema.COMPOSITION, Schema.DATA: dict(d) if d else {}}
            for d in (composition_data_list or [])
        ]
        # сохранить не-composition свойства, если появятся
        other = [
            p for p in (g.get(Schema.PROPERTIES) or [])
            if isinstance(p, dict) and p.get(Schema.PROP_NAME) != Schema.COMPOSITION
        ]
        g[Schema.PROPERTIES] = other + props

    def append_composition(self, data):
        g = self.ensure_group(Schema.TYPE_CHEMICAL)
        props = g.get(Schema.PROPERTIES)
        if not isinstance(props, list):
            props = []
            g[Schema.PROPERTIES] = props
        props.append({Schema.PROP_NAME: Schema.COMPOSITION, Schema.DATA: dict(data) if data else {}})

    def delete_composition_at(self, index):
        entries = self.get_composition_entries()
        if index < 0 or index >= len(entries):
            return
        target = entries[index]
        g = self.get_group(Schema.TYPE_CHEMICAL)
        if not g:
            return
        props = g.get(Schema.PROPERTIES) or []
        g[Schema.PROPERTIES] = [p for p in props if p is not target]

    # ------------------------------------------------------------------
    # Lookup used by UI (raw material_data dict without Material instance)
    # ------------------------------------------------------------------

    @staticmethod
    def physical_data_from_raw(material_data, prop_name):
        if not isinstance(material_data, dict):
            return None
        for g in material_data.get(Schema.PROPERTY_GROUPS) or []:
            if not isinstance(g, dict) or g.get(Schema.PROPERTY_TYPE) != Schema.TYPE_PHYSICAL:
                continue
            entry = Material.find_named_prop(g.get(Schema.PROPERTIES), prop_name)
            return Material.get_prop_data(entry)
        # legacy
        phys = material_data.get(Schema.PHYSICAL)
        if isinstance(phys, dict):
            p = phys.get(prop_name)
            return p if isinstance(p, dict) else None
        if isinstance(phys, list):
            for item in phys:
                if isinstance(item, dict) and (
                    item.get(Schema.PROP_NAME) == prop_name or item.get("property_id") == prop_name
                ):
                    return item.get(Schema.DATA) if isinstance(item.get(Schema.DATA), dict) else item
        return None

    @staticmethod
    def category_prop_data_from_raw(cat, prop_name):
        return Material.get_category_prop_data(cat, prop_name)

    # ------------------------------------------------------------------
    # Interpolation / sources
    # ------------------------------------------------------------------

    def get_interpolated_property(self, prop_key, temp, category_idx=None):
        data = self.get_physical_data(prop_key)
        if data:
            val = MathUtils.linear_interpolate(data.get(Schema.TEMP_PAIRS, []), temp)
            if val is not None:
                return val

        cats = self.get_strength_categories()
        target = (
            [cats[category_idx]]
            if category_idx is not None and 0 <= category_idx < len(cats)
            else cats
        )
        for cat in target:
            data = self.get_category_prop_data(cat, prop_key)
            if data:
                val = MathUtils.linear_interpolate(data.get(Schema.TEMP_PAIRS, []), temp)
                if val is not None:
                    return val
        return None

    def get_source_info(self, prop_type, prop_key=None, category_idx=None, source_manager=None):
        def resolve(container):
            if not isinstance(container, dict):
                return None
            rid = container.get(Schema.REF_ID)
            if rid and source_manager:
                return source_manager.get_name_by_id(rid)
            return (
                container.get("property_source")
                or container.get("property_subsource")
                or None
            )

        if prop_type in (Schema.PHYSICAL, Schema.TYPE_PHYSICAL):
            data = self.get_physical_data(prop_key) if prop_key else None
            return resolve(data) or "-"

        if prop_type in (Schema.MECHANICAL, Schema.TYPE_MECHANICAL):
            cats = self.get_strength_categories()
            if not cats:
                return "-"
            cat = (
                cats[category_idx]
                if category_idx is not None and 0 <= category_idx < len(cats)
                else cats[0]
            )
            name = resolve(cat)
            if name:
                return name
            if prop_key:
                return resolve(self.get_category_prop_data(cat, prop_key)) or "-"
            return "-"

        return "-"

    # ------------------------------------------------------------------
    # Legacy → property_groups
    # ------------------------------------------------------------------

    def normalize_schema(self):
        """Идемпотентно приводит self.data к property_groups."""
        if isinstance(self.data.get(Schema.PROPERTY_GROUPS), list) and self.data[Schema.PROPERTY_GROUPS]:
            # уже новая схема; подчистим legacy-ключи если остались
            self._drop_legacy_roots()
            return

        groups = []

        # physical
        phys = self.data.get(Schema.PHYSICAL)
        phys_props = []
        if isinstance(phys, dict):
            for key, val in phys.items():
                if isinstance(val, dict):
                    phys_props.append({Schema.PROP_NAME: key, Schema.DATA: dict(val)})
        elif isinstance(phys, list):
            for item in phys:
                if not isinstance(item, dict):
                    continue
                name = item.get(Schema.PROP_NAME) or item.get("property_id")
                if not name:
                    continue
                data = item.get(Schema.DATA) if isinstance(item.get(Schema.DATA), dict) else {
                    k: v for k, v in item.items() if k not in (Schema.PROP_NAME, "property_id")
                }
                phys_props.append({Schema.PROP_NAME: name, Schema.DATA: data})
        groups.append({Schema.PROPERTY_TYPE: Schema.TYPE_PHYSICAL, Schema.PROPERTIES: phys_props})

        # mechanical
        strength_groups = []
        mech = self.data.get(Schema.MECHANICAL)
        if isinstance(mech, dict):
            cats = mech.get("strength_category") or mech.get(Schema.STRENGTH_GROUPS) or []
            if isinstance(cats, list):
                for cat in cats:
                    if not isinstance(cat, dict):
                        continue
                    strength_groups.append(self._normalize_legacy_category(cat))
        groups.append({
            Schema.PROPERTY_TYPE: Schema.TYPE_MECHANICAL,
            Schema.STRENGTH_GROUPS: strength_groups,
        })

        # chemical
        chem_props = []
        chem = self.data.get(Schema.CHEMICAL)
        if isinstance(chem, dict):
            comps = chem.get(Schema.COMPOSITION) or []
            if isinstance(comps, list):
                for comp in comps:
                    if isinstance(comp, dict):
                        chem_props.append({
                            Schema.PROP_NAME: Schema.COMPOSITION,
                            Schema.DATA: dict(comp),
                        })
        groups.append({Schema.PROPERTY_TYPE: Schema.TYPE_CHEMICAL, Schema.PROPERTIES: chem_props})

        self.data[Schema.PROPERTY_GROUPS] = groups
        self._drop_legacy_roots()

    @staticmethod
    def _normalize_legacy_category(cat):
        name = cat.get(Schema.STRENGTH_CAT) or cat.get(Schema.VAL_STR_CAT) or ""
        out = {
            Schema.STRENGTH_CAT: name,
            "comment": cat.get("comment", ""),
            Schema.PROPERTIES: [],
        }
        if cat.get(Schema.REF_ID):
            out[Schema.REF_ID] = cat[Schema.REF_ID]
        if cat.get("property_subsource"):
            out["property_subsource"] = cat["property_subsource"]
        if cat.get("property_source"):
            out["property_source"] = cat["property_source"]

        props = []
        # already new-ish properties list
        if isinstance(cat.get(Schema.PROPERTIES), list):
            for item in cat[Schema.PROPERTIES]:
                if not isinstance(item, dict):
                    continue
                pname = item.get(Schema.PROP_NAME) or item.get("property_id")
                if not pname:
                    continue
                if isinstance(item.get(Schema.DATA), dict):
                    props.append({Schema.PROP_NAME: pname, Schema.DATA: dict(item[Schema.DATA])})
                elif pname == Schema.HARDNESS and isinstance(item.get("values"), list):
                    props.append({
                        Schema.PROP_NAME: Schema.HARDNESS,
                        Schema.DATA: {
                            Schema.HARDNESS_VALUES: item["values"],
                            Schema.HARDNESS_UNIT: item.get("property_unit") or item.get("value_unit") or "HB",
                            "comment": item.get("comment", ""),
                        },
                    })
                else:
                    data = {k: v for k, v in item.items() if k not in (Schema.PROP_NAME, "property_id")}
                    if pname == Schema.HARDNESS and Schema.HARDNESS_VALUES not in data and "values" in data:
                        data[Schema.HARDNESS_VALUES] = data.pop("values")
                    props.append({Schema.PROP_NAME: pname, Schema.DATA: data})
        else:
            reserved = {
                Schema.STRENGTH_CAT, Schema.VAL_STR_CAT, Schema.PROPERTIES, Schema.REF_ID,
                Schema.HARDNESS_UNIT, "comment", "property_source", "property_subsource",
            }
            if isinstance(cat.get(Schema.HARDNESS), list):
                unit = cat.get(Schema.HARDNESS_UNIT) or (
                    cat[Schema.HARDNESS][0].get("unit_value") if cat[Schema.HARDNESS] else "HB"
                ) or "HB"
                props.append({
                    Schema.PROP_NAME: Schema.HARDNESS,
                    Schema.DATA: {
                        Schema.HARDNESS_VALUES: cat[Schema.HARDNESS],
                        Schema.HARDNESS_UNIT: unit,
                        "comment": "",
                    },
                })
            for key, val in cat.items():
                if key in reserved or key == Schema.HARDNESS:
                    continue
                if isinstance(val, dict) and (
                    Schema.TEMP_PAIRS in val or "property_name" in val or "value_unit" in val
                ):
                    props.append({Schema.PROP_NAME: key, Schema.DATA: dict(val)})

        out[Schema.PROPERTIES] = props
        return out

    def _drop_legacy_roots(self):
        for key in (Schema.PHYSICAL, Schema.MECHANICAL, Schema.CHEMICAL):
            self.data.pop(key, None)

    def save(self, filepath=None):
        save_path = filepath or self.filepath
        if not save_path:
            raise ValueError("Путь не указан")
        self.filepath = save_path
        self.filename = os.path.basename(save_path)
        self.normalize_schema()
        now = datetime.now().isoformat()

        for entry in self.get_physical_properties_list():
            data = self.get_prop_data(entry)
            if data is not None:
                data["property_last_updated"] = now

        for cat in self.get_strength_categories():
            for entry in cat.get(Schema.PROPERTIES) or []:
                data = self.get_prop_data(entry)
                if data is not None:
                    data["property_last_updated"] = now

        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

class Schema:
    """Константы для ключей JSON структуры материала."""
    METADATA = "metadata"

    # Новая схема
    PROPERTY_GROUPS = "property_groups"
    PROPERTY_TYPE = "property_type"
    PROP_NAME = "property_name"  # id свойства (density, yield_strength, …)
    DATA = "data"
    PROPERTIES = "properties"
    STRENGTH_GROUPS = "strength_groups"
    HARDNESS_VALUES = "hardness_values"
    HARDNESS_UNIT = "hardness_unit"
    HARDNESS = "hardness"

    TYPE_PHYSICAL = "physical"
    TYPE_MECHANICAL = "mechanical"
    TYPE_CHEMICAL = "chemical"

    # Legacy-ключи (для миграции / аудита вкладок)
    PHYSICAL = "physical_properties"
    MECHANICAL = "mechanical_properties"
    CHEMICAL = "chemical_properties"

    # Вложенные ключи
    STRENGTH_CAT = "strength_category"  # имя КП в strength_groups
    COMPOSITION = "composition"
    TEMP_PAIRS = "temperature_value_pairs"
    APP_AREA = "application_area"
    NAME_STD = "name_material_standard"
    NAME_ALT = "name_material_alternative"

    # Поля значений
    REF_ID = "source_ref_id"
    # legacy имя КП
    VAL_STR_CAT = "value_strength_category"

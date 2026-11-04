import pytest

from src.services.hardness_table import HardnessTable


@pytest.fixture
def hardness_table():
    return HardnessTable()


def test_json_load(hardness_table):
    """
    Сценарий: HardnessTable() создаётся без исключения
    Ожидание: объект создан
    """
    assert hardness_table is not None


def test_column_names(hardness_table):
    """
    Сценарий: column_names() возвращает 7 колонок
    Ожидание: d10 … HSD
    """
    assert hardness_table.column_names() == ["d10", "HB", "HRA", "HRC", "HRB", "HV", "HSD"]


def test_system_unit():
    """
    Сценарий: SYSTEM_UNIT
    Ожидание: "HB"
    """
    assert HardnessTable.SYSTEM_UNIT == "HB"


def test_supported_unit(hardness_table):
    """
    Сценарий: is_supported_unit("HB")
    Ожидание: True
    """
    assert hardness_table.is_supported_unit("HB") is True


def test_not_supported_unit(hardness_table):
    """
    Сценарий: is_supported_unit("Brinell")
    Ожидание: False
    """
    assert hardness_table.is_supported_unit("Brinell") is False


def test_identity_int(hardness_table):
    """
    Сценарий: convert той же единицы (целое)
    Вход: value=200, from=HB, to=HB
    Ожидание: 200.0
    """
    assert hardness_table.convert(200, "HB", "HB") == 200.0


def test_identity_float(hardness_table):
    """
    Сценарий: convert той же единицы (дробное)
    Вход: value=653.0, from=HB, to=HB
    Ожидание: 653.0
    """
    assert hardness_table.convert(653.0, "HB", "HB") == 653.0


def test_HB_to_HRC(hardness_table):
    """
    Сценарий: точное совпадение со строкой таблицы HB → HRC
    Эталон: config/hardness_table.json, HB=653, HRC=62.9
    Вход: value=653, from=HB, to=HRC
    Ожидание: 62.9
    """
    assert hardness_table.convert(653, "HB", "HRC") == 62.9


def test_HB_to_HV(hardness_table):
    """
    Сценарий: точное совпадение со строкой таблицы HB → HV
    Эталон: config/hardness_table.json, HB=653, HV=866
    Вход: value=653, from=HB, to=HV
    Ожидание: 866
    """
    assert hardness_table.convert(653, "HB", "HV") == 866


def test_HRC_to_HB(hardness_table):
    """
    Сценарий: обратный перевод HRC → HB
    Эталон: config/hardness_table.json, HRC=62.9, HB=653
    Вход: value=62.9, from=HRC, to=HB
    Ожидание: 653.0
    """
    assert hardness_table.convert(62.9, "HRC", "HB") == 653.0


def test_interpolate_HB_to_HRC(hardness_table):
    """
    Сценарий: интерполяция между строками HB → HRC
    Эталон: между HB=653/HRC=62.9 и HB=648/HRC=62.5
    Вход: value=650.5, from=HB, to=HRC
    Ожидание: ≈ 62.7
    """
    assert hardness_table.convert(650.5, "HB", "HRC") == pytest.approx(62.7, abs=0.01)


def test_lower_than_HB(hardness_table):
    """
    Сценарий: значение ниже min диапазона HB→HRC (без экстраполяции)
    Вход: value=74, from=HB, to=HRC
    Ожидание: None
    """
    assert hardness_table.convert(74, "HB", "HRC") is None


def test_higher_than_HB(hardness_table):
    """
    Сценарий: значение выше max диапазона HB→HRC (без экстраполяции)
    Вход: value=800, from=HB, to=HRC
    Ожидание: None
    """
    assert hardness_table.convert(800, "HB", "HRC") is None


def test_value_is_None(hardness_table):
    """
    Сценарий: value is None
    Вход: value=None, from=HB, to=HRC
    Ожидание: None
    """
    assert hardness_table.convert(None, "HB", "HRC") is None


def test_unfamiliar_from(hardness_table):
    """
    Сценарий: неизвестная from_unit
    Вход: value=200, from=XXX, to=HRC
    Ожидание: None
    """
    assert hardness_table.convert(200, "XXX", "HRC") is None


def test_unfamiliar_to(hardness_table):
    """
    Сценарий: неизвестная to_unit
    Вход: value=200, from=HB, to=YYY
    Ожидание: None
    """
    assert hardness_table.convert(200, "HB", "YYY") is None


def test_null_in_table(hardness_table):
    """
    Сценарий: HB → HRB на высокой твёрдости (в строке HRB=null)
    Эталон: config/hardness_table.json, HB=653, HRB=null
    Вход: value=653, from=HB, to=HRB
    Ожидание: None
    """
    assert hardness_table.convert(653, "HB", "HRB") is None

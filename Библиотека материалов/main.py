# main.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import subprocess
import uuid
import copy
import sys
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import Ellipse, Patch
import colorsys

from src.services.properties_catalog import PropertiesCatalog
from src.core.schema_keys import Schema
from src.core.models.material import Material
from src.core.math.interpolation import MathUtils
from src.infrastructure.paths import get_app_directory
from src.services.hardness_table import HardnessTable
from src.services.source_service import SourceService
from src.services.material_repository import MaterialRepository

# ======================================================================================
# БЛОК 1: КОНФИГУРАЦИЯ И КОНСТАНТЫ
# ======================================================================================

# Константа для логов
LOG_FILENAME = "material_changelog.txt"

# ======================================================================================
# АУДИТ: единый словарь нормализованных event_name
# ======================================================================================
# Важно: аналитика использует event.name + event.category + event.action.
# Поэтому event.name делаем стабильным, а старт/финиш/ошибки различаем через event.action/result/metrics.
AUDIT_EVENT_NAMES = {
    # Материалы
    "MATERIAL_SELECTED": "Материал: выбран",
    "MATERIAL_CREATE_DRAFT": "Материал: создан новый (черновик)",
    "MATERIAL_SAVE": "Материал: сохранение",
    "MATERIAL_SAVE_TAB": "Материал: изменения по вкладке",
    "MATERIAL_SAVE_AS": "Материал: сохранить как",
    "MATERIAL_RESET_CREATE": "Материал: создание сброшено",
    "MATERIAL_CANCEL_CHANGES": "Материал: изменения отменены",

    # Источники
    "SOURCE_SELECTED": "Источник: выбран",
    "SOURCE_CREATE": "Источник: создание",
    "SOURCE_UPDATE": "Источник: изменение",
    "SOURCE_DELETE": "Источник: удаление",
    "SOURCE_OPEN_LINK": "Источник: открыть ссылку",

    # Навигация
    "NAV_TAB_SELECTED": "Навигация: вкладка выбрана",

    # Импорт
    "IMPORT_OPEN_DIR": "Импорт: открыть директорию",
    "IMPORT_OPEN_DIR_ERROR": "Импорт: ошибка открытия директории",

    # Справка
    "HELP_ABOUT_OPEN": "Справка: о приложении открыто",
    "HELP_INSTRUCTIONS_OPEN": "Справка: инструкция открыта",
    "HELP_CHANGELOG_OPEN": "Справка: список изменений открыт",
}

PROPERTIES = PropertiesCatalog()
PHYSICAL_MAP = {k: PROPERTIES.get_meta(k) for k in PROPERTIES.physical_keys()}
MECHANICAL_MAP = {k: PROPERTIES.get_meta(k) for k in PROPERTIES.mechanical_keys()}
ALL_PROPERTIES_MAP = {**PHYSICAL_MAP, **MECHANICAL_MAP}
HARDNESS = HardnessTable()

# Константа для сравнения списков (для логов)
LIST_ITEM_KEYS = {
    (Schema.PROPERTY_GROUPS,): Schema.PROPERTY_TYPE,
    (Schema.MECHANICAL, Schema.STRENGTH_CAT): Schema.VAL_STR_CAT,  # legacy
}


def find_changes(old_data, new_data):
    """
    Главная функция для поиска изменений. Подготавливает данные и вызывает рекурсивный хелпер.
    Возвращает структурированный список изменений.
    """

    def list_item_key_for_path(path):
        key = LIST_ITEM_KEYS.get(tuple(path))
        if key:
            return key
        if not path:
            return None
        last = str(path[-1])
        if last == Schema.PROPERTIES:
            return Schema.PROP_NAME
        if last == Schema.STRENGTH_GROUPS:
            return Schema.STRENGTH_CAT
        if last == "other_elements":
            return "element"
        if last == Schema.HARDNESS_VALUES:
            return None
        if last == Schema.COMPOSITION:
            return "composition_source"
        return None

    def find_changes_recursive(d1, d2, path):
        changes = []
        if isinstance(d1, dict) and isinstance(d2, dict):
            all_keys = sorted(list(set(d1.keys()) | set(d2.keys())))
            for key in all_keys:
                if key in ["material_id", "property_last_updated"]: continue
                new_path = path + [key]
                val1, val2 = d1.get(key), d2.get(key)
                if val1 is None and val2 is not None:
                    changes.append({'path': new_path, 'type': 'added', 'new': val2})
                elif val1 is not None and val2 is None:
                    changes.append({'path': new_path, 'type': 'removed', 'old': val1})
                elif val1 != val2:
                    changes.extend(find_changes_recursive(val1, val2, new_path))
        elif isinstance(d1, list) and isinstance(d2, list):
            unique_key_name = list_item_key_for_path(path)
            is_list_of_dicts_with_key = (unique_key_name and
                                         all(isinstance(item, dict) and unique_key_name in item for item in d1 + d2))
            if is_list_of_dicts_with_key:
                old_map = {item[unique_key_name]: item for item in d1}
                new_map = {item[unique_key_name]: item for item in d2}
                all_item_keys = sorted(list(set(old_map.keys()) | set(new_map.keys())))
                for item_key in all_item_keys:
                    old_item = old_map.get(item_key)
                    new_item = new_map.get(item_key)
                    item_path = path + [f"{path[-1]}[{item_key}]"]
                    if old_item is None:
                        changes.append({'path': item_path, 'type': 'added', 'new': new_item})
                    elif new_item is None:
                        changes.append({'path': item_path, 'type': 'removed', 'old': old_item})
                    elif old_item != new_item:
                        changes.extend(find_changes_recursive(old_item, new_item, item_path))
            else:
                if json.dumps(d1, sort_keys=True) != json.dumps(d2, sort_keys=True):
                    changes.append({'path': path, 'type': 'modified', 'old': d1, 'new': d2})
        elif d1 != d2:
            changes.append({'path': path, 'type': 'modified', 'old': d1, 'new': d2})
        return changes

    return find_changes_recursive(copy.deepcopy(old_data), copy.deepcopy(new_data), [])


# ======================================================================================
# БЛОК 2: УТИЛИТЫ
# ======================================================================================

def get_username():
    try:
        return os.getlogin()
    except Exception:
        return os.environ.get("USERNAME", "unknown_user")


def read_text_from_file(filename):
    embedded = {"app_list.txt": APP_TEXT, "instruction_list.txt": INSTR_TEXT, "change_list.txt": CHANGELOG_TEXT}
    return embedded.get(filename, f"ОШИБКА: Не удалось прочитать '{filename}'")


# Порядок вкладок редактора для аудита (отдельная строка JSON на каждую с изменениями)
EDITOR_AUDIT_TAB_ORDER = (
    "Общие данные",
    "Физические свойства",
    "Механические свойства",
    "Химический состав",
    "Прочее",
)


def _audit_editor_tab_for_path(path):
    """Определяет вкладку редактора по пути diff (первый сегмент корня JSON)."""
    if not path:
        return None
    root = str(path[0])
    if root == Schema.METADATA:
        return "Общие данные"
    if root == Schema.PROPERTY_GROUPS:
        joined = " ".join(str(x) for x in path)
        if f"{Schema.PROPERTY_TYPE}[{Schema.TYPE_PHYSICAL}]" in joined or "property_groups[physical]" in joined:
            return "Физические свойства"
        if f"{Schema.PROPERTY_TYPE}[{Schema.TYPE_MECHANICAL}]" in joined or "property_groups[mechanical]" in joined:
            return "Механические свойства"
        if f"{Schema.PROPERTY_TYPE}[{Schema.TYPE_CHEMICAL}]" in joined or "property_groups[chemical]" in joined:
            return "Химический состав"
        # fallback по вхождениям типов в сегментах
        for seg in path:
            s = str(seg)
            if Schema.TYPE_PHYSICAL in s:
                return "Физические свойства"
            if Schema.TYPE_MECHANICAL in s or Schema.STRENGTH_GROUPS in s:
                return "Механические свойства"
            if Schema.TYPE_CHEMICAL in s or Schema.COMPOSITION in s:
                return "Химический состав"
        return "Прочее"
    if root == Schema.PHYSICAL:
        return "Физические свойства"
    if root == Schema.MECHANICAL:
        return "Механические свойства"
    if root == Schema.CHEMICAL:
        return "Химический состав"
    return "Прочее"


def _audit_metadata_human_label(segments):
    """Человекочитаемая подпись поля для вкладки «Общие данные»."""
    if not segments:
        return "Общие данные (metadata)"
    k0 = str(segments[0])
    if k0 == Schema.NAME_STD:
        return "Наименование (стандарт)"
    if k0 == Schema.NAME_ALT:
        return "Альтернативные названия"
    if k0 == "comment":
        return "Общий комментарий"
    if k0 == Schema.APP_AREA:
        return "Области применения"
    if k0 == "classification" and len(segments) >= 2:
        sub = str(segments[1])
        sub_map = {
            "classification_category": "Классификация: категория",
            "classification_class": "Классификация: структурный класс",
            "classification_subclass": "Классификация: подкласс",
        }
        return sub_map.get(sub, f"Классификация: {sub}")
    if k0 == "classification":
        return "Классификация"
    if k0 == "temperature_application":
        if len(segments) >= 2:
            sub = str(segments[1])
            if sub == "value":
                return "Температура применения ДО (значение)"
            if sub == "comment":
                return "Комментарий к температуре применения"
        return "Параметры применения (температура)"
    return f"Общие данные: {k0}"


def _audit_prop_name_from_segment(seg):
    s = str(seg)
    for prefix in (f"{Schema.PROPERTIES}[", f"{Schema.STRENGTH_GROUPS}[", f"{Schema.PROPERTY_GROUPS}["):
        if s.startswith(prefix) and s.endswith("]"):
            return s[len(prefix):-1]
    return None


def _audit_physical_human_label(segments):
    for seg in segments:
        sk = str(seg)
        prop_id = _audit_prop_name_from_segment(sk) or sk
        if prop_id.startswith(f"{Schema.PROP_NAME}=") or False:
            pass
        # properties[density] → density; или сегмент data после properties[density]
        if PROPERTIES.is_physical(prop_id):
            return PROPERTIES.get_meta(prop_id)["name"]
        if sk.startswith(f"{Schema.PROPERTIES}[") and sk.endswith("]"):
            pid = sk[len(f"{Schema.PROPERTIES}["):-1]
            if PROPERTIES.is_physical(pid):
                return PROPERTIES.get_meta(pid)["name"]
    return "Физическое свойство"


_MECH_CAT_FIELD_LABELS = {
    Schema.HARDNESS_UNIT: "Единица твердости (КП)",
    "hardness_unit": "Единица твердости (КП)",
    Schema.STRENGTH_CAT: "Наименование категории прочности",
    Schema.VAL_STR_CAT: "Наименование категории прочности",
    Schema.HARDNESS: "Твердость",
}


def _audit_mechanical_human_label(segments):
    kp = None
    for seg in segments:
        s = str(seg)
        if s.startswith(f"{Schema.STRENGTH_GROUPS}[") and s.endswith("]"):
            kp = s[len(f"{Schema.STRENGTH_GROUPS}["):-1]
        if s.startswith(f"{Schema.STRENGTH_CAT}[") and s.endswith("]"):
            kp = s[len(f"{Schema.STRENGTH_CAT}["):-1]
    for seg in segments:
        s = str(seg)
        prop_id = s
        if s.startswith(f"{Schema.PROPERTIES}[") and s.endswith("]"):
            prop_id = s[len(f"{Schema.PROPERTIES}["):-1]
        if prop_id == Schema.HARDNESS or PROPERTIES.is_mechanical(prop_id):
            name = "Твердость" if prop_id == Schema.HARDNESS else PROPERTIES.get_meta(prop_id)["name"]
            if kp is not None and str(kp).strip() not in ("", "-1", "-"):
                return f"КП «{kp}»: {name}"
            return name
    for seg in segments:
        s = str(seg)
        if s in _MECH_CAT_FIELD_LABELS:
            base = _MECH_CAT_FIELD_LABELS[s]
            if kp is not None and str(kp).strip() not in ("", "-1", "-"):
                return f"КП «{kp}»: {base}"
            return base
    return "Механическое свойство (КП)"


def _audit_chemical_human_label(segments):
    str_segs = [str(x) for x in segments]
    elem = None
    for x in str_segs:
        if x.startswith("other_elements[") and x.endswith("]"):
            elem = x[len("other_elements["):-1]
    for seg in str_segs:
        if seg.startswith(f"{Schema.COMPOSITION}[") and seg.endswith("]"):
            src = seg[len(f"{Schema.COMPOSITION}["):-1]
            if "other_elements" in str_segs:
                if elem:
                    return f"Состав ({src}): элемент {elem}"
                return f"Состав ({src}): прочие элементы"
            return f"Состав ({src})"
    if Schema.COMPOSITION in str_segs:
        return "Состав (структура)"
    return "Химический состав"


def _audit_human_field_label(path):
    """Краткая подпись изменённого поля без значений."""
    if not path:
        return "неизвестно"
    p0 = str(path[0])
    if p0 == Schema.METADATA:
        return _audit_metadata_human_label(path[1:])
    if p0 == Schema.PROPERTY_GROUPS:
        joined = " ".join(str(x) for x in path)
        if Schema.TYPE_PHYSICAL in joined or "property_groups[physical]" in joined:
            return _audit_physical_human_label(path[1:])
        if Schema.TYPE_MECHANICAL in joined or Schema.STRENGTH_GROUPS in joined or "property_groups[mechanical]" in joined:
            return _audit_mechanical_human_label(path[1:])
        if Schema.TYPE_CHEMICAL in joined or "property_groups[chemical]" in joined:
            return _audit_chemical_human_label(path[1:])
        return _audit_physical_human_label(path[1:])
    if p0 == Schema.PHYSICAL:
        return _audit_physical_human_label(path[1:])
    if p0 == Schema.MECHANICAL:
        return _audit_mechanical_human_label(path[1:])
    if p0 == Schema.CHEMICAL:
        return _audit_chemical_human_label(path[1:])
    return str(path[-1])


def group_editor_changes_by_tab(changes):
    """
    Группирует find_changes() по вкладкам редактора.
    Возвращает dict: вкладка -> отсортированный список уникальных подписей полей.
    """
    buckets = {tab: set() for tab in EDITOR_AUDIT_TAB_ORDER}
    if not changes:
        return {}
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        path = ch.get("path")
        if not isinstance(path, list) or not path:
            continue
        tab = _audit_editor_tab_for_path(path)
        if tab not in buckets:
            tab = "Прочее"
        label = _audit_human_field_label(path)
        buckets[tab].add(label)
    return {tab: sorted(buckets[tab]) for tab in EDITOR_AUDIT_TAB_ORDER if buckets[tab]}


def log_changes(material_name, changes_list):
    """Записывает изменения в лог-файл в иерархическом виде."""
    if not changes_list: return
    log_path = os.path.join(get_app_directory(), LOG_FILENAME)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = get_username()
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"Время: {timestamp}\n")
            f.write(f"Пользователь: {username}\n")
            f.write(f"Материал: {material_name}\n")
            f.write("Изменения:\n")
            printed_headers = set()
            for change in changes_list:
                path = change['path']
                for i in range(len(path) - 1):
                    header_path_tuple = tuple(path[:i + 1])
                    if header_path_tuple not in printed_headers:
                        indent = "  " * (i + 1)
                        header_name = path[i]
                        if isinstance(header_name, int): f.write(f"{indent}Изменения в элементе с индексом [{header_name}]:\n")
                        else: f.write(f"{indent}Изменения в '{header_name}':\n")
                        printed_headers.add(header_path_tuple)
                leaf_key = path[-1]
                indent = "  " * len(path)
                ct = change['type']
                if ct == 'modified': f.write(f"{indent}- '{leaf_key}': [БЫЛО] '{change['old']}' -> [СТАЛО] '{change['new']}'\n")
                elif ct == 'added': f.write(f"{indent}- '{leaf_key}': [ДОБАВЛЕНО] -> '{change['new']}'\n")
                elif ct == 'removed': f.write(f"{indent}- '{leaf_key}': [УДАЛЕНО] (было '{change['old']}')\n")
            f.write("\n")
    except Exception as e:
        print(f"Ошибка записи в лог-файл: {e}")


def safe_float(value, default=None):
    """
    Безопасное преобразование строки в float.
    Меняет запятую на точку. Возвращает default при ошибке.
    """
    if value is None: return default
    if isinstance(value, (float, int)): return float(value)
    try:
        # Убираем пробелы и меняем запятую на точку
        return float(str(value).strip().replace(',', '.'))
    except (ValueError, TypeError):
        return default


class ScrollableMixin:
    """Миксин для прокрутки колесом мыши."""
    def bind_mouse_wheel(self, widget, target_widget=None):
        target = target_widget if target_widget else widget
        def _on_mousewheel(event):
            if isinstance(event.widget, ttk.Combobox): pass
            if hasattr(event, 'delta') and event.delta != 0:
                target.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif hasattr(event, 'num'):
                if event.num == 4: target.yview_scroll(-1, "units")
                elif event.num == 5: target.yview_scroll(1, "units")
            return "break"
        widget.bind("<MouseWheel>", _on_mousewheel)
        widget.bind("<Button-4>", _on_mousewheel)
        widget.bind("<Button-5>", _on_mousewheel)

    def bind_all_children(self, parent_widget, target_canvas):
        self.bind_mouse_wheel(parent_widget, target_canvas)
        for child in parent_widget.winfo_children():
            self.bind_all_children(child, target_canvas)


# ======================================================================================
# БЛОК 3: БИЗНЕС-ЛОГИКА (CORE)
# ======================================================================================


class UnitManager:
    """
    Менеджер единиц измерения.
    Архитектура:
    1. У каждого типа есть одна SYSTEM_UNIT (Закон проекта).
    2. factors хранит коэффициент перевода: ИЗ Единицы -> В System_Unit.
       Пример: Pressure System = кгс/см2.
       Factor для МПа = 10.197162 (т.е. 1 МПа * 10.197 = Значение в кгс/см2).
    """

    REGISTRY = {
        "Давление": {
            "system_unit": "кгс/см2",
            "factors": {
                "кгс/см2": 1.0,
                "МПа": 10.197162,
                "бар": 1.019716,
                "Па": 1.019716e-5,
                "кПа": 0.010197,
                "мм рт.ст.": 0.0013595,
                "мм вод.ст.": 0.0001,
                "атм": 1.033227,
                "psi": 0.070307,
                "ksi": 70.3069
            }
        },
        "Температура": {
            "system_unit": "C",
            "factors": {
                "C": 1.0,
                "K": "offset_k",  # Спец. обработка
                "F": "offset_f"   # Спец. обработка
            }
        },
        "Расход": {
            "system_unit": "т/ч",
            "factors": {
                "т/ч": 1.0,
                "кг/с": 3.6,
                "кг/ч": 0.001,
                "т/с": 3600.0
            }
        },
        "Объемный расход": {
            "system_unit": "м3/ч",
            "factors": {
                "м3/ч": 1.0,
                "м3/с": 3600.0,
                "л/с": 3.6,
                "л/мин": 0.06,
                "л/ч": 0.001
            }
        },
        "Скорость": {
            "system_unit": "м/с",
            "factors": {
                "м/с": 1.0,
                "км/ч": 0.277778,
                "узлы": 0.514444
            }
        },
        "Плотность": {
            "system_unit": "кг/м3",
            "factors": {
                "кг/м3": 1.0,
                "г/см3": 1000.0,
                "т/м3": 1000.0
            }
        },
        "Удельный объем": {
            "system_unit": "м3/кг",
            "factors": {
                "м3/кг": 1.0,
                "см3/г": 0.001,
                "л/кг": 0.001,
                "ft3/lb": 0.062428
            }
        },
        "Вязкость дин.": {
            "system_unit": "кг/(м*с)",
            "factors": {
                "кг/(м*с)": 1.0,
                "Па*с": 1.0,
                "Пуаз": 0.1,
                "сП": 0.001
            }
        },
        "Вязкость кин.": {
            "system_unit": "м2/с",
            "factors": {
                "м2/с": 1.0,
                "сСт": 1e-6,
                "Ст": 1e-4
            }
        },
        "Энтальпия": {
            "system_unit": "ккал/кг",
            "factors": {
                "ккал/кг": 1.0,
                "кал/кг": 0.001,
                "кДж/кг": 0.238846,
                "Дж/кг": 0.0002388
            }
        },
        "Энтропия": {
            "system_unit": "ккал/(кг*С)",
            "factors": {
                "ккал/(кг*С)": 1.0,
                "кал/(кг*С)": 0.001,
                "кДж/(кг*К)": 0.238846,
                "кДж/(кг*С)": 0.238846,
                "Дж/(кг*К)": 0.0002388
            }
        },
        "Степень сухости": {
            "system_unit": "-",
            "factors": {
                "-": 1.0,
                "%": 0.01
            }
        },
        "Удельная теплоемкость": {
            "system_unit": "ккал/(кг*С)",
            "factors": {
                "ккал/(кг*С)": 1.0,
                "кДж/(кг*К)": 0.238846,
                "кДж/(кг*С)": 0.238846,
                "Дж/(кг*К)": 0.0002388,
                "Дж/(кг*С)": 0.0002388
            }
        },
        "Теплопроводность": {
            "system_unit": "Вт/(м*К)",
            "factors": {
                "Вт/(м*К)": 1.0,
                "ккал/(ч*м*С)": 1.163
            }
        },
        "Мощность": {
            "system_unit": "МВт",
            "factors": {
                "МВт": 1.0,
                "кВт": 0.001,
                "Вт": 1e-6,
                "ГВт": 1000.0,
                "Гкал/ч": 1.163,
                "ккал/ч": 1.163e-6,
                "л.с.": 7.35499e-4
            }
        },
        "Энергия": {
            "system_unit": "Гкал",
            "factors": {
                "Гкал": 1.0,
                "ккал": 1e-6,
                "МВт*ч": 0.859845,
                "кВт*ч": 0.0008598,
                "ГДж": 0.238846,
                "кДж": 2.388e-7
            }
        },
        "Сила": {
            "system_unit": "Н",
            "factors": {
                "Н": 1.0,
                "кН": 1000.0,
                "кгс": 9.80665,
                "lbf": 4.44822,
                "дина": 1e-5
            }
        },
        "Момент силы": {
            "system_unit": "Н*м",
            "factors": {
                "Н*м": 1.0,
                "кгс*м": 9.80665,
                "кН*м": 1000.0
            }
        },
        "Частота": {
            "system_unit": "Гц",
            "factors": {
                "Гц": 1.0,
                "кГц": 1000.0,
                "МГц": 1000000.0,
                "об/с": 1.0,
                "об/мин": 0.0166667
            }
        },
        "Теплоотдача": {
            "system_unit": "Вт/(м2*К)",
            "factors": {
                "Вт/(м2*К)": 1.0,
                "Вт/(м2*С)": 1.0
            }
        },
        "Длина": {
            "system_unit": "мм",
            "factors": {
                "км": 1000000,
                "м": 1000,
                "дм": 100,
                "см": 10,
                "мм": 1,
                "мкм": 0.001,
                "микрон": 0.001,
                "св.лет": 9460000000000000000.00,
                "вершки": 44.45,
                "пяди": 177.8,
                "аршины": 711.2,
                "сажени": 2133.6,
                "версты": 1066800,
                "дюймы": 25.4,
                "футы": 304.8,
                "ярды": 914.4,
                "мили": 1609344,
                "лье": 5556000
            }
        },
        "Площадь": {
            "system_unit": "м2",
            "factors": {
                "см2": 0.0001,
                "м2": 1,
                "сотки": 100,
                "Га": 10000,
                "акры": 4046.86
            }
        },
        "Объем": {
            "system_unit": "м3",
            "factors": {
                "м3": 1.0,
                "л": 0.001,
                "мл": 1e-6,
                "см3": 1e-6,
                "баррель": 0.158987,
                "галлон (US)": 0.00378541,
                "фут3": 0.0283168
            }
        },
        "Масса": {
            "system_unit": "кг",
            "factors": {
                "тонны": 1000,
                "центнер": 100,
                "кг": 1,
                "грамм": 0.001,
                "унции": 0.02835,
                "lb": 0.453592
            }
        },
        "Время": {
            "system_unit": "с",
            "factors": {
                "с": 1.0,
                "мин": 60.0,
                "ч": 3600.0,
                "сутки": 86400.0,
                "год": 31536000.0
            }
        },
        "Угол": {
            "system_unit": "град",
            "factors": {
                "град": 1,
                "радианы": 57.3
            }
        },
        "Безразмерный": {
            "system_unit": "-",
            "factors": {
                "-": 1.0,
                "%": 0.01
            }
        },
        "Твердость": {
            "system_unit": "HB",
            "factors": {
                "HB": 1.0,
                "HRA": "table",
                "HRC": "table",
                "HRB": "table",
                "HV": "table",
                "HSD": "table"
            }
        },
        "Декремент колебаний": {
            "system_unit": "-",
            "factors": {
                "-": 1.0,
                "%": 0.01,
                "Np": 1.0,
                "dB": 0.1151
            }
        },
        "Предел ползучести": {
            "system_unit": "МПа",
            "factors": {
                "МПа": 1.0,
                "Па": 1e-6,
                "кПа": 0.001,
                "ГПа": 1000.0,
                "кгс/мм2": 9.80665,
                "кгс/см2": 0.0980665,
                "бар": 0.1,
                "psi": 0.00689476,
                "ksi": 6.89476,
                "N/mm2": 1.0
            }
        },
        "Предел прочности": {
            "system_unit": "МПа",
            "factors": {
                "МПа": 1.0,
                "Па": 1e-6,
                "кПа": 0.001,
                "ГПа": 1000.0,
                "кгс/мм2": 9.80665,
                "кгс/см2": 0.0980665,
                "бар": 0.1,
                "psi": 0.00689476,
                "ksi": 6.89476,
                "N/mm2": 1.0
            }
        },
        "Предел длит. прочности": {
            "system_unit": "МПа",
            "factors": {
                "МПа": 1.0,
                "Па": 1e-6,
                "кПа": 0.001,
                "ГПа": 1000.0,
                "кгс/мм2": 9.80665,
                "кгс/см2": 0.0980665,
                "бар": 0.1,
                "psi": 0.00689476,
                "ksi": 6.89476,
                "N/mm2": 1.0,
                "tsf": 0.09576,
                "тс/м2": 0.00980665
            }
        },
        "Предел текучести": {
            "system_unit": "МПа",
            "factors": {
                "МПа": 1.0,
                "Па": 1e-6,
                "кПа": 0.001,
                "ГПа": 1000.0,
                "кгс/мм2": 9.80665,
                "кгс/см2": 0.0980665,
                "бар": 0.1,
                "psi": 0.00689476,
                "ksi": 6.89476,
                "N/mm2": 1.0
            }
        },
        "Предел выносливости": {
            "system_unit": "МПа",
            "factors": {
                "МПа": 1.0,
                "Па": 1e-6,
                "кПа": 0.001,
                "ГПа": 1000.0,
                "кгс/мм2": 9.80665,
                "кгс/см2": 0.0980665,
                "бар": 0.1,
                "psi": 0.00689476,
                "ksi": 6.89476,
                "N/mm2": 1.0
            }
        },
        "Модуль упругости": {
            "system_unit": "МПа",
            "factors": {
                "МПа": 1.0,
                "ГПа": 1000.0,
                "Па": 1e-6,
                "кгс/мм2": 9.80665,
                "кгс/см2": 0.0980665,
                "psi": 0.00689476,
                "ksi": 6.89476,
                "Mpsi": 6894.76,
                "N/mm2": 1.0
            }
        },
        "Ударная вязкость": {
            "system_unit": "кДж/м2",
            "factors": {
                "кДж/м2": 1.0,
                "Дж/м2": 0.001,
                "Дж/см2": 10.0,
                "кгс*м/см2": 98.0665,
                "кгс*м/м2": 0.00980665,
                "ft*lbf/in2": 2.1015
            }
        },
        "Коэфф. лин. расширения": {
            "system_unit": "1/С",
            "factors": {
                "1/С": 1.0,
                "1/K": 1.0,
                "1/F": 1.8,
                "мк/С": 1e-6,
                "10^-6/C": 1e-6,
                "10^-6/K": 1e-6,
                "10^-6/F": 1.8e-6
            }
        }
    }

    # Маппинг для библиотеки seuif97:
    # Какой тип данных ожидает библиотека и в какой единице (SI).
    # Это нужно для конвертации: System -> SI (для библиотеки).
    LIB_SI_TARGETS = {
        "Давление": "МПа",
        "Температура": "C",        # В seuif97 T в градусах Цельсия (или Кельвинах, но C удобнее)
        "Энтальпия": "кДж/кг",
        "Энтропия": "кДж/(кг*К)",
        "Удельный объем": "м3/кг",
        "Степень сухости": "-",
        "Плотность": "кг/м3",
        "Вязкость дин.": "Па*с",
        "Вязкость кин.": "м2/с",
        "Теплопроводность": "Вт/(м*К)",
        "Безразмерный": "-",
        "КПД": "-",                 # ief возвращает доли
    }

    # ==========================================
    # ТАБЛИЦА ПЕРЕВОДА ТВЕРДОСТИ
    # Сортировка: по возрастанию d10 (диаметр отпечатка)
    # Формат кортежа: (d10, HB, HRA, HRC, HRB, HV, HSD)
    # Если значения нет, стоит None.
    # ==========================================
    @staticmethod
    def get_system_unit(type_name):
        cfg = UnitManager.REGISTRY.get(type_name)
        return cfg["system_unit"] if cfg else ""

    @staticmethod
    def get_types():
        return list(UnitManager.REGISTRY.keys())

    @staticmethod
    def get_units(type_name):
        if type_name in UnitManager.REGISTRY:
            return list(UnitManager.REGISTRY[type_name]["factors"].keys())
        return []

    # --- ЛОГИКА ИНТЕРПОЛЯЦИИ ТВЕРДОСТИ (ИСПРАВЛЕННАЯ) ---


    # --- КОНВЕРТАЦИЯ В СИСТЕМНУЮ ЕДИНИЦУ (ВХОД) ---
    @staticmethod
    def to_system(value, from_unit, type_name):
        # 1. Спец. обработка для Твердости
        if type_name == "Твердость":
            system_unit = UnitManager.get_system_unit(type_name) # HB
            if from_unit == system_unit:
                return float(value)
            # Перевод: Единица -> HB (по таблице)
            res = HARDNESS.convert(float(value), from_unit, system_unit)
            return res if res is not None else 0.0

        # 2. Стандартная обработка
        cfg = UnitManager.REGISTRY.get(type_name)
        if not cfg: return value

        factor = cfg["factors"].get(from_unit)
        if factor is None: return value

        try:
            val = float(value)
        except:
            return 0.0

        if factor == "offset_k": return val - 273.15
        if factor == "offset_f": return (val - 32.0) * 5 / 9

        return val * factor

    # --- КОНВЕРТАЦИЯ ИЗ СИСТЕМНОЙ ЕДИНИЦЫ (ВЫХОД) ---
    @staticmethod
    def from_system(value, to_unit, type_name):
        # 1. Спец. обработка для Твердости
        if type_name == "Твердость":
            system_unit = UnitManager.get_system_unit(type_name) # HB
            if to_unit == system_unit:
                return float(value)
            # Перевод: HB -> Единица (по таблице)
            res = HARDNESS.convert(float(value), system_unit, to_unit)
            return res if res is not None else 0.0

        # 2. Стандартная обработка
        cfg = UnitManager.REGISTRY.get(type_name)
        if not cfg: return value

        factor = cfg["factors"].get(to_unit)
        if factor is None: return value

        try:
            val = float(value)
        except:
            return 0.0

        if factor == "offset_k": return val + 273.15
        if factor == "offset_f": return (val * 9 / 5) + 32.0

        return val / factor





# ======================================================================================
# БЛОК 4: UI HELPERS
# ======================================================================================


class CustomToolbar(NavigationToolbar2Tk):
    """
    Пользовательская панель инструментов, которая при нажатии 'Home'
    перерисовывает график, вызывая внешнюю функцию.
    """
    def __init__(self, canvas, window, plot_callback):
        super().__init__(canvas, window)
        # Сохраняем ссылку на нашу функцию для построения графика
        self.plot_callback = plot_callback

    def home(self, *args, **kwargs):
        """
        Переопределяем стандартное поведение кнопки 'Home'.
        Вместо сброса вида, мы полностью перерисовываем график.
        """
        # Вызываем нашу функцию, которая всё сделает сама
        self.plot_callback()


class Tooltip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip_window = None
        self.id = None
        self.widget.bind("<Enter>", self.schedule_tip)
        self.widget.bind("<Leave>", self.hide_tip)
    def schedule_tip(self, event=None):
        self.id = self.widget.after(self.delay, self.show_tip)
    def show_tip(self, event=None):
        if self.tip_window or not self.text: return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip_window, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("TkDefaultFont", 10, "normal"), wraplength=300)
        label.pack(ipadx=5, ipady=3)
    def hide_tip(self, event=None):
        if self.id: self.widget.after_cancel(self.id); self.id = None
        if self.tip_window: self.tip_window.destroy(); self.tip_window = None


def create_editable_treeview(parent_frame, on_update_callback=None):
    tree = ttk.Treeview(parent_frame)
    def on_tree_double_click(event):
        region = tree.identify("region", event.x, event.y)
        if region != "cell": return
        item_id = tree.focus()
        column = tree.identify_column(event.x)
        x, y, width, height = tree.bbox(item_id, column)
        entry_var = tk.StringVar()
        entry = ttk.Entry(tree, textvariable=entry_var)
        entry_var.set(tree.set(item_id, column))
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        entry.selection_range(0, tk.END)
        def on_focus_out(event):
            tree.set(item_id, column, entry_var.get())
            entry.destroy()
            if on_update_callback: on_update_callback()
        entry.bind("<FocusOut>", on_focus_out)
        entry.bind("<Return>", lambda e: on_focus_out(e))
    tree.bind("<Double-1>", on_tree_double_click)
    return tree


# ======================================================================================
# БЛОК 5: ВКЛАДКИ ПРОСМОТРА (VIEWER)
# ======================================================================================


class TempSelectionTab(ttk.Frame, ScrollableMixin):
    """Вкладка 'Подбор по температуре' с фиксированными колонками и синхронным скроллом."""

    def __init__(self, parent, app_data, main_app=None):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app
        self.treeview_data = []
        self.column_units = {}
        self.PROP_TYPES = ["Физические свойства", "Механические свойства", "Твердость"]
        self.PROPERTY_COLUMN_WIDTH = 100
        self.HARDNESS_COLUMNS = {
            "min_value": {"name": "Min", "width": self.PROPERTY_COLUMN_WIDTH, "unit_type": "Твердость"},
            "max_value": {"name": "Max", "width": self.PROPERTY_COLUMN_WIDTH, "unit_type": "Твердость"},
            # Для заголовка "Ед. изм." тоже задаем тип единиц "Твердость",
            # чтобы по ПКМ вызывать меню выбора единиц.
            "unit_value": {"name": "Ед. изм.", "width": self.PROPERTY_COLUMN_WIDTH, "unit_type": "Твердость"}
        }
        self._after_id = None
        style = ttk.Style()
        style.configure("Treeview.Heading", padding=(5, 5), wraplength=120, font=('TkDefaultFont', 9))
        style.map("Treeview", background=[("selected", "gray")], foreground=[("selected", "white")])
        self._setup_widgets()
        self._setup_treeview()
        self._reconfigure_scrollable_treeview(self.PROP_TYPES[0])

    def _setup_widgets(self):
        controls_frame = ttk.Frame(self)
        controls_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(controls_frame, text="Тип свойств:").pack(side="left", padx=(0, 5))
        self.prop_type_combo = ttk.Combobox(controls_frame, state="readonly", width=20, values=self.PROP_TYPES)
        self.prop_type_combo.pack(side="left", padx=5)
        self.prop_type_combo.set(self.PROP_TYPES[0])
        self.prop_type_combo.bind("<<ComboboxSelected>>", self._trigger_calculate)
        ttk.Label(controls_frame, text="Область применения:").pack(side="left", padx=(10, 5))
        self.area_combo = ttk.Combobox(controls_frame, state="readonly", width=30)
        self.area_combo.pack(side="left", padx=5)
        self.area_combo.bind("<<ComboboxSelected>>", self._trigger_calculate)
        ttk.Label(controls_frame, text="Температура, °С:").pack(side="left", padx=(20, 5))
        self.temp_entry = ttk.Entry(controls_frame, width=10)
        self.temp_entry.pack(side="left", padx=5)
        self.temp_entry.insert(0, "20")
        self.temp_entry.bind("<KeyRelease>", self._trigger_calculate)

        lbl_hint = ttk.Label(controls_frame, text="(ПКМ по заголовку для смены ед.изм.)", foreground="gray")
        lbl_hint.pack(side="right", padx=10)

    def _setup_treeview(self):
        tree_container = ttk.Frame(self)
        tree_container.pack(expand=True, fill="both", padx=10, pady=(0, 10))
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(1, weight=1)

        frozen_columns = ["material_name", "strength_category", "source", "max_temp"]
        self.tree_frozen = ttk.Treeview(tree_container, columns=frozen_columns, show="headings")
        self.tree_scrollable = ttk.Treeview(tree_container, columns=[], show="headings")

        self.tree_frozen.grid(row=0, column=0, sticky="nswe")
        self.tree_scrollable.grid(row=0, column=1, sticky="nswe")

        # --- ВОССТАНОВЛЕНЫ ШИРИНЫ КОЛОНОК ---
        self.tree_frozen.heading("material_name", text="Материал",
                                 command=lambda: self._sort_column("material_name", False))
        self.tree_frozen.column("material_name", width=150, minwidth=150)

        self.tree_frozen.heading("strength_category", text="КП",
                                 command=lambda: self._sort_column("strength_category", False))
        self.tree_frozen.column("strength_category", width=50, minwidth=50)

        self.tree_frozen.heading("source", text="НТД", command=lambda: self._sort_column("source", False))
        self.tree_frozen.column("source", width=120, minwidth=120)

        self.tree_frozen.heading("max_temp", text="tприм ДО, °С",
                                 command=lambda: self._sort_column("max_temp", False))
        self.tree_frozen.column("max_temp", width=100, minwidth=100, anchor="center")

        # Скроллбары
        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self._on_vertical_scroll)
        vsb.grid(row=0, column=2, sticky="ns")
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree_scrollable.xview)
        hsb.grid(row=1, column=1, sticky="ew")

        self.tree_frozen.configure(yscrollcommand=vsb.set)
        self.tree_scrollable.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # --- СИНХРОННЫЙ СКРОЛЛ КОЛЕСОМ ---
        # Мы не используем Mixin здесь, так как логика сложнее (два дерева сразу)
        self.tree_frozen.bind("<MouseWheel>", self._on_mousewheel)
        self.tree_scrollable.bind("<MouseWheel>", self._on_mousewheel)
        self.tree_frozen.bind("<Button-4>", lambda e: self._on_mousewheel(e, -1))
        self.tree_frozen.bind("<Button-5>", lambda e: self._on_mousewheel(e, 1))
        self.tree_scrollable.bind("<Button-4>", lambda e: self._on_mousewheel(e, -1))
        self.tree_scrollable.bind("<Button-5>", lambda e: self._on_mousewheel(e, 1))

        # Контекстное меню
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Копировать", command=self._copy_cell_value)
        self.last_clicked_tree = None
        self.tree_frozen.bind("<Button-3>", self._show_context_menu)
        self.tree_scrollable.bind("<Button-3>", self._on_scrollable_right_click)

    def _trigger_calculate(self, event=None):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(300, self._on_calculate)

    # Специальный метод скролла для этой вкладки
    def _on_vertical_scroll(self, *args):
        self.tree_frozen.yview(*args)
        self.tree_scrollable.yview(*args)

    # Специальный метод колеса для этой вкладки
    def _on_mousewheel(self, event, delta_direction=None):
        delta = delta_direction if delta_direction else (
            -1 * (event.delta // 120) if hasattr(event, 'delta') else (1 if event.num == 5 else -1))
        self.tree_frozen.yview_scroll(delta, "units")
        self.tree_scrollable.yview_scroll(delta, "units")
        return "break"

    def _reconfigure_scrollable_treeview(self, prop_type):
        self.tree_scrollable["columns"] = []
        self.column_units.clear()

        prop_map = {}
        if prop_type == "Физические свойства":
            prop_map = PHYSICAL_MAP
        elif prop_type == "Механические свойства":
            prop_map = MECHANICAL_MAP
        elif prop_type == "Твердость":
            prop_map = self.HARDNESS_COLUMNS

        new_columns = list(prop_map.keys())
        self.tree_scrollable["columns"] = new_columns

        for prop_key, prop_info in prop_map.items():
            base_unit = prop_info.get('unit', '')
            unit_type = prop_info.get("unit_type")
            if unit_type:
                available = UnitManager.get_units(unit_type)
                if base_unit in available:
                    self.column_units[prop_key] = base_unit
                else:
                    self.column_units[prop_key] = UnitManager.get_system_unit(unit_type)
            else:
                self.column_units[prop_key] = base_unit

            self._update_column_header(prop_key, prop_info)
            self.tree_scrollable.column(prop_key, width=self.PROPERTY_COLUMN_WIDTH, minwidth=80, anchor="center")

    def _update_column_header(self, prop_key, prop_info=None):
        if not prop_info:
            current_type = self.prop_type_combo.get()
            if current_type == "Твердость":
                prop_info = self.HARDNESS_COLUMNS.get(prop_key)
            else:
                prop_info = PROPERTIES.get_meta(prop_key)

        if not prop_info: return
        current_unit = self.column_units.get(prop_key, prop_info.get('unit', ''))
        header_text = prop_info.get('symbol', prop_info.get('name', prop_key))
        if current_unit:
            header_text += f", {current_unit}"
        self.tree_scrollable.heading(prop_key, text=header_text,
                                     command=lambda k=prop_key: self._sort_column(k, False))

    def _on_scrollable_right_click(self, event):
        region = self.tree_scrollable.identify_region(event.x, event.y)
        if region == "heading":
            col_id = self.tree_scrollable.identify_column(event.x)
            col_index = int(col_id.replace('#', '')) - 1
            columns = self.tree_scrollable["columns"]
            if 0 <= col_index < len(columns):
                self._show_header_unit_menu(event, columns[col_index])
        else:
            self._show_context_menu(event)

    def _show_header_unit_menu(self, event, prop_key):
        current_type = self.prop_type_combo.get()
        prop_info = {}
        if current_type == "Физические свойства":
            prop_info = PROPERTIES.get_meta(prop_key)
        elif current_type == "Механические свойства":
            prop_info = PROPERTIES.get_meta(prop_key)
        elif current_type == "Твердость":
            # Для твердости берем описание из HARDNESS_COLUMNS
            prop_info = self.HARDNESS_COLUMNS.get(prop_key)

        if not prop_info: return
        unit_type = prop_info.get("unit_type")
        if not unit_type: return

        available_units = UnitManager.get_units(unit_type)
        if not available_units: return

        menu = tk.Menu(self, tearoff=0)
        current_unit = self.column_units.get(prop_key)

        for unit in available_units:
            menu.add_radiobutton(
                label=unit,
                value=unit,
                variable=tk.StringVar(value=current_unit),
                command=lambda u=unit: self._change_column_unit(prop_key, u)
            )
        menu.post(event.x_root, event.y_root)

    def _change_column_unit(self, prop_key, new_unit):
        if self.column_units.get(prop_key) == new_unit:
            return

        # Особая логика для твердости: меняем единицу сразу для всех трех колонок
        # ("min_value", "max_value", "unit_value"), чтобы они были согласованы.
        if prop_key in self.HARDNESS_COLUMNS:
            for h_key in self.HARDNESS_COLUMNS.keys():
                self.column_units[h_key] = new_unit
                self._update_column_header(h_key)
        else:
            self.column_units[prop_key] = new_unit
            self._update_column_header(prop_key)

        self._populate_treeview()

    def _get_value_from_prop_data(self, prop_data, temp):
        if not prop_data or "temperature_value_pairs" not in prop_data: return None
        pairs = sorted(prop_data.get("temperature_value_pairs", []), key=lambda p: p[0])
        if not pairs: return None
        for t, val in pairs:
            if t == temp: return float(val)
        lower_point, upper_point = None, None
        for t, val in pairs:
            try:
                t_float, v_float = float(t), float(val)
                if t_float < temp:
                    lower_point = (t_float, v_float)
                elif t_float > temp:
                    upper_point = (t_float, v_float)
                    break
            except (ValueError, TypeError):
                continue
        if lower_point and upper_point:
            t1, v1 = lower_point;
            t2, v2 = upper_point
            if t2 - t1 == 0: return v1
            return v1 + (temp - t1) * (v2 - v1) / (t2 - t1)
        return None

    def _on_calculate(self):
        selected_prop_type = self.prop_type_combo.get()
        current_cols = self.tree_scrollable["columns"]

        is_phys = (selected_prop_type == "Физические свойства")
        is_mech = (selected_prop_type == "Механические свойства")
        is_hard = (selected_prop_type == "Твердость")

        prop_map = {}
        if is_phys:
            prop_map = PHYSICAL_MAP
        elif is_mech:
            prop_map = MECHANICAL_MAP
        elif is_hard:
            prop_map = self.HARDNESS_COLUMNS

        if list(current_cols) != list(prop_map.keys()):
            self._reconfigure_scrollable_treeview(selected_prop_type)

        temp = MathUtils.safe_float(self.temp_entry.get(), default=0.0)
        selected_area = self.area_combo.get()

        filtered_materials = [
            m for m in self.app_data.materials
            if selected_area == "Все" or selected_area in m.data.get(Schema.METADATA, {}).get(Schema.APP_AREA, [])
        ]

        self.treeview_data = []

        for mat in filtered_materials:
            max_app_temp = mat.data.get(Schema.METADATA, {}).get("temperature_application", {}).get("value", "-")
            cats = mat.get_strength_categories()

            if is_hard:
                # Логика твердости сложная, оставляем ручной перебор, но через константы
                if cats:
                    for cat in cats:
                        h_list = Material.get_hardness_entries(cat)
                        if h_list:
                            for h in h_list:
                                src = h.get("property_source", "") + (
                                    f" ({h.get('property_subsource')})" if h.get("property_subsource") else "")
                                self.treeview_data.append({
                                    "material_name": mat.get_display_name(), "obj": mat,
                                    "strength_category": Material.category_name(cat) or "N/A",
                                    "source": src or "-", "max_temp": max_app_temp,
                                    "min_value": h.get("min_value"), "max_value": h.get("max_value"),
                                    "unit_value": h.get("unit_value", "-")
                                })
                        else:
                            self.treeview_data.append({"material_name": mat.get_display_name(),
                                                       "strength_category": Material.category_name(cat), "source": "-",
                                                       "max_temp": max_app_temp, "min_value": None})
                else:
                    self.treeview_data.append(
                        {"material_name": mat.get_display_name(), "strength_category": "-", "source": "-",
                         "max_temp": max_app_temp, "min_value": None})
            else:
                # Физические и Механические
                if cats and not is_phys:  # Для механики разбиваем по категориям
                    for i, cat in enumerate(cats):
                        source_str = mat.get_source_info(Schema.MECHANICAL if is_mech else Schema.PHYSICAL,
                                                         category_idx=i, source_manager=self.app_data.source_manager)
                        row = {
                            "material_name": mat.get_display_name(), "obj": mat,
                            "strength_category": Material.category_name(cat) or "N/A",
                            "source": source_str, "max_temp": max_app_temp
                        }
                        for prop_key in prop_map:
                            # ! ВЫЗОВ НОВОГО МЕТОДА !
                            val = mat.get_interpolated_property(prop_key, temp, category_idx=i)
                            row[prop_key] = val
                        self.treeview_data.append(row)
                else:
                    # Физ свойства (одна строка на материал)
                    source_str = mat.get_source_info(Schema.PHYSICAL, source_manager=self.app_data.source_manager)
                    row = {
                        "material_name": mat.get_display_name(), "obj": mat,
                        "strength_category": "-", "source": source_str, "max_temp": max_app_temp
                    }
                    for prop_key in prop_map:
                        # ! ВЫЗОВ НОВОГО МЕТОДА !
                        val = mat.get_interpolated_property(prop_key, temp)
                        row[prop_key] = val
                    self.treeview_data.append(row)

        self._populate_treeview()

    def _populate_treeview(self):
        for i in self.tree_frozen.get_children(): self.tree_frozen.delete(i)
        for i in self.tree_scrollable.get_children(): self.tree_scrollable.delete(i)

        scrollable_cols = self.tree_scrollable["columns"]
        frozen_cols = self.tree_frozen["columns"]

        prop_map = {}
        current_type = self.prop_type_combo.get()
        if current_type == "Физические свойства":
            prop_map = PHYSICAL_MAP
        elif current_type == "Механические свойства":
            prop_map = MECHANICAL_MAP
        elif current_type == "Твердость":
            prop_map = self.HARDNESS_COLUMNS

        for row in self.treeview_data:
            frozen_values = [str(row.get(c, "-") if row.get(c) is not None else "-") for c in frozen_cols]
            scrollable_values = []
            for col_key in scrollable_cols:
                raw_val = row.get(col_key)
                if col_key == "unit_value":
                    # Для твердости показываем выбранную единицу отображения,
                    # а не исходную из БД.
                    if self.prop_type_combo.get() == "Твердость":
                        unit = self.column_units.get(col_key) or UnitManager.get_system_unit("Твердость")
                        scrollable_values.append(unit)
                    else:
                        scrollable_values.append(str(raw_val) if raw_val else "-")
                    continue
                if raw_val is None:
                    scrollable_values.append("-")
                    continue

                prop_info = prop_map.get(col_key)
                if prop_info and "unit_type" in prop_info:
                    unit_type = prop_info["unit_type"]
                    source_unit = prop_info.get("unit")
                    if unit_type == "Твердость": source_unit = row.get("unit_value")
                    target_unit = self.column_units.get(col_key, source_unit)

                    if source_unit and target_unit and unit_type:
                        try:
                            sys_val = UnitManager.to_system(raw_val, source_unit, unit_type)
                            final_val = UnitManager.from_system(sys_val, target_unit, unit_type)
                            scrollable_values.append(f"{final_val:.2f}")
                        except Exception:
                            scrollable_values.append(f"{raw_val:.2f}")
                    else:
                        scrollable_values.append(f"{raw_val:.2f}")
                else:
                    scrollable_values.append(f"{raw_val:.2f}")

            self.tree_frozen.insert("", "end", values=frozen_values)
            self.tree_scrollable.insert("", "end", values=scrollable_values)

    def _sort_column(self, col, reverse):
        def get_sort_key(item):
            value = item.get(col)
            if value is None: return (2, None)
            if isinstance(value, (int, float)): return (0, value)
            return (1, str(value).lower())

        self.treeview_data.sort(key=get_sort_key, reverse=reverse)
        self._populate_treeview()
        tree_to_bind = self.tree_frozen if col in self.tree_frozen['columns'] else self.tree_scrollable
        tree_to_bind.heading(col, command=lambda: self._sort_column(col, not reverse))

    def update_comboboxes(self):
        areas = ["Все"] + self.app_data.application_areas
        self.area_combo.config(values=areas)
        if not self.area_combo.get(): self.area_combo.set("Все")
        if not self.prop_type_combo.get(): self.prop_type_combo.set(self.PROP_TYPES[0])
        self._trigger_calculate()

    def _show_context_menu(self, event):
        self.last_clicked_tree = event.widget
        item_id = self.last_clicked_tree.identify_row(event.y)
        if item_id:
            self.last_clicked_tree.focus(item_id)
            self.last_clicked_tree.selection_set(item_id)
        self.context_menu.post(event.x_root, event.y_root)

    def _copy_cell_value(self):
        tree = self.last_clicked_tree
        if not tree or not tree.focus(): return
        item = tree.focus()
        col = tree.identify_column(self.winfo_pointerx() - tree.winfo_rootx())
        col_index = int(col.replace('#', '')) - 1
        try:
            value = tree.item(item, "values")[col_index]
            self.clipboard_clear()
            self.clipboard_append(value)
        except (IndexError, tk.TclError):
            pass


class SingleCalculationTab(ttk.Frame, ScrollableMixin):
    """
    Вкладка-справочник + Калькулятор точки.
    Особенности:
    - Скрытие/показ колонок.
    - Увеличенная высота заголовков.
    - Интерполяция и (для произвольных точек) экстраполяция по двум ближайшим точкам.
    - Автопересчет при смене материала.
    """

    def __init__(self, parent, app_data, main_app):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app
        self.column_units = {}
        self.column_visibility = {
            k: True for k in PROPERTIES.all_keys()
        }
        self.ALL_KEYS = PROPERTIES.all_keys()
        self.TEMP_KEYS = [k for k in self.ALL_KEYS if PROPERTIES.supports_temperature(k)]
        self.SCALAR_KEYS = [k for k in self.ALL_KEYS if not PROPERTIES.supports_temperature(k)]
        self.db_data_rows = []
        self.custom_temps = []
        style = ttk.Style()
        style.configure("BigHeader.Treeview.Heading", padding=(5, 10, 5, 10), font=('TkDefaultFont', 9, 'bold'))
        style.configure("BigHeader.Treeview", rowheight=25)
        self._setup_widgets()

    def _setup_widgets(self):
        # --- 1. ВЕРХНЯЯ ПАНЕЛЬ ФИЛЬТРОВ ---
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill="x", side="top")

        row1 = ttk.Frame(top_frame)
        row1.pack(fill="x", pady=(0, 5))

        ttk.Label(row1, text="Область:").pack(side="left", padx=(0, 5))
        self.area_combo = ttk.Combobox(row1, state="readonly", width=20)
        self.area_combo.pack(side="left", padx=5)
        self.area_combo.bind("<<ComboboxSelected>>", self._filter_materials)

        ttk.Label(row1, text="Материал:").pack(side="left", padx=(15, 5))
        self.material_combo = ttk.Combobox(row1, state="readonly", width=35)
        self.material_combo.pack(side="left", padx=5)
        self.material_combo.bind("<<ComboboxSelected>>", self._on_material_select)

        ttk.Label(row1, text="КП:").pack(side="left", padx=(15, 5))
        self.category_combo = ttk.Combobox(row1, state="readonly", width=10)
        self.category_combo.pack(side="left", padx=5)
        self.category_combo.bind("<<ComboboxSelected>>", self._on_category_select)

        row2 = ttk.Frame(top_frame)
        row2.pack(fill="x")

        self.col_btn = ttk.Menubutton(row2, text="Настроить столбцы", direction="below")
        self.col_menu = tk.Menu(self.col_btn, tearoff=0)
        self.col_btn.configure(menu=self.col_menu)
        self.col_btn.pack(side="left")
        self._populate_column_menu()

        ttk.Label(row2, text="(ПКМ по заголовку — смена ед.изм)", foreground="gray").pack(side="right")

        # --- 2. ТАБЛИЦА ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=0)

        self.tree = ttk.Treeview(tree_frame, show="headings", style="BigHeader.Treeview")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Теги для раскраски фона
        self.tree.tag_configure("custom_calc", background="#ffffe0", foreground="black",
                                font=('TkDefaultFont', 9, 'bold'))
        self.tree.tag_configure("separator", background="#555555", foreground="white")

        self.tree.bind("<Button-3>", self._on_header_right_click)
        self.tree.bind("<ButtonRelease-1>", lambda e: self._enforce_column_minwidths())
        self.bind_mouse_wheel(self.tree)

        # --- 3. ЛЕГЕНДА ПОД БЛОКОМ РАСЧЕТА ---
        # ВНИМАНИЕ: пакуем legend_frame ПЕРЕД calc_frame с side="bottom",
        # чтобы визуально легенда была ПОД блоком "Расчет произвольной точки".
        legend_frame = ttk.Frame(self, padding=(10, 0))
        legend_frame.pack(fill="x", padx=10, pady=(0, 5), side="bottom")

        legend_text = (
            "330.0 - значение соответствует заданному в базе данных; "
            "(330.0) - значение получено линейной интерполяцией; "
            "[330.0] - значение получено линейной экстраполяцией по двум ближайшим точкам."
        )
        ttk.Label(legend_frame, text=legend_text, foreground="gray").pack(anchor="w")

        # --- 4. НИЖНЯЯ ПАНЕЛЬ (КАЛЬКУЛЯТОР) ---
        calc_frame = ttk.LabelFrame(self, text="Расчет произвольной точки", padding=10)
        calc_frame.pack(fill="x", padx=10, pady=10, side="bottom")

        ttk.Label(calc_frame, text="Температура, °C:").pack(side="left", padx=(0, 5))
        self.calc_temp_entry = ttk.Entry(calc_frame, width=10)
        self.calc_temp_entry.pack(side="left", padx=5)
        self.calc_temp_entry.bind("<Return>", lambda e: self._add_custom_calculation())

        # Кнопка добавления
        add_btn = ttk.Button(calc_frame, text="+ Добавить расчет", command=self._add_custom_calculation)
        add_btn.pack(side="left", padx=15)

        # Кнопка удаления выделенного
        del_btn = ttk.Button(calc_frame, text="- Исключить строку", command=self._remove_selected_custom_row)
        del_btn.pack(side="left", padx=5)

        sort_btn = ttk.Button(calc_frame, text="Сортировать", command=self._sort_custom_rows)
        sort_btn.pack(side="left", padx=5)

        # Кнопка очистки всего
        clear_btn = ttk.Button(calc_frame, text="Очистить все", command=self._clear_custom_rows)
        clear_btn.pack(side="right")

    def _populate_column_menu(self):
        self.col_menu.delete(0, tk.END)
        self.col_menu.add_command(label="[Показать все]", command=lambda: self._set_all_columns(True))
        self.col_menu.add_command(label="[Скрыть все]", command=lambda: self._set_all_columns(False))
        self.col_menu.add_separator()

        for key in self.ALL_KEYS:
            name = PROPERTIES.get_meta(key)['symbol']

            is_visible = self.column_visibility[key]
            self.col_menu.add_checkbutton(
                label=name, onvalue=1, offvalue=0,
                variable=tk.IntVar(value=1 if is_visible else 0),
                command=lambda k=key: self._toggle_column(k)
            )

    def _toggle_column(self, key):
        self.column_visibility[key] = not self.column_visibility[key]
        self._populate_column_menu()
        self._render_table()

    def _set_all_columns(self, visible):
        for k in self.column_visibility:
            self.column_visibility[k] = visible
        self._populate_column_menu()
        self._render_table()

    # --- ЛОГИКА ---

    def update_comboboxes(self):
        areas = ["Все"] + self.app_data.application_areas
        self.area_combo.config(values=areas)
        if not self.area_combo.get():
            self.area_combo.set("Все")
        self._filter_materials()

    def _filter_materials(self, event=None):
        selected_area = self.area_combo.get()
        mats = []
        for m in self.app_data.materials:
            if selected_area == "Все" or selected_area in m.data.get("metadata", {}).get("application_area", []):
                mats.append(m.get_display_name())

        self.material_combo.config(values=mats)
        if mats:
            self.material_combo.current(0)
            self._on_material_select()
        else:
            self.material_combo.set("")
            self.category_combo.set("")
            self._clear_db_data()

    def _on_material_select(self, event=None):
        mat_name = self.material_combo.get()
        material = next((m for m in self.app_data.materials if m.get_display_name() == mat_name), None)
        if not material:
            return

        cats = material.get_strength_categories()
        cat_names = [Material.category_name(c) or "Без названия" for c in cats]

        self.category_combo.config(values=cat_names)
        if cat_names:
            self.category_combo.current(0)
        else:
            self.category_combo.set("")

        self._calculate_db_rows()

    def _on_category_select(self, event=None):
        self._calculate_db_rows()

    def _clear_db_data(self):
        self.db_data_rows = []
        self._render_table()

    def _get_value_with_mode(self, material, prop_key, temp, cat_idx=None, allow_extrapolation=False):
        """
        Возвращает кортеж (value, mode) для заданного свойства:
        - value: float или None;
        - mode: "exact" (точное совпадение точки),
                "interp" (линейная интерполяция внутри диапазона),
                "approx" (линейная экстраполяция по двум ближайшим точкам),
                либо None, если значение не может быть определено.
        """
        data_container = None

        # Определяем, откуда брать пары температур для свойства
        if PROPERTIES.is_physical(prop_key):
            data_container = material.get_physical_data(prop_key)
        elif PROPERTIES.is_mechanical(prop_key):
            cats = material.get_strength_categories()
            if cat_idx is not None and 0 <= cat_idx < len(cats):
                data_container = Material.get_category_prop_data(cats[cat_idx], prop_key)
        else:
            return None, None

        if not data_container:
            return None, None

        pairs = data_container.get(Schema.TEMP_PAIRS, [])
        if not pairs:
            return None, None

        points = []
        for t_raw, v_raw in pairs:
            t_val = safe_float(t_raw)
            v_val = safe_float(v_raw)
            if t_val is not None and v_val is not None:
                points.append((t_val, v_val))

        if not points:
            return None, None

        points.sort(key=lambda p: p[0])
        xs = [p[0] for p in points]
        min_x, max_x = xs[0], xs[-1]

        # 1. Точное совпадение
        for x, y in points:
            if x == temp:
                return y, "exact"

        # 2. Внутри диапазона — интерполяция
        if min_x < temp < max_x:
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if x1 <= temp <= x2:
                    if x2 == x1:
                        return y1, "interp"
                    val = y1 + (temp - x1) * (y2 - y1) / (x2 - x1)
                    return val, "interp"
            return None, None

        # 3. Вне диапазона
        if not allow_extrapolation:
            return None, None

        # 3.1. Если всего одна точка — повторяем её как экстраполяцию
        if len(points) == 1:
            return points[0][1], "approx"

        # 3.2. Две ближайшие точки для экстраполяции
        if temp < min_x:
            p1, p2 = points[0], points[1]
        else:
            p1, p2 = points[-2], points[-1]

        x1, y1 = p1
        x2, y2 = p2
        if x2 == x1:
            return y1, "approx"

        val = y1 + (temp - x1) * (y2 - y1) / (x2 - x1)
        return val, "approx"

    def _get_property_container(self, material, prop_key, cat_idx=None):
        if PROPERTIES.is_physical(prop_key):
            return material.get_physical_data(prop_key)
        if PROPERTIES.is_mechanical(prop_key):
            cats = material.get_strength_categories()
            if cat_idx is not None and 0 <= cat_idx < len(cats):
                return Material.get_category_prop_data(cats[cat_idx], prop_key)
        return None

    def _get_scalar_value(self, material, prop_key, cat_idx=None):
        """Скалярные свойства (δ, ψ, угол): одно значение без привязки к T."""
        data_container = self._get_property_container(material, prop_key, cat_idx)
        if not data_container:
            return None

        pairs = data_container.get(Schema.TEMP_PAIRS, [])
        for _, v_raw in pairs:
            v_val = safe_float(v_raw)
            if v_val is not None:
                return v_val
        return None

    def _calculate_db_rows(self):
        """Сбор данных из БД (без экстраполяции, только точные точки и интерполяция)."""
        mat_name = self.material_combo.get()
        material = next((m for m in self.app_data.materials if m.get_display_name() == mat_name), None)
        if not material:
            return

        cat_idx = self.category_combo.current()

        # Собираем температуры только из температурно-зависимых свойств
        all_temps = set()
        cat_idx_arg = cat_idx if cat_idx != -1 else None

        for pk in self.TEMP_KEYS:
            data = self._get_property_container(material, pk, cat_idx_arg)
            if not data:
                continue
            for t, _ in data.get(Schema.TEMP_PAIRS, []):
                all_temps.add(t)

        scalar_values = {
            pk: self._get_scalar_value(material, pk, cat_idx_arg)
            for pk in self.SCALAR_KEYS
        }

        sorted_temps = sorted(list(all_temps))
        self.db_data_rows = []
        if not sorted_temps and any(v is not None for v in scalar_values.values()):
            row = {"temp": "—"}
            for prop_key in self.SCALAR_KEYS:
                row[prop_key] = {"value": scalar_values.get(prop_key), "mode": "scalar"}
            self.db_data_rows.append(row)

        for t in sorted_temps:
            row = {"temp": t}
            for prop_key in self.TEMP_KEYS:
                value, mode = self._get_value_with_mode(
                    material,
                    prop_key,
                    t,
                    cat_idx=cat_idx_arg,
                    allow_extrapolation=False
                )
                row[prop_key] = {"value": value, "mode": mode}
            for prop_key in self.SCALAR_KEYS:
                row[prop_key] = {"value": scalar_values.get(prop_key), "mode": "scalar"}
            self.db_data_rows.append(row)

        self._render_table()

    def _calculate_custom_row(self, temp):
        """
        Расчет пользовательской строки (с экстраполяцией).
        Возвращает словарь с "temp" и для каждого свойства:
        {"value": float|None, "mode": "exact"/"interp"/"approx"|None}.
        """
        mat_name = self.material_combo.get()
        material = next((m for m in self.app_data.materials if m.get_display_name() == mat_name), None)
        if not material:
            return {"temp": temp}

        cat_idx = self.category_combo.current()
        cat_idx_arg = cat_idx if cat_idx != -1 else None

        row = {"temp": temp}
        for prop_key in self.TEMP_KEYS:
            value, mode = self._get_value_with_mode(
                material,
                prop_key,
                temp,
                cat_idx=cat_idx_arg,
                allow_extrapolation=True
            )
            row[prop_key] = {"value": value, "mode": mode}
        for prop_key in self.SCALAR_KEYS:
            row[prop_key] = {
                "value": self._get_scalar_value(material, prop_key, cat_idx_arg),
                "mode": "scalar",
            }
        return row

    def _render_table(self):
        self.tree.delete(*self.tree.get_children())

        visible_keys = [k for k in self.ALL_KEYS if self.column_visibility[k]]
        cols = ["temp"] + visible_keys
        self.tree["columns"] = cols

        self.tree.heading("temp", text="T, °C")
        self.tree.column("temp", width=90, minwidth=90, anchor="center", stretch=False)

        # Заголовки свойств
        for prop_key in visible_keys:
            info = PROPERTIES.get_meta(prop_key)

            base_unit = info.get("unit", "")
            current_unit = self.column_units.get(prop_key)

            if not current_unit:
                unit_type = info.get("unit_type")
                if unit_type:
                    avail = UnitManager.get_units(unit_type)
                    current_unit = base_unit if base_unit in avail else UnitManager.get_system_unit(unit_type)
                else:
                    current_unit = base_unit
                self.column_units[prop_key] = current_unit

            header_text = f"{info.get('symbol', prop_key)}\n{current_unit}"
            self.tree.heading(prop_key, text=header_text)
            self.tree.column(prop_key, width=90, minwidth=90, anchor="center", stretch=False)

        def insert_row(row_dict, tag=""):
            values = [row_dict["temp"]]
            is_custom = (tag == "custom_calc")

            for prop_key in visible_keys:
                cell = row_dict.get(prop_key)

                # Поддержка старого формата (на всякий случай)
                if isinstance(cell, dict):
                    raw_val = cell.get("value")
                    mode = cell.get("mode")
                else:
                    raw_val = cell
                    mode = None

                if raw_val is None:
                    values.append("-")
                    continue

                info = PROPERTIES.get_meta(prop_key)
                unit_type = info.get("unit_type")
                base_unit = info.get("unit")
                target_unit = self.column_units.get(prop_key)

                # Конвертация единиц и форматирование с точностью 0.1
                if unit_type and base_unit and target_unit:
                    try:
                        sys_val = UnitManager.to_system(raw_val, base_unit, unit_type)
                        final_val = UnitManager.from_system(sys_val, target_unit, unit_type)
                        base_str = f"{final_val:.1f}"
                    except Exception:
                        base_str = str(raw_val)
                else:
                    try:
                        base_str = f"{float(raw_val):.1f}"
                    except Exception:
                        base_str = str(raw_val)

                # Обозначения для пользовательских строк:
                # exact  -> 330.0
                # interp -> (330.0)
                # approx -> [330.0]
                # Для строк из БД интерполированные значения тоже в скобках (330.0)
                if is_custom:
                    if mode == "interp":
                        display_str = f"({base_str})"
                    elif mode == "approx":
                        display_str = f"[{base_str}]"
                    else:
                        display_str = base_str
                else:
                    if mode == "interp":
                        display_str = f"({base_str})"
                    else:
                        display_str = base_str

                values.append(display_str)

            self.tree.insert("", "end", values=values, tags=(tag,) if tag else ())

        # 1. Данные из БД
        for row in self.db_data_rows:
            insert_row(row)

        # 2. Разделитель (если есть кастомные данные)
        if self.custom_temps:
            sep_values = ["РАСЧЕТ"] + [""] * len(visible_keys)
            self.tree.insert("", "end", values=sep_values, tags=("separator",))

            # 3. Пользовательские данные (считаем на лету)
            for t in self.custom_temps:
                calc_row = self._calculate_custom_row(t)
                insert_row(calc_row, tag="custom_calc")

        self._enforce_column_minwidths()

    def _enforce_column_minwidths(self):
        """Принудительно выставляет ширину колонок не меньше minwidth (соблюдается всегда)."""
        MIN_COLUMN_WIDTH = 90
        try:
            for col in self.tree["columns"]:
                current = self.tree.column(col, "width")
                min_w = self.tree.column(col, "minwidth")
                min_w = max(min_w, MIN_COLUMN_WIDTH)
                if current < min_w:
                    self.tree.column(col, width=min_w)
        except (tk.TclError, TypeError):
            pass

    # --- КАЛЬКУЛЯТОР ---

    def _add_custom_calculation(self):
        temp = safe_float(self.calc_temp_entry.get())
        if temp is None:
            messagebox.showerror("Ошибка", "Некорректная температура")
            return

        self.custom_temps.append(temp)
        self._render_table()
        self.tree.yview_moveto(1)
        self.calc_temp_entry.delete(0, tk.END)

    def _remove_selected_custom_row(self):
        """Удаляет только выделенную строку, если это расчет (по позиции в списке)."""
        selected_item = self.tree.selection()
        if not selected_item:
            return

        item_id = selected_item[0]
        item = self.tree.item(item_id)
        tags = item.get("tags", [])

        if "custom_calc" not in tags:
            messagebox.showinfo("Инфо", "Можно удалять только строки из раздела расчетов.")
            return

        children = self.tree.get_children()
        try:
            idx = list(children).index(item_id)
        except ValueError:
            return

        n_db = len(self.db_data_rows)
        # После строк БД идёт разделитель (если есть custom_temps), затем строки расчёта
        if self.custom_temps and idx > n_db:
            custom_index = idx - n_db - 1  # -1 из-за строки-разделителя "РАСЧЕТ"
            if 0 <= custom_index < len(self.custom_temps):
                self.custom_temps.pop(custom_index)
                self._render_table()

    def _clear_custom_rows(self):
        self.custom_temps = []
        self._render_table()

    def _sort_custom_rows(self):
        """Сортирует список произвольных температур по возрастанию и перерисовывает таблицу."""
        self.custom_temps.sort()
        self._render_table()

    # --- КОНТЕКСТНОЕ МЕНЮ (ПКМ) ---
    def _on_header_right_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "heading":
            col_id = self.tree.identify_column(event.x)
            col_index = int(col_id.replace('#', '')) - 1
            current_cols = self.tree["columns"]

            if 0 <= col_index < len(current_cols):
                prop_key = current_cols[col_index]
                if prop_key == "temp":
                    return
                self._show_unit_menu(event, prop_key)

    def _show_unit_menu(self, event, prop_key):
        if PROPERTIES.is_physical(prop_key):
            info = PROPERTIES.get_meta(prop_key)
        else:
            info = PROPERTIES.get_meta(prop_key)

        if not info:
            return
        unit_type = info.get("unit_type")
        if not unit_type:
            return

        available = UnitManager.get_units(unit_type)
        current = self.column_units.get(prop_key)

        menu = tk.Menu(self, tearoff=0)
        for u in available:
            menu.add_radiobutton(label=u, value=u,
                                 variable=tk.StringVar(value=current),
                                 command=lambda x=u: self._change_unit(prop_key, x))
        menu.post(event.x_root, event.y_root)

    def _change_unit(self, prop_key, new_unit):
        self.column_units[prop_key] = new_unit
        self._render_table()


class PropertyComparisonTab(ttk.Frame):
    """Вкладка 'Сравнение материалов (свойства)' с новым интерфейсом выбора."""

    def __init__(self, parent, app_data, main_app):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app
        # listbox_item_map — текущий пул для списка поиска (фильтруется по области и свойству)
        self.listbox_item_map = {}
        # full_item_map — полный пул "имя -> (material_data, category_data)" для всех материалов/КП,
        # используется для построения графика, чтобы показывать "нет данных" при смене свойства.
        self.full_item_map = {}
        self._setup_widgets()

    def _setup_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        controls_frame = ttk.Frame(main_frame, width=300)
        controls_frame.pack(side="left", fill="y", padx=(0, 10))
        controls_frame.pack_propagate(False)

        ttk.Label(controls_frame, text="Область применения:").pack(fill="x", pady=(0, 2))
        self.area_combo = ttk.Combobox(controls_frame, state="readonly")
        self.area_combo.pack(fill="x", pady=(0, 10))
        self.area_combo.bind("<<ComboboxSelected>>", self._update_search_pool)

        ttk.Label(controls_frame, text="Свойство для сравнения:").pack(fill="x", pady=(0, 2))
        self.prop_keys = [k for k in ALL_PROPERTIES_MAP if PROPERTIES.supports_temperature(k)]
        prop_names = [
            f"{ALL_PROPERTIES_MAP[k]['name']} ({ALL_PROPERTIES_MAP[k].get('symbol', '')})"
            for k in self.prop_keys
        ]
        self.prop_combo = ttk.Combobox(controls_frame, state="readonly", values=prop_names)
        self.prop_combo.pack(fill="x", pady=(0, 10))
        if prop_names:
            self.prop_combo.current(0)
        # При смене свойства пересобираем пул материалов и обновляем график
        self.prop_combo.bind("<<ComboboxSelected>>", self._on_property_change)

        ttk.Label(controls_frame, text="Поиск материала:").pack(fill="x", pady=(5, 2))
        self.search_entry = ttk.Entry(controls_frame)
        self.search_entry.pack(fill="x", pady=(0, 5))
        self.search_entry.bind("<KeyRelease>", self._filter_search_results)

        search_list_frame = ttk.LabelFrame(controls_frame, text="Результаты поиска")
        search_list_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.search_listbox = tk.Listbox(search_list_frame, exportselection=False)
        search_scrollbar = ttk.Scrollbar(search_list_frame, orient="vertical", command=self.search_listbox.yview)
        self.search_listbox.config(yscrollcommand=search_scrollbar.set)
        search_scrollbar.pack(side="right", fill="y")
        self.search_listbox.pack(side="left", fill="both", expand=True)
        self.search_listbox.bind("<Double-1>", self._add_material_to_selection)

        selected_list_frame = ttk.LabelFrame(controls_frame, text="Выбранные материалы")
        selected_list_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.selected_listbox = tk.Listbox(selected_list_frame, exportselection=False)
        selected_scrollbar = ttk.Scrollbar(selected_list_frame, orient="vertical", command=self.selected_listbox.yview)
        self.selected_listbox.config(yscrollcommand=selected_scrollbar.set)
        selected_scrollbar.pack(side="right", fill="y")
        self.selected_listbox.pack(side="left", fill="both", expand=True)
        self.selected_listbox.bind("<Double-1>", self._remove_material_from_selection)

        plot_button = ttk.Button(controls_frame, text="Построить график", command=self._plot_graph)
        plot_button.pack(fill="x", pady=(0, 5))

        reset_button = ttk.Button(controls_frame, text="Сбросить", command=self._reset_selection)
        reset_button.pack(fill="x")

        self.plot_frame = ttk.Frame(main_frame)
        self.plot_frame.pack(side="right", fill="both", expand=True)
        fig = Figure(figsize=(8, 6), dpi=100)
        self.ax = fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        toolbar = CustomToolbar(self.canvas, self.plot_frame, plot_callback=self._plot_graph)
        toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def update_lists(self):
        """Вызывается при загрузке данных. Обновляет фильтры и пулы данных."""
        areas = ["Все"] + self.app_data.application_areas
        self.area_combo.config(values=areas)
        self.area_combo.set("Все")

        # Полный пул для всех материалов и всех категорий (независимо от выбранного свойства).
        # Используется при построении графика, чтобы даже при смене свойства
        # уже выбранные материалы могли попасть в легенду как "нет данных".
        self.full_item_map.clear()
        for mat in self.app_data.materials:
            display_name = mat.get_display_name()
            # Сам материал (для физ. свойств)
            self.full_item_map[display_name] = (mat.data, None)

            # Категории прочности (для мех. свойств)
            for cat in mat.get_strength_categories():
                cat_name = Material.category_name(cat)
                display_name_with_cat = f"{display_name} {cat_name}".strip()
                self.full_item_map[display_name_with_cat] = (mat.data, cat)

        self._update_search_pool()

    def _on_property_change(self, event=None):
        """
        Обработчик смены свойства:
        - пересобирает пул материалов с учетом выбранного свойства;
        - обновляет график на основе текущего списка выбранных материалов.
        """
        self._update_search_pool()
        self._plot_graph()

    def _update_search_pool(self, event=None):
        """
        Обновляет `listbox_item_map`, который является источником для поиска.
        Учитывает:
        - выбранную область применения;
        - выбранное свойство: в пул попадают только те материалы/категории,
          у которых для этого свойства есть непустые temperature_value_pairs.
        """
        self.listbox_item_map.clear()
        selected_area = self.area_combo.get()

        # Текущее выбранное свойство
        prop_idx = self.prop_combo.current()
        if prop_idx == -1:
            # Свойство не выбрано — ничего не показываем
            self._filter_search_results()
            return

        prop_key = self.prop_keys[prop_idx]

        for mat in self.app_data.materials:
            meta = mat.data.get("metadata", {})
            app_areas = meta.get("application_area", [])
            if selected_area != "Все" and selected_area not in app_areas:
                continue

            display_name = mat.get_display_name()

            if PROPERTIES.is_mechanical(prop_key):
                # Для механического свойства показываем только те категории прочности,
                # в которых это свойство реально заполнено (есть точки).
                cats = mat.get_strength_categories()
                for cat in cats:
                    prop_data = Material.get_category_prop_data(cat, prop_key)
                    if not prop_data:
                        continue
                    pairs = prop_data.get("temperature_value_pairs", [])
                    if not pairs:
                        continue

                    cat_name = Material.category_name(cat)
                    display_name_with_cat = f"{display_name} {cat_name}".strip()
                    self.listbox_item_map[display_name_with_cat] = (mat.data, cat)
            else:
                # Физическое свойство: используем только физические свойства материала.
                prop_data = Material.physical_data_from_raw(mat.data, prop_key)
                if not prop_data:
                    continue
                pairs = prop_data.get("temperature_value_pairs", [])
                if not pairs:
                    continue

                # Добавляем сам материал (без разбиения по категориям)
                self.listbox_item_map[display_name] = (mat.data, None)

        self._filter_search_results()

    def _filter_search_results(self, event=None):
        """Фильтрует список `search_listbox` на основе текста в `search_entry`."""
        search_term = self.search_entry.get().lower()
        self.search_listbox.delete(0, tk.END)

        sorted_keys = sorted(self.listbox_item_map.keys())

        for name in sorted_keys:
            if search_term in name.lower():
                self.search_listbox.insert(tk.END, name)

    def _add_material_to_selection(self, event):
        """Добавляет материал из списка поиска в список выбранных."""
        selected_indices = self.search_listbox.curselection()
        if not selected_indices: return

        name_to_add = self.search_listbox.get(selected_indices[0])
        current_selected = self.selected_listbox.get(0, tk.END)

        if name_to_add not in current_selected:
            self.selected_listbox.insert(tk.END, name_to_add)

    def _remove_material_from_selection(self, event):
        """Удаляет материал из списка выбранных."""
        selected_indices = self.selected_listbox.curselection()
        if not selected_indices: return

        self.selected_listbox.delete(selected_indices[0])

    def _reset_selection(self):
        """Сбрасывает список выбранных материалов и график."""
        self.selected_listbox.delete(0, tk.END)
        self.search_entry.delete(0, tk.END)
        self._filter_search_results()
        self._plot_graph()

    def _add_minor_gridlines(self):
        # Эта функция остается без изменений
        x_ticks = self.ax.get_xticks()
        if len(x_ticks) > 1:
            for i in range(len(x_ticks) - 1):
                mid_point = (x_ticks[i] + x_ticks[i + 1]) / 2
                self.ax.axvline(x=mid_point, color='grey', linestyle='--', linewidth=0.5, alpha=0.7)
        y_ticks = self.ax.get_yticks()
        if len(y_ticks) > 1:
            for i in range(len(y_ticks) - 1):
                mid_point = (y_ticks[i] + y_ticks[i + 1]) / 2
                self.ax.axhline(y=mid_point, color='grey', linestyle='--', linewidth=0.5, alpha=0.7)

    def _plot_graph(self):
        """Строит график на основе списка `selected_listbox`."""
        prop_idx = self.prop_combo.current()
        if prop_idx == -1:
            messagebox.showwarning("Внимание", "Выберите свойство для отображения.")
            return

        prop_key = self.prop_keys[prop_idx]
        prop_info = ALL_PROPERTIES_MAP.get(prop_key)
        if not prop_info:
            return

        self.ax.clear()

        selected_names = self.selected_listbox.get(0, tk.END)
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b',
                  '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        for i, display_name in enumerate(selected_names):
            color = colors[i % len(colors)]

            # Для построения графика используем ПОЛНЫЙ пул (full_item_map),
            # чтобы уже выбранные материалы/КП оставались в легенде даже если
            # для текущего свойства у них нет данных.
            material_data, category_data = self.full_item_map.get(display_name, (None, None))

            if not material_data:
                # Вообще не нашли такой материал/категорию — пропускаем
                continue

            prop_data = None


            if PROPERTIES.is_mechanical(prop_key):
                # Если свойство механическое, ищем его ТОЛЬКО в категории
                if category_data:
                    prop_data = Material.get_category_prop_data(category_data, prop_key)
            else:
                # Если свойство физическое, ищем его в ОБЩИХ данных материала
                prop_data = Material.physical_data_from_raw(material_data, prop_key)

            if prop_data and "temperature_value_pairs" in prop_data and prop_data["temperature_value_pairs"]:
                pairs = sorted(prop_data["temperature_value_pairs"], key=lambda p: p[0])
                temps = [p[0] for p in pairs]
                values = [p[1] for p in pairs]
                self.ax.plot(temps, values, marker='o', linestyle='-', label=display_name, color=color)
                for t, v in zip(temps, values):
                    text_label = f"{v:.0f}" if v == int(v) else f"{v:.1f}"
                    self.ax.annotate(
                        text_label,
                        xy=(t, v),
                        xytext=(5, 5),
                        textcoords='offset points',
                        fontsize=8,
                        color='dimgray'
                    )
            else:
                # Нет данных по выбранному свойству — выводим "нет данн��х" в легенде
                self.ax.plot([], [], marker='o', linestyle='-', label=f"{display_name} (нет данных)", color=color)

        self.ax.set_xlabel("Температура [°С]")
        self.ax.set_ylabel(f"{prop_info['name']} [{prop_info['unit']}]")
        self.ax.set_title(f"Зависимость свойства '{prop_info['name']}' от температуры")

        if selected_names:
            self.ax.legend()

        self.ax.grid(True)
        self._add_minor_gridlines()
        self.canvas.draw()


class ChemComparisonTab(ttk.Frame, ScrollableMixin):
    """
    Вкладка "Сравнение материалов (хим. состав)" с разделением на два сценария:
    1) Сравнение хим. состава одного материала по разным источникам (ГОСТ/ТУ).
    2) Подбор материала по целевому химическому составу.
    """

    def __init__(self, parent, app_data, main_app):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app

        # Подсказки по влиянию элементов (можно переиспользовать при необходимости)
        self.element_tooltips = {
            "C": "Углерод.\nПовышает: Твердость, прочность, упругость.\nСнижает: Пластичность, вязкость.",
            "Si": "Кремний.\nПовышает: Прочность, упругость, электросопротивление, жаростойкость, твердость.\nСнижает: -.",
            "P": "Фосфор.\nПовышает: Прочность, коррозионная стойкость.\nСнижает: Пластичность, вязкость",
            "S": "Сера.\nПовышает: Хрупкость при высоких температурах. \nСнижает: Прочность, пластичность, свариваемость, коррозионная стойкость",
            "N2": "Азот.\nПовышает: -. \nСнижает: Вязкость, пластичность.",
            "O2": "Кислород.\nПовышает: -. \nСнижает: Вязкость, пластичность.",
            "H2": "Водород.\nПовышает: Хрупкость. \nСнижает: -.",
            "Cr": "Хром.\nПовышает: Твердость, прочность, ударная вязкость, коррозионная стойкость, электросопротивление. \nСнижает: Коэффициент линейного расширения, пластичность.",
            "Ni": "Никель.\nПовышает: Пластичность, вязкость, коррозионная стойкость, ударная прочность. \nСнижает: -.",
            "W": "Вольфрам.\nПовышает: Твердость, прокаливаемость. \nСнижает: -.",
            "Mo": "Молибден.\nПовышает: Упругость, коррозионная стойкость, сопротивляемость растягивающим нагрузкам, прокаливаемость.  \nСнижает: -.",
            "V": "Ванадий.\nПовышает: Прочность, твердость, плотность. \nСнижает: -.",
            "Mn": "Марганец.\nПовышает: Твердость, износоустойчивость, ударная вязкость, прокаливаемость. \nСнижает: -.",
            "Co": "Кобальт.\nПовышает: Ударная прочность, жаропрочность, магнитные свойства. \nСнижает: -.",
            "Al": "Алюминий.\nПовышает: Жаростойкость, окалиностойкость. \nСнижает: -.",
            "Ti": "Титан.\nПовышает: Прочность, коррозионная стойкость, обрабатываемость. \nСнижает: -.",
            "Nb": "Ниобий.\nПовышает: Коррозионная стойкость, устойчивость к кислотам. \nСнижает: -.",
            "Cu": "Медь.\nПовышает: Коррозионная стойкость, пластичность. \nСнижает: -.",
            "Ce": "Церий.\nПовышает: Пластичность, прочность. \nСнижает: -.",
            "Nd": "Неодим.\nПовышает: Качество поверхности. \nСнижает: Пористость.",
            "Cs": "Цезий.\nПовышает: Качество поверхности. \nСнижает: Пористость.",
            "La": "Лантан.\nПовышает: Качество поверхности. \nСнижает: Пористость.",
            "Sb": "Сурьма.\nПовышает: Отпускную хрупкость. \nСнижает: Качество поверхности литья."
        }

        # --- СЦЕНАРИЙ 1: Сравнение ГОСТов/источников для одного материала ---
        self.s1_current_material = None
        self.s1_compositions = []      # список dict по источникам для выбранного материала
        self.s1_elements = []          # отсортированный список всех элементов для pivot-таблицы

        # Виджеты сценария 1
        self.s1_area_combo = None
        self.s1_search_entry = None
        self.s1_mat_listbox = None
        self.s1_pivot_tree = None
        self.s1_sources_tree = None

        # --- СЦЕНАРИЙ 2: Подбор по целевому составу ---
        self.s2_target_tree = None
        self.s2_results_tree = None
        self.s2_details_tree = None
        self.s2_area_combo = None
        self.s2_influence_frame = None     # блок "Влияние элементов..."
        self._s2_popup_window = None       # всплывающий список элементов

        # Кэш всех комбинаций (материал + источник состава)
        self.s2_all_compositions = []       # список dict
        self.s2_candidate_by_item = {}      # item_id (Treeview) -> dict с данными кандидата

        self._setup_widgets()

    # =========================================================================
    # ОБЩЕЕ: инициализация вкладок
    # =========================================================================

    def _setup_widgets(self):
        """Создаёт внутренний Notebook с двумя сценариями."""
        main_notebook = ttk.Notebook(self)
        main_notebook.pack(fill="both", expand=True, padx=10, pady=10)

        tab_compare = ttk.Frame(main_notebook)   # сценарий 1
        tab_select = ttk.Frame(main_notebook)    # сценарий 2

        main_notebook.add(tab_compare, text="По стандартам для материала")
        main_notebook.add(tab_select, text="Подбор по целевому составу")

        self._setup_scenario1(tab_compare)
        self._setup_scenario2(tab_select)

    # =========================================================================
    # СЦЕНАРИЙ 1: ОДИН МАТЕРИАЛ, РАЗНЫЕ ИСТОЧНИКИ
    # =========================================================================

    def _setup_scenario1(self, parent):
        """UI для сравнения состава одного материала по разным источникам."""
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill="both", expand=True)

        # Левая панель (фильтры и выбор материала)
        left_frame = ttk.Frame(main_frame, width=250)
        left_frame.pack(side="left", fill="y", padx=(0, 10))
        left_frame.pack_propagate(False)

        ttk.Label(left_frame, text="Область применения:").pack(fill="x", pady=(0, 2))
        self.s1_area_combo = ttk.Combobox(left_frame, state="readonly")
        self.s1_area_combo.pack(fill="x", pady=(0, 8))
        self.s1_area_combo.bind("<<ComboboxSelected>>", self._s1_update_material_listbox)

        ttk.Label(left_frame, text="Поиск материала:").pack(fill="x", pady=(0, 2))
        self.s1_search_entry = ttk.Entry(left_frame)
        self.s1_search_entry.pack(fill="x", pady=(0, 8))
        self.s1_search_entry.bind("<KeyRelease>", self._s1_update_material_listbox)

        ttk.Label(left_frame, text="Материалы:").pack(fill="x", pady=(0, 2))
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill="both", expand=True)

        self.s1_mat_listbox = tk.Listbox(list_frame, exportselection=False)
        s1_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.s1_mat_listbox.yview)
        self.s1_mat_listbox.configure(yscrollcommand=s1_scroll.set)
        s1_scroll.pack(side="right", fill="y")
        self.s1_mat_listbox.pack(side="left", fill="both", expand=True)
        self.s1_mat_listbox.bind("<<ListboxSelect>>", self._s1_on_material_select)

        # Правая часть – две таблицы: pivot по элементам + список источников
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side="right", fill="both", expand=True)

        # Pivot-таблица: строки = элементы, столбцы = источники
        pivot_frame = ttk.LabelFrame(right_frame, text="Сравнение хим. состава по элементам", padding=5)
        pivot_frame.pack(fill="both", expand=True, pady=(0, 5))

        self.s1_pivot_tree = ttk.Treeview(pivot_frame, show="headings")
        p_vsb = ttk.Scrollbar(pivot_frame, orient="vertical", command=self.s1_pivot_tree.yview)
        p_hsb = ttk.Scrollbar(pivot_frame, orient="horizontal", command=self.s1_pivot_tree.xview)
        self.s1_pivot_tree.configure(yscrollcommand=p_vsb.set, xscrollcommand=p_hsb.set)
        self.s1_pivot_tree.grid(row=0, column=0, sticky="nsew")
        p_vsb.grid(row=0, column=1, sticky="ns")
        p_hsb.grid(row=1, column=0, sticky="ew")

        pivot_frame.grid_rowconfigure(0, weight=1)
        pivot_frame.grid_columnconfigure(0, weight=1)

        # Строки, где источники дают разные значения, подсвечиваем
        self.s1_pivot_tree.tag_configure("diff", background="#fffacd")  # светло-жёлтый

        # Список источников для выбранного материала
        sources_frame = ttk.LabelFrame(right_frame, text="Источники состава выбранного материала", padding=5)
        sources_frame.pack(fill="x", expand=False, pady=(5, 0))

        self.s1_sources_tree = ttk.Treeview(
            sources_frame,
            columns=("src", "comment", "base", "unit"),
            show="headings",
            height=4
        )
        self.s1_sources_tree.heading("src", text="Источник")
        self.s1_sources_tree.column("src", width=250, anchor="w")
        self.s1_sources_tree.heading("comment", text="Комментарий")
        self.s1_sources_tree.column("comment", width=250, anchor="w")
        self.s1_sources_tree.heading("base", text="Основа")
        self.s1_sources_tree.column("base", width=80, anchor="center")
        self.s1_sources_tree.heading("unit", text="Ед. изм.")
        self.s1_sources_tree.column("unit", width=80, anchor="center")

        s_vsb = ttk.Scrollbar(sources_frame, orient="vertical", command=self.s1_sources_tree.yview)
        self.s1_sources_tree.configure(yscrollcommand=s_vsb.set)
        self.s1_sources_tree.grid(row=0, column=0, sticky="nsew")
        s_vsb.grid(row=0, column=1, sticky="ns")

        sources_frame.grid_rowconfigure(0, weight=1)
        sources_frame.grid_columnconfigure(0, weight=1)

    def _s1_update_material_listbox(self, event=None):
        """Обновление списка материалов для сценария 1 (по области и поиску)."""
        if not self.s1_mat_listbox:
            return

        self.s1_mat_listbox.delete(0, tk.END)

        selected_area = self.s1_area_combo.get() or "Все"
        search_term = (self.s1_search_entry.get() or "").lower()

        for mat in self.app_data.materials:
            # учитываем только материалы с хоть одним источником хим. состава
            if not mat.get_compositions():
                continue

            meta = mat.data.get(Schema.METADATA, {})
            app_areas = meta.get(Schema.APP_AREA, [])

            if selected_area != "Все" and selected_area not in app_areas:
                continue

            display_name = mat.get_display_name()
            if search_term and search_term not in display_name.lower():
                continue

            self.s1_mat_listbox.insert(tk.END, display_name)

        # Автовыбор первого материала
        if self.s1_mat_listbox.size() > 0:
            self.s1_mat_listbox.selection_clear(0, tk.END)
            self.s1_mat_listbox.selection_set(0)
            self.s1_mat_listbox.event_generate("<<ListboxSelect>>")
        else:
            self.s1_current_material = None
            self._s1_clear_tables()

    def _s1_clear_tables(self):
        """Очищает pivot-таблицу и таблицу источников."""
        if self.s1_pivot_tree:
            self.s1_pivot_tree.delete(*self.s1_pivot_tree.get_children())
            self.s1_pivot_tree["columns"] = ()
        if self.s1_sources_tree:
            self.s1_sources_tree.delete(*self.s1_sources_tree.get_children())
        self.s1_compositions = []
        self.s1_elements = []

    def _s1_on_material_select(self, event=None):
        """Обработчик выбора материала в списке (сценарий 1)."""
        if not self.s1_mat_listbox:
            return
        selection = self.s1_mat_listbox.curselection()
        if not selection:
            self.s1_current_material = None
            self._s1_clear_tables()
            return

        name = self.s1_mat_listbox.get(selection[0])
        material = next((m for m in self.app_data.materials if m.get_display_name() == name), None)
        self.s1_current_material = material
        if not material:
            self._s1_clear_tables()
            return

        self._s1_build_material_view(material)

    def _s1_build_material_view(self, material):
        """
        Формирует данные по источникам хим. состава выбранного материала
        и обновляет две таблицы: источники + pivot по элементам.
        """
        self.s1_compositions = []
        self.s1_elements = []

        chem = material.get_compositions()
        source_manager = getattr(self.app_data, "source_manager", None)

        all_elements = set()

        for comp in chem:
            # Человекочитаемое имя источника (гибрид: новый/старый формат)
            source_name = "-"
            ref_id = comp.get("source_ref_id")
            if ref_id and source_manager:
                source_name = source_manager.get_name_by_id(ref_id)
            else:
                source_name = comp.get("composition_source", "") or "-"

            if comp.get("composition_subsource"):
                source_name = f"{source_name} ({comp['composition_subsource']})"

            comment = comp.get("comment", "")
            base_element = comp.get("base_element", "-")
            elements = comp.get("other_elements", [])
            elements_map = {e.get("element"): e for e in elements if e.get("element")}
            unit = elements[0].get("unit_value", "%") if elements else "%"

            all_elements.update(elements_map.keys())

            self.s1_compositions.append({
                "source_label": source_name,
                "comment": comment,
                "base_element": base_element,
                "unit": unit,
                "elements_map": elements_map
            })

        self.s1_elements = sorted(all_elements)
        self._s1_refresh_sources_table()
        self._s1_refresh_pivot_table()

    def _s1_refresh_sources_table(self):
        """Заполняет таблицу источников для выбранного материала (сценарий 1)."""
        self.s1_sources_tree.delete(*self.s1_sources_tree.get_children())

        for comp in self.s1_compositions:
            values = (
                comp["source_label"],
                comp["comment"],
                comp["base_element"],
                comp["unit"]
            )
            self.s1_sources_tree.insert("", "end", values=values)

    def _format_chem_value(self, elem_data):
        """
        Форматирование значения хим. элемента в диапазон/неравенство.
        Повторяет старую логику.
        """
        if not elem_data:
            return "-"

        min_v, max_v = elem_data.get("min_value"), elem_data.get("max_value")
        min_tol = elem_data.get("min_value_tolerance")
        max_tol = elem_data.get("max_value_tolerance")

        if min_v == 0:
            min_v = None
        if max_v == 0:
            max_v = None

        if min_v is not None and max_v is not None:
            min_tol_str = f"({min_tol}) " if min_tol not in (None, '') else ""
            max_tol_str = f" ({max_tol})" if max_tol not in (None, '') else ""
            return f"{min_tol_str}{min_v} - {max_v}{max_tol_str}"
        elif max_v is not None:
            max_tol_str = f" ({max_tol})" if max_tol not in (None, '') else ""
            return f"≤ {max_v}{max_tol_str}"
        elif min_v is not None:
            min_tol_str = f" ({min_tol})" if min_tol not in (None, '') else ""
            return f"≥ {min_v}{min_tol_str}"
        else:
            return "-"

    def _s1_refresh_pivot_table(self):
        """Перестраивает pivot-таблицу по элементам (строки) и источникам (столбцы)."""
        tree = self.s1_pivot_tree
        tree.delete(*tree.get_children())

        if not self.s1_compositions or not self.s1_elements:
            tree["columns"] = ()
            return

        # Базовые колонки: символ + название элемента
        columns = ["element", "name"]
        # Для каждого источника – своя колонка
        for idx, _ in enumerate(self.s1_compositions):
            columns.append(f"src_{idx}")

        tree["columns"] = columns

        tree.heading("element", text="Элемент")
        tree.column("element", width=70, anchor="center", stretch=False)

        tree.heading("name", text="Название")
        tree.column("name", width=150, anchor="w", stretch=True)

        for idx, comp in enumerate(self.s1_compositions):
            col_id = f"src_{idx}"
            header_text = comp["source_label"] or f"Источник {idx + 1}"
            tree.heading(col_id, text=header_text)
            tree.column(col_id, width=140, anchor="center", stretch=True)

        # Заполнение строк
        for elem_sym in self.s1_elements:
            # Название элемента берём из ELEMENTS_MAP в ChemicalCompositionTab
            elem_info = getattr(ChemicalCompositionTab, "ELEMENTS_MAP", {}).get(elem_sym, {})
            elem_name = elem_info.get("name", "")
            row_values = [elem_sym, elem_name]

            # Определяем, одинаковые ли значения по всем источникам для этого элемента,
            # сравнивая уже отформатированные строки (как в ячейках)
            reprs = []
            for comp in self.s1_compositions:
                elem_data = comp["elements_map"].get(elem_sym)
                formatted = self._format_chem_value(elem_data)
                row_values.append(formatted)
                reprs.append(formatted)

            unique_reprs = set(reprs)
            # Если у разных источников отличаются диапазоны/наличие – подсвечиваем строку
            # (если все строки одинаковые, в т.ч. "-", подсветки нет)
            tag = "diff" if len(unique_reprs) > 1 else ""

            tree.insert("", "end", values=row_values, tags=(tag,) if tag else ())

    # =========================================================================
    # СЦЕНАРИЙ 2: ПОДБОР ПО ЦЕЛЕВОМУ СОСТАВУ
    # =========================================================================

    def _setup_scenario2(self, parent):
        """UI для подбора материалов по целевому хим. составу."""
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill="both", expand=True)

        # Левая панель: область, целевой состав (таблица)
        left_frame = ttk.Frame(main_frame, width=320)
        left_frame.pack(side="left", fill="y", padx=(0, 10))
        left_frame.pack_propagate(False)

        ttk.Label(left_frame, text="Область применения:").pack(fill="x", pady=(0, 2))
        self.s2_area_combo = ttk.Combobox(left_frame, state="readonly")
        self.s2_area_combo.pack(fill="x", pady=(0, 8))
        self.s2_area_combo.bind("<<ComboboxSelected>>", self._s2_recalculate_results)

        target_frame = ttk.LabelFrame(left_frame, text="Целевой химический состав", padding=5)
        target_frame.pack(fill="both", expand=True)

        # Кнопки добавления/удаления строк — сразу под заголовком блока
        btn_frame = ttk.Frame(target_frame)
        btn_frame.pack(fill="x", pady=(0, 5))

        # Внешний фрейм с рамкой вокруг таблицы — визуально отделяет область ввода
        outer_table_frame = ttk.Frame(target_frame, borderwidth=1, relief="solid")
        outer_table_frame.pack(fill="both", expand=True)

        table_frame = ttk.Frame(outer_table_frame)
        table_frame.pack(fill="both", expand=True)

        self.s2_target_tree = create_editable_treeview(
            table_frame,
            on_update_callback=self._s2_recalculate_results
        )

        # Стиль для таблицы целевого состава:
        # увеличиваем высоту строки и заставляем фон быть однородным,
        # чтобы строки и области ввода были лучше различимы.
        style = ttk.Style()
        style.configure("Target.Treeview", rowheight=22, borderwidth=0)
        self.s2_target_tree.configure(show="headings", style="Target.Treeview")
        self.s2_target_tree["columns"] = ("elem", "target")

        self.s2_target_tree.heading("elem", text="Элемент")
        self.s2_target_tree.column("elem", width=80, anchor="center")
        self.s2_target_tree.heading("target", text="Target, %")
        self.s2_target_tree.column("target", width=80, anchor="center")

        t_vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.s2_target_tree.yview)
        self.s2_target_tree.configure(yscrollcommand=t_vsb.set)
        self.s2_target_tree.pack(side="left", fill="both", expand=True)
        t_vsb.pack(side="right", fill="y")

        # ПКМ по ячейке элемента — выбор из списка элементов
        self.s2_target_tree.bind("<Button-3>", self._s2_on_target_right_click)

        def add_target_row():
            # Добавляем строку с placeholder'ом в колонке "Элемент",
            # сразу выделяем и прокручиваем к ней, чтобы пользователь явно видел новую ячейку.
            item_id = self.s2_target_tree.insert("", "end", values=["-", ""])
            self.s2_target_tree.selection_set(item_id)
            self.s2_target_tree.focus(item_id)
            self.s2_target_tree.see(item_id)
            self._s2_recalculate_results()

        def del_target_row():
            sel = self.s2_target_tree.selection()
            for item in sel:
                self.s2_target_tree.delete(item)
            self._s2_recalculate_results()

        ttk.Button(btn_frame, text="+", width=2, command=add_target_row).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="-", width=2, command=del_target_row).pack(side="left", padx=2)

        ttk.Label(
            target_frame,
            text="Заполните элементы и целевые значения.\nТаблица справа будет обновляться автоматически.",
            foreground="gray"
        ).pack(fill="x", pady=(5, 0))

        # Правая часть: верхняя таблица – кандидаты, нижняя – детализация
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side="right", fill="both", expand=True)

        # Верхняя таблица – списки кандидатов
        results_frame = ttk.LabelFrame(right_frame, text="Результаты подбора материалов", padding=5)
        results_frame.pack(fill="both", expand=True, pady=(0, 5))

        self.s2_results_tree = ttk.Treeview(
            results_frame,
            show="headings",
            columns=("material", "source", "base", "matched", "total", "status")
        )
        self.s2_results_tree.heading("material", text="Материал")
        self.s2_results_tree.column("material", width=220, anchor="w")
        self.s2_results_tree.heading("source", text="Источник")
        self.s2_results_tree.column("source", width=200, anchor="w")
        self.s2_results_tree.heading("base", text="Основа")
        self.s2_results_tree.column("base", width=60, anchor="center")
        self.s2_results_tree.heading("matched", text="Совпавших")
        self.s2_results_tree.column("matched", width=80, anchor="center")
        self.s2_results_tree.heading("total", text="Всего")
        self.s2_results_tree.column("total", width=60, anchor="center")
        self.s2_results_tree.heading("status", text="Статус")
        self.s2_results_tree.column("status", width=130, anchor="center")

        r_vsb = ttk.Scrollbar(results_frame, orient="vertical", command=self.s2_results_tree.yview)
        r_hsb = ttk.Scrollbar(results_frame, orient="horizontal", command=self.s2_results_tree.xview)
        self.s2_results_tree.configure(yscrollcommand=r_vsb.set, xscrollcommand=r_hsb.set)
        self.s2_results_tree.grid(row=0, column=0, sticky="nsew")
        r_vsb.grid(row=0, column=1, sticky="ns")
        r_hsb.grid(row=1, column=0, sticky="ew")

        results_frame.grid_rowconfigure(0, weight=1)
        results_frame.grid_columnconfigure(0, weight=1)

        # Раскраска строк в зависимости от статуса
        self.s2_results_tree.tag_configure("full_match", background="#d0f0c0")     # светло-зелёный
        self.s2_results_tree.tag_configure("partial_match", background="#fffacd")  # светло-жёлтый
        self.s2_results_tree.tag_configure("no_match", background="#ffe4e1")       # розоватый

        self.s2_results_tree.bind("<<TreeviewSelect>>", self._s2_on_result_select)

        # Нижняя таблица – детализация по выбранному кандидату
        details_frame = ttk.LabelFrame(right_frame, text="Детализированное сравнение по выбранному источнику", padding=5)
        details_frame.pack(fill="both", expand=True, pady=(5, 0))

        self.s2_details_tree = ttk.Treeview(
            details_frame,
            show="headings",
            columns=("elem", "target", "min", "max", "min_tol", "max_tol", "state", "delta")
        )

        self.s2_details_tree.heading("elem", text="Элемент")
        self.s2_details_tree.column("elem", width=70, anchor="center")
        self.s2_details_tree.heading("target", text="Target, %")
        self.s2_details_tree.column("target", width=80, anchor="center")
        self.s2_details_tree.heading("min", text="Min, %")
        self.s2_details_tree.column("min", width=80, anchor="center")
        self.s2_details_tree.heading("max", text="Max, %")
        self.s2_details_tree.column("max", width=80, anchor="center")
        self.s2_details_tree.heading("min_tol", text="Допуск Min, %")
        self.s2_details_tree.column("min_tol", width=90, anchor="center")
        self.s2_details_tree.heading("max_tol", text="Допуск Max, %")
        self.s2_details_tree.column("max_tol", width=90, anchor="center")
        self.s2_details_tree.heading("state", text="Статус")
        self.s2_details_tree.column("state", width=120, anchor="center")
        self.s2_details_tree.heading("delta", text="Δ до границы, %")
        self.s2_details_tree.column("delta", width=120, anchor="center")

        d_vsb = ttk.Scrollbar(details_frame, orient="vertical", command=self.s2_details_tree.yview)
        d_hsb = ttk.Scrollbar(details_frame, orient="horizontal", command=self.s2_details_tree.xview)
        self.s2_details_tree.configure(yscrollcommand=d_vsb.set, xscrollcommand=d_hsb.set)
        self.s2_details_tree.grid(row=0, column=0, sticky="nsew")
        d_vsb.grid(row=0, column=1, sticky="ns")
        d_hsb.grid(row=1, column=0, sticky="ew")

        details_frame.grid_rowconfigure(0, weight=1)
        details_frame.grid_columnconfigure(0, weight=1)

        # Раскраска по ячейкам (через теги строк)
        self.s2_details_tree.tag_configure("in_range", background="#d0f0c0")
        self.s2_details_tree.tag_configure("out_of_range", background="#ffe4e1")
        self.s2_details_tree.tag_configure("missing", background="#f0f0f0")

        # Блок "Влияние элементов на свойства стали"
        influence_outer = ttk.LabelFrame(
            right_frame,
            text="Влияние элементов на свойства стали",
            padding=5
        )
        # Фиксируем высоту (примерно на 10 строк текста)
        influence_outer.pack(fill="x", expand=False, pady=(5, 0))
        influence_outer.configure(height=220)
        influence_outer.pack_propagate(False)

        # Внутри LabelFrame создаём Canvas + вертикальный скролл + внутренний фрейм
        influence_canvas = tk.Canvas(influence_outer, borderwidth=0, highlightthickness=0)
        influence_vsb = ttk.Scrollbar(influence_outer, orient="vertical", command=influence_canvas.yview)
        influence_inner = ttk.Frame(influence_canvas)

        influence_inner.bind(
            "<Configure>",
            lambda e: influence_canvas.configure(scrollregion=influence_canvas.bbox("all"))
        )

        influence_canvas.create_window((0, 0), window=influence_inner, anchor="nw")
        influence_canvas.configure(yscrollcommand=influence_vsb.set)

        influence_canvas.pack(side="left", fill="both", expand=True)
        influence_vsb.pack(side="right", fill="y")

        # Привязка прокрутки колесом мыши
        self.bind_mouse_wheel(influence_canvas)
        self.bind_mouse_wheel(influence_inner, influence_canvas)

        # Здесь будем создавать строки с влиянием элементов
        self.s2_influence_frame = influence_inner

    # =========================================================================
    # ОБЩИЙ МЕТОД ДЛЯ ViewerFrame
    # =========================================================================

    def update_lists(self):
        """
        Вызывается при загрузке/перезагрузке данных.
        Обновляет комбобоксы областей и кэширует все источники хим. состава.
        """
        areas = ["Все"] + getattr(self.app_data, "application_areas", [])

        # Сценарий 1
        if self.s1_area_combo:
            self.s1_area_combo.config(values=areas)
            if not self.s1_area_combo.get():
                self.s1_area_combo.set("Все")

        # Сценарий 2
        if self.s2_area_combo:
            self.s2_area_combo.config(values=areas)
            if not self.s2_area_combo.get():
                self.s2_area_combo.set("Все")

        # Перестраиваем кэш всех (материал, источник состава)
        self._s2_rebuild_all_compositions()

        # Обновляем список материалов для сценария 1
        self._s1_update_material_listbox()

        # Пересчитываем результаты подбора для сценария 2
        self._s2_recalculate_results()

    # =========================================================================
    # СЦЕНАРИЙ 2: ЛОГИКА ПОДБОРА
    # =========================================================================

    def _s2_rebuild_all_compositions(self):
        """Строит кэш всех комбинаций (материал + источник состава)."""
        self.s2_all_compositions = []
        source_manager = getattr(self.app_data, "source_manager", None)

        for mat in self.app_data.materials:
            chem = mat.get_compositions()
            if not chem:
                continue

            mat_name = mat.get_display_name()

            for comp in chem:
                elements = comp.get("other_elements", [])
                elements_map = {e.get("element"): e for e in elements if e.get("element")}
                base_element = comp.get("base_element", "-")
                unit = elements[0].get("unit_value", "%") if elements else "%"

                # Имя источника (как в сценарии 1)
                source_label = "-"
                ref_id = comp.get("source_ref_id")
                if ref_id and source_manager:
                    source_label = source_manager.get_name_by_id(ref_id)
                else:
                    source_label = comp.get("composition_source", "") or "-"

                if comp.get("composition_subsource"):
                    source_label = f"{source_label} ({comp['composition_subsource']})"

                self.s2_all_compositions.append({
                    "material": mat,
                    "material_name": mat_name,
                    "composition": comp,
                    "source_label": source_label,
                    "base_element": base_element,
                    "unit": unit,
                    "elements_map": elements_map
                })

    def _s2_collect_targets(self):
        """
        Собирает целевые значения из таблицы слева.
        Возвращает dict: { "C": float, "Cr": float, ... }.
        """
        targets = {}
        if not self.s2_target_tree:
            return targets

        for item_id in self.s2_target_tree.get_children():
            values = self.s2_target_tree.set(item_id)
            elem = (values.get("elem") or "").strip()
            if not elem:
                continue
            val_str = (values.get("target") or "").strip()
            if not val_str:
                continue
            t_val = safe_float(val_str)
            if t_val is None:
                continue
            targets[elem] = t_val

        return targets

    def _s2_recalculate_results(self, event=None):
        """Пересчитывает результаты подбора материалов по текущему целевому составу."""
        if not self.s2_results_tree:
            return

        # Сбрасываем детали и блок влияния элементов
        self.s2_details_tree.delete(*self.s2_details_tree.get_children())
        self._s2_clear_influence()
        self.s2_candidate_by_item.clear()

        targets = self._s2_collect_targets()
        self.s2_results_tree.delete(*self.s2_results_tree.get_children())

        if not targets:
            # Нечего подбирать – таблица пустая
            return

        selected_area = self.s2_area_combo.get() or "Все"

        candidates = []

        for cand in self.s2_all_compositions:
            mat = cand["material"]
            meta = mat.data.get(Schema.METADATA, {})
            app_areas = meta.get(Schema.APP_AREA, [])

            if selected_area != "Все" and selected_area not in app_areas:
                continue

            evaluated = self._s2_evaluate_candidate(cand, targets)
            if evaluated:
                candidates.append(evaluated)

        # Сортировка: сначала полные совпадения, затем частичные, затем без совпадений
        def sort_key(c):
            if c["status"] == "Полное совпадение":
                rank = 0
            elif c["status"] == "Частичное совпадение":
                rank = 1
            else:
                rank = 2
            # Чем больше совпавших и меньше max_delta – тем выше
            return (rank, -c["matched"], c["max_delta"], c["missing"], c["material_name"].lower())

        candidates.sort(key=sort_key)

        for c in candidates:
            item_values = (
                c["material_name"],
                c["source_label"],
                c["base_element"],
                str(c["matched"]),
                str(c["total_targets"]),
                c["status"]
            )
            if c["status"] == "Полное совпадение":
                tag = "full_match"
            elif c["status"] == "Частичное совпадение":
                tag = "partial_match"
            else:
                tag = "no_match"

            item_id = self.s2_results_tree.insert("", "end", values=item_values, tags=(tag,))
            self.s2_candidate_by_item[item_id] = c

        # Автовыбор первого кандидата
        first = self.s2_results_tree.get_children()
        if first:
            self.s2_results_tree.selection_set(first[0])
            self.s2_results_tree.event_generate("<<TreeviewSelect>>")

    def _s2_evaluate_candidate(self, cand, targets):
        """
        Оценивает один источник состава относительно целевого набора элементов.
        Учитывает допуски Min/Max (min_value_tolerance, max_value_tolerance).
        Возвращает dict с суммарными метриками и деталями по каждому элементу.
        """
        elements_map = cand["elements_map"]
        details = {}
        matched = 0
        missing = 0
        numeric_deltas = []

        for elem_sym, target_val in targets.items():
            elem_info = elements_map.get(elem_sym)
            detail = {
                "target": target_val,
                "min": None,
                "max": None,
                "min_tol": None,
                "max_tol": None,
                "state": "",
                "delta": None
            }

            # Элемента вообще нет в составе
            if not elem_info:
                detail["state"] = "missing"
                missing += 1
                details[elem_sym] = detail
                continue

            # Базовые границы
            min_v = safe_float(elem_info.get("min_value"))
            max_v = safe_float(elem_info.get("max_value"))
            # Допуски (абсолютные значения)
            min_tol = safe_float(elem_info.get("min_value_tolerance"))
            max_tol = safe_float(elem_info.get("max_value_tolerance"))

            detail["min"] = min_v
            detail["max"] = max_v
            detail["min_tol"] = min_tol
            detail["max_tol"] = max_tol

            # Если и Min, и Max отсутствуют — трактуем как отсутствие данных по элементу
            if min_v is None and max_v is None:
                detail["state"] = "missing"
                missing += 1
                details[elem_sym] = detail
                continue

            # Эффективные границы с учётом допусков (НОВАЯ ЛОГИКА):
            # - если заданы и min, и min_tol -> нижняя граница = min_tol (абсолютный предел);
            # - если задан только один из них -> нижняя граница = это значение;
            # - если нет ни min, ни min_tol -> нижняя граница = -inf.
            if min_v is not None and min_tol is not None:
                lower = min_tol
            elif min_v is not None:
                lower = min_v
            elif min_tol is not None:
                lower = min_tol
            else:
                lower = float("-inf")

            # Аналогично для верхней границы:
            # - если заданы и max, и max_tol -> верхняя граница = max_tol (абсолютный предел);
            # - если задан только один из них -> верхняя граница = это значение;
            # - если нет ни max, ни max_tol -> верхняя граница = +inf.
            if max_v is not None and max_tol is not None:
                upper = max_tol
            elif max_v is not None:
                upper = max_v
            elif max_tol is not None:
                upper = max_tol
            else:
                upper = float("inf")

            if lower <= target_val <= upper:
                detail["state"] = "in"
                matched += 1
            else:
                if target_val < lower:
                    detail["state"] = "below"
                    if lower != float("-inf"):
                        delta = lower - target_val
                        detail["delta"] = delta
                        numeric_deltas.append(delta)
                elif target_val > upper:
                    detail["state"] = "above"
                    if upper != float("inf"):
                        delta = target_val - upper
                        detail["delta"] = delta
                        numeric_deltas.append(delta)
                else:
                    detail["state"] = "missing"

            details[elem_sym] = detail

        total_targets = len(targets)

        if matched == total_targets and missing == 0 and not numeric_deltas:
            status = "Полное совпадение"
        elif matched > 0:
            status = "Частичное совпадение"
        else:
            status = "Нет совпадений"

        max_delta = max(numeric_deltas) if numeric_deltas else 0.0

        return {
            "material": cand["material"],
            "material_name": cand["material_name"],
            "source_label": cand["source_label"],
            "base_element": cand["base_element"],
            "unit": cand["unit"],
            "details": details,
            "matched": matched,
            "total_targets": total_targets,
            "missing": missing,
            "status": status,
            "max_delta": max_delta
        }

    def _s2_on_result_select(self, event=None):
        """Обновление таблицы деталей при выборе кандидата."""
        if not self.s2_results_tree or not self.s2_details_tree:
            return

        sel = self.s2_results_tree.selection()
        self.s2_details_tree.delete(*self.s2_details_tree.get_children())
        self._s2_clear_influence()

        if not sel:
            return

        item_id = sel[0]
        cand = self.s2_candidate_by_item.get(item_id)
        if not cand:
            return

        self._s2_fill_details(cand)

    def _s2_fill_details(self, cand):
        """Заполняет нижнюю таблицу деталями по выбранному кандидату."""
        tree = self.s2_details_tree
        tree.delete(*tree.get_children())

        unit = cand["unit"] or "%"

        # Обновляем заголовки с учётом единиц
        tree.heading("target", text=f"Target, {unit}")
        tree.heading("min", text=f"Min, {unit}")
        tree.heading("max", text=f"Max, {unit}")
        tree.heading("min_tol", text=f"Допуск Min, {unit}")
        tree.heading("max_tol", text=f"Допуск Max, {unit}")
        tree.heading("delta", text=f"Δ до границы, {unit}")

        # Человеко-читаемые статусы
        state_labels = {
            "in": "в диапазоне",
            "below": "ниже диапазона",
            "above": "выше диапазона",
            "missing": "нет данных",
            "": "нет данных"
        }

        for elem_sym in sorted(cand["details"].keys()):
            d = cand["details"][elem_sym]
            target = d["target"]
            min_v = d["min"]
            max_v = d["max"]
            min_tol = d.get("min_tol")
            max_tol = d.get("max_tol")
            state = d["state"]
            delta = d["delta"]

            def fmt(x, prec=4):
                if x is None:
                    return "-"
                s = f"{x:.{prec}f}".rstrip('0').rstrip('.')
                return s

            target_str = fmt(target, prec=4)
            min_str = fmt(min_v, prec=4)
            max_str = fmt(max_v, prec=4)
            min_tol_str = fmt(min_tol, prec=4)
            max_tol_str = fmt(max_tol, prec=4)
            delta_str = fmt(delta, prec=4) if delta is not None and delta > 0 else "-"

            label = state_labels.get(state, "нет данных")

            if state == "in":
                tag = "in_range"
            elif state == "missing":
                tag = "missing"
            else:
                tag = "out_of_range"

            # ВСТАВЛЯЕМ СТРОКУ ВСЕГДА, независимо от статуса
            tree.insert(
                "",
                "end",
                values=(elem_sym, target_str, min_str, max_str, min_tol_str, max_tol_str, label, delta_str),
                tags=(tag,)
            )

        # После заполнения таблицы обновляем блок влияния элементов
        self._s2_update_influence(cand)

    def _s2_clear_influence(self):
        """Очищает блок 'Влияние элементов на свойства стали'."""
        if not self.s2_influence_frame:
            return
        for w in self.s2_influence_frame.winfo_children():
            w.destroy()

    def _s2_update_influence(self, cand):
        """Заполняет блок влияния элементов на свойства стали по выбранному кандидату."""
        if not self.s2_influence_frame:
            return

        self._s2_clear_influence()

        elements_map = getattr(ChemicalCompositionTab, "ELEMENTS_MAP", {})

        for elem_sym in sorted(cand["details"].keys()):
            tip = self.element_tooltips.get(elem_sym)
            elem_info = elements_map.get(elem_sym, {})
            elem_name = elem_info.get("name", elem_sym)

            # Строка заголовка: "Углерод: C"
            header_line = f"{elem_name}: {elem_sym}"

            improves_line = ""
            reduces_line = ""

            if tip:
                # Ожидаемый формат:
                #   1-я строка: "Углерод."
                #   2-я: "Повышает: ..."
                #   3-я: "Снижает: ..."
                raw_lines = [ln.strip() for ln in tip.splitlines() if ln.strip()]
                for ln in raw_lines:
                    if ln.startswith("Повышает"):
                        improves_line = f"    - {ln}"
                    elif ln.startswith("Снижает"):
                        reduces_line = f"    - {ln}"
            # Если подсказки нет — всё равно выводим хотя бы заголовок
            lines_to_show = [header_line]
            if improves_line:
                lines_to_show.append(improves_line)
            if reduces_line:
                lines_to_show.append(reduces_line)

            text = "\n".join(lines_to_show)

            lbl = ttk.Label(
                self.s2_influence_frame,
                text=text,
                wraplength=700,
                justify="left",
                anchor="w"
            )
            lbl.pack(fill="x", anchor="w", pady=1)

    def _s2_on_target_right_click(self, event):
        """ПКМ по ячейке 'Элемент' в таблице целевого состава — выбор элемента из списка."""
        if not self.s2_target_tree:
            return

        region = self.s2_target_tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        row_id = self.s2_target_tree.identify_row(event.y)
        column = self.s2_target_tree.identify_column(event.x)

        # Интересует только первая колонка ('elem')
        if column != "#1" or not row_id:
            return

        self.s2_target_tree.selection_set(row_id)
        self.s2_target_tree.focus(row_id)
        self._s2_show_element_picker(event, row_id)

    def _s2_show_element_picker(self, event, row_id):
        """Всплывающий список элементов (как в ChemicalCompositionTab)."""
        # Закрываем предыдущее окно, если есть
        if self._s2_popup_window:
            self._s2_popup_window.destroy()
            self._s2_popup_window = None

        self._s2_popup_window = tk.Toplevel(self)
        self._s2_popup_window.wm_overrideredirect(True)
        self._s2_popup_window.geometry(f"+{event.x_root}+{event.y_root}")

        frame = ttk.Frame(self._s2_popup_window, relief="solid", borderwidth=1)
        frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        listbox = tk.Listbox(
            frame,
            height=10,
            width=30,
            yscrollcommand=scrollbar.set,
            exportselection=False
        )
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        # Берём справочник элементов из ChemicalCompositionTab
        elements_map = getattr(ChemicalCompositionTab, "ELEMENTS_MAP", {})
        sorted_items = sorted(elements_map.items(), key=lambda x: x[1].get("name", ""))

        items_data = []
        for symbol, data in sorted_items:
            name = data.get("name", symbol)
            display_text = f"{name} ({symbol})"
            listbox.insert(tk.END, display_text)
            items_data.append((symbol, name))

        def on_select(evt):
            sel_idx = listbox.curselection()
            if not sel_idx:
                return
            idx = sel_idx[0]
            symbol, _name = items_data[idx]

            current_values = list(self.s2_target_tree.item(row_id, "values"))
            # 0-й столбец — символ элемента
            if len(current_values) < 2:
                current_values = [symbol, ""]
            else:
                current_values[0] = symbol
            self.s2_target_tree.item(row_id, values=current_values)

            self._s2_recalculate_results()

            if self._s2_popup_window:
                self._s2_popup_window.destroy()
                self._s2_popup_window = None

        listbox.bind("<<ListboxSelect>>", on_select)
        listbox.bind("<Escape>", lambda e: self._s2_popup_window.destroy())

        self._s2_popup_window.bind("<FocusOut>", lambda e: self._s2_popup_window.destroy())

        def _on_mousewheel(evt):
            listbox.yview_scroll(int(-1 * (evt.delta / 120)), "units")
            return "break"

        listbox.bind("<MouseWheel>", _on_mousewheel)
        listbox.focus_set()


class AshbyDiagramTab(ttk.Frame):
    """Вкладка для построения диаграмм Эшби по классам материалов."""

    def __init__(self, parent, app_data, main_app):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app

        # Карта доступных свойств для осей (включая температуру)
        self.ashby_properties_map = {
            "temperature": {"name": "Температура", "symbol": "T", "unit": "°С"},
            **ALL_PROPERTIES_MAP
        }
        self.ashby_prop_keys = list(self.ashby_properties_map.keys())
        self.ashby_prop_names = [
            f"{info['name']} ({info.get('symbol', '')})"
            for info in self.ashby_properties_map.values()
        ]

        # Пул классов для текущей области (для поиска)
        self.class_search_pool = []

        self._setup_widgets()

    def _setup_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        controls_frame = ttk.Frame(main_frame, width=300)
        controls_frame.pack(side="left", fill="y", padx=(0, 10))
        controls_frame.pack_propagate(False)

        # Область применения
        ttk.Label(controls_frame, text="Область применения:").pack(fill="x", pady=(0, 2))
        self.area_combo = ttk.Combobox(controls_frame, state="readonly")
        self.area_combo.pack(fill="x", pady=(0, 10))
        self.area_combo.bind("<<ComboboxSelected>>", self._update_search_pool)

        # Ось X
        ttk.Label(controls_frame, text="Ось X:").pack(fill="x", pady=(5, 2))
        self.x_axis_combo = ttk.Combobox(controls_frame, state="readonly", values=self.ashby_prop_names)
        self.x_axis_combo.pack(fill="x", pady=(0, 5))
        self.x_axis_combo.bind("<<ComboboxSelected>>", self._on_axis_change)

        # Ось Y
        ttk.Label(controls_frame, text="Ось Y:").pack(fill="x", pady=(5, 2))
        self.y_axis_combo = ttk.Combobox(controls_frame, state="readonly", values=self.ashby_prop_names)
        self.y_axis_combo.pack(fill="x", pady=(0, 10))
        self.y_axis_combo.bind("<<ComboboxSelected>>", self._on_axis_change)

        # Поиск класса
        ttk.Label(controls_frame, text="Поиск структурного класса:").pack(fill="x", pady=(5, 2))
        self.search_entry = ttk.Entry(controls_frame)
        self.search_entry.pack(fill="x", pady=(0, 5))
        self.search_entry.bind("<KeyRelease>", self._filter_search_results)

        # Список результатов поиска классов
        search_list_frame = ttk.LabelFrame(controls_frame, text="Результаты поиска")
        search_list_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.search_listbox = tk.Listbox(search_list_frame, exportselection=False)
        search_scrollbar = ttk.Scrollbar(search_list_frame, orient="vertical", command=self.search_listbox.yview)
        self.search_listbox.config(yscrollcommand=search_scrollbar.set)
        search_scrollbar.pack(side="right", fill="y")
        self.search_listbox.pack(side="left", fill="both", expand=True)
        self.search_listbox.bind("<Double-1>", self._add_material_to_selection)  # теперь добавляем класс

        # Список выбранных классов
        selected_list_frame = ttk.LabelFrame(controls_frame, text="Выбранные классы")
        selected_list_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.selected_listbox = tk.Listbox(selected_list_frame, exportselection=False)
        selected_scrollbar = ttk.Scrollbar(selected_list_frame, orient="vertical", command=self.selected_listbox.yview)
        self.selected_listbox.config(yscrollcommand=selected_scrollbar.set)
        selected_scrollbar.pack(side="right", fill="y")
        self.selected_listbox.pack(side="left", fill="both", expand=True)
        self.selected_listbox.bind("<Double-1>", self._remove_material_from_selection)

        # Кнопки
        plot_button = ttk.Button(controls_frame, text="Построить диаграмму", command=self._plot_diagram)
        plot_button.pack(fill="x", pady=(0, 5))

        reset_button = ttk.Button(controls_frame, text="Сбросить", command=self._reset_selection)
        reset_button.pack(fill="x")

        # Область графика
        self.plot_frame = ttk.Frame(main_frame)
        self.plot_frame.pack(side="right", fill="both", expand=True)
        fig = Figure(figsize=(8, 6), dpi=100)
        self.ax = fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        toolbar = NavigationToolbar2Tk(self.canvas, self.plot_frame)
        toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Значения по умолчанию для осей
        if self.ashby_prop_names:
            # По умолчанию X — Предел текучести, Y — Температура (если они есть в списке)
            try:
                x_default_index = self.ashby_prop_names.index("Предел текучести (σ_0,2)")
            except ValueError:
                x_default_index = 0
            try:
                y_default_index = self.ashby_prop_names.index("Температура (T)")
            except ValueError:
                y_default_index = min(1, len(self.ashby_prop_names) - 1)

            self.x_axis_combo.current(x_default_index)
            self.y_axis_combo.current(y_default_index)

    # === Работа со списками классов ===

    def update_lists(self):
        """Обновляет список областей и доступных классов (по всей базе)."""
        areas = ["Все"] + self.app_data.application_areas
        self.area_combo.config(values=areas)
        self.area_combo.set("Все")

        self._update_search_pool()

    def _update_search_pool(self, event=None):
        """
        Обновляет пул классов для текущей области применения.
        В search_listbox показываются классы, для которых есть хотя бы один материал
        с выбранной областью.
        """
        selected_area = self.area_combo.get()
        if not selected_area:
            selected_area = "Все"

        classes = set()
        for mat in self.app_data.materials:
            meta = mat.data.get(Schema.METADATA, {})
            app_areas = meta.get(Schema.APP_AREA, [])
            if selected_area != "Все" and selected_area not in app_areas:
                continue
            cls = meta.get("classification", {}).get("classification_class", "")
            if cls:
                classes.add(cls)

        self.class_search_pool = sorted(classes)
        self._filter_search_results()

    def _filter_search_results(self, event=None):
        """Фильтрация списка классов по тексту поиска."""
        search_term = self.search_entry.get().lower()
        self.search_listbox.delete(0, tk.END)

        for cls_name in self.class_search_pool:
            if search_term in cls_name.lower():
                self.search_listbox.insert(tk.END, cls_name)

    def _add_material_to_selection(self, event):
        """Добавляет класс из результатов поиска в список выбранных классов."""
        selected_indices = self.search_listbox.curselection()
        if not selected_indices:
            return

        class_name = self.search_listbox.get(selected_indices[0])
        current_selected = self.selected_listbox.get(0, tk.END)

        if class_name not in current_selected:
            self.selected_listbox.insert(tk.END, class_name)

    def _remove_material_from_selection(self, event):
        """Удаляет класс из списка выбранных."""
        selected_indices = self.selected_listbox.curselection()
        if not selected_indices:
            return

        self.selected_listbox.delete(selected_indices[0])

    def _reset_selection(self):
        """Сбрасывает выбранные классы и перерисовывает диаграмму."""
        self.selected_listbox.delete(0, tk.END)
        self._plot_diagram()

    # === Оси X/Y ===

    def _on_axis_change(self, event=None):
        """
        Обновляет списки значений в комбобоксах осей, чтобы не было одинакового выбора.
        И перерисовывает диаграмму.
        """
        x_selection = self.x_axis_combo.get()
        y_selection = self.y_axis_combo.get()

        if x_selection:
            self.y_axis_combo['values'] = [name for name in self.ashby_prop_names if name != x_selection]
        else:
            self.y_axis_combo['values'] = self.ashby_prop_names

        if y_selection:
            self.x_axis_combo['values'] = [name for name in self.ashby_prop_names if name != y_selection]
        else:
            self.x_axis_combo['values'] = self.ashby_prop_names

        # Восстанавливаем текущее значение после обновления values
        if x_selection and x_selection in self.x_axis_combo['values']:
            self.x_axis_combo.set(x_selection)
        if y_selection and y_selection in self.y_axis_combo['values']:
            self.y_axis_combo.set(y_selection)

        self._plot_diagram()

    # === Вспомогательные функции для расчета точек ===

    def _get_axis_value(self, material, cat_idx, prop_key, temp):
        """Возвращает значение свойства для оси при заданной температуре."""
        if prop_key == "temperature":
            return temp

        if PROPERTIES.is_physical(prop_key):
            return material.get_interpolated_property(prop_key, temp)

        if PROPERTIES.is_mechanical(prop_key):
            if cat_idx is None:
                return None
            return material.get_interpolated_property(prop_key, temp, category_idx=cat_idx)

        return None

    def _compute_series_points(self, material, cat_idx, x_prop_key, y_prop_key):
        """
        Строит набор точек (X, Y) для одной серии:
        - material: объект Material
        - cat_idx: индекс категории прочности или None (если не используется)
        - x_prop_key, y_prop_key: ключи свойств из ashby_properties_map
        Возвращает: (xs, ys), где xs, ys — списки чисел.
        """
        temps = set()

        # Собираем температуры из данных по обоим свойствам
        for prop_key in (x_prop_key, y_prop_key):
            if prop_key == "temperature":
                continue

            if PROPERTIES.is_physical(prop_key):
                prop_data = material.get_physical_data(prop_key) or {}
                for t_raw, _ in prop_data.get(Schema.TEMP_PAIRS, []):
                    t_val = MathUtils.safe_float(t_raw)
                    if t_val is not None:
                        temps.add(t_val)

            elif PROPERTIES.is_mechanical(prop_key) and cat_idx is not None:
                cats = material.get_strength_categories()
                if 0 <= cat_idx < len(cats):
                    prop_data = Material.get_category_prop_data(cats[cat_idx], prop_key) or {}
                    for t_raw, _ in prop_data.get(Schema.TEMP_PAIRS, []):
                        t_val = MathUtils.safe_float(t_raw)
                        if t_val is not None:
                            temps.add(t_val)

        if not temps:
            return [], []

        temps = sorted(temps)
        xs, ys = [], []

        for t in temps:
            x_val = self._get_axis_value(material, cat_idx, x_prop_key, t)
            y_val = self._get_axis_value(material, cat_idx, y_prop_key, t)
            if x_val is not None and y_val is not None:
                xs.append(x_val)
                ys.append(y_val)

        return xs, ys

    def _compute_convex_hull(self, points):
        """
        Строит выпуклую оболочку для множества точек (x, y)
        методом монотонной цепи (алгоритм Эндрю).
        Возвращает список вершин оболочки в порядке обхода.
        """
        # Убираем дубликаты и сортируем
        points = sorted(set(points))
        if len(points) <= 1:
            return points

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        lower = []
        for p in points:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)

        upper = []
        for p in reversed(points):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)

        # Соединяем нижнюю и верхнюю цепи, убирая последнюю точку каждой (она повторяется)
        return lower[:-1] + upper[:-1]

    def _get_series_color(self, index):
        """
        Возвращает цвет для кривой по её порядковому номеру.
        Используем равномерное распределение оттенков по HSV,
        чтобы можно было нарисовать сколь угодно много кривых
        с максимально разными цветами.
        """
        golden_ratio_conjugate = 0.618033988749895
        h = (index * golden_ratio_conjugate) % 1.0  # оттенок
        s = 0.9
        v = 0.9
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    # === Построение диаграммы ===

    def _plot_diagram(self):
        """Строит диаграмму Эшби по выбранным классам."""
        x_selection_text = self.x_axis_combo.get()
        y_selection_text = self.y_axis_combo.get()
        if not x_selection_text or not y_selection_text:
            return

        try:
            x_prop_index = self.ashby_prop_names.index(x_selection_text)
            y_prop_index = self.ashby_prop_names.index(y_selection_text)
        except ValueError:
            return

        x_prop_key = self.ashby_prop_keys[x_prop_index]
        y_prop_key = self.ashby_prop_keys[y_prop_index]
        x_prop_info = self.ashby_properties_map[x_prop_key]
        y_prop_info = self.ashby_properties_map[y_prop_key]

        selected_classes = self.selected_listbox.get(0, tk.END)
        selected_area = self.area_combo.get()
        if not selected_area:
            selected_area = "Все"

        self.ax.clear()

        # Цвета ДЛЯ ОБЛАСТЕЙ (классы) оставляем фиксированными, как раньше
        class_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
                        '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
                        '#bcbd22', '#17becf']

        # Отдельный счётчик для всех кривых по материалам/КП,
        # чтобы каждая кривая была с уникальным цветом.
        series_index = 0

        x_is_mech = PROPERTIES.is_mechanical(x_prop_key)
        y_is_mech = PROPERTIES.is_mechanical(y_prop_key)

        for idx_class, class_name in enumerate(selected_classes):
            class_color = class_colors[idx_class % len(class_colors)]
            class_points = []  # Для выпуклой оболочки по этому классу

            for mat in self.app_data.materials:
                meta = mat.data.get(Schema.METADATA, {})
                app_areas = meta.get(Schema.APP_AREA, [])
                cls = meta.get("classification", {}).get("classification_class", "")

                if cls != class_name:
                    continue
                if selected_area != "Все" and selected_area not in app_areas:
                    continue

                cats = mat.get_strength_categories()

                # Если хотя бы одна ось механическая — рисуем по категориям
                if x_is_mech or y_is_mech:
                    for cat_idx, cat in enumerate(cats):
                        cat_name = Material.category_name(cat)
                        series_label = f"{mat.get_display_name()} {cat_name}".strip()

                        xs, ys = self._compute_series_points(mat, cat_idx, x_prop_key, y_prop_key)
                        # Цвет для данной кривой (уникальный по series_index)
                        curve_color = self._get_series_color(series_index)
                        series_index += 1

                        if xs and ys:
                            class_points.extend(zip(xs, ys))
                            self.ax.plot(xs, ys,
                                         marker='o', linestyle='-',
                                         label=series_label,
                                         color=curve_color)
                        else:
                            # Нет данных по выбранным свойствам для этой категории
                            self.ax.plot([], [],
                                         marker='o', linestyle='-',
                                         label=f"{series_label} (нет данных)",
                                         color=curve_color)
                else:
                    # Оси только по физическим свойствам/температуре — одна кривая на материал
                    series_label = mat.get_display_name()
                    xs, ys = self._compute_series_points(mat, None, x_prop_key, y_prop_key)
                    curve_color = self._get_series_color(series_index)
                    series_index += 1

                    if xs and ys:
                        class_points.extend(zip(xs, ys))
                        self.ax.plot(xs, ys,
                                     marker='o', linestyle='-',
                                     label=series_label,
                                     color=curve_color)
                    else:
                        self.ax.plot([], [],
                                     marker='o', linestyle='-',
                                     label=f"{series_label} (нет данных)",
                                     color=curve_color)

            # Заливка выпуклой оболочки по всем точкам данного класса
            if len(class_points) >= 3:
                hull = self._compute_convex_hull(class_points)
                if len(hull) >= 3:
                    hx = [p[0] for p in hull] + [hull[0][0]]
                    hy = [p[1] for p in hull] + [hull[0][1]]
                    # Для области оставляем цвет класса (class_color)
                    self.ax.fill(hx, hy, color=class_color, alpha=0.15, zorder=0)

        self.ax.set_xlabel(f"{x_prop_info['name']} [{x_prop_info['unit']}]")
        self.ax.set_ylabel(f"{y_prop_info['name']} [{y_prop_info['unit']}]")
        if selected_classes:
            self.ax.set_title("Диаграмма Эшби по классам: " + ", ".join(selected_classes))
        else:
            self.ax.set_title("Диаграмма Эшби (классы не выбраны)")

        if selected_classes:
            # Добавляем в легенду отдельные элементы для классов (цвет областей)
            handles, labels = self.ax.get_legend_handles_labels()
            # class_color_map заполняется в цикле выше
            # (если ещё нет, то можно завести локальный словарь там:
            #   class_color_map = {}; class_color_map[class_name] = class_color)
            # Предполагаем, что он существует в замыкании этого метода:
            # поэтому нужно добавить его создание в начале _plot_diagram, до цикла:
            #   class_color_map = {}
            #   ...
            #   class_color_map[class_name] = class_color
            for idx_class, class_name in enumerate(selected_classes):
                # Цвет области берём из той же схемы, что и при заливке
                class_color = class_colors[idx_class % len(class_colors)]
                patch = Patch(
                    facecolor=class_color,
                    edgecolor='none',
                    alpha=0.15,
                    label=f"Класс: {class_name}"
                )
                handles.append(patch)
                labels.append(f"Класс: {class_name}")

            self.ax.legend(handles, labels, fontsize='small')

        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.canvas.draw()


# ======================================================================================
# БЛОК 6: ВКЛАДКИ РЕДАКТОРА
# ======================================================================================


class SinglePropertyEditor(ttk.Frame):
    """
    Переиспользуемый компонент для редактирования одного свойства.
    Содержит: Поля (Ед. изм, Источник свойств, Комментарий), Таблицу точек и График.
    """

    def __init__(self, parent, prop_key, prop_info):
        super().__init__(parent)
        self.prop_key = prop_key
        self.prop_info = prop_info
        self._temperature_dependent = PROPERTIES.supports_temperature(prop_key)

        # Менеджер источников и кэш отображения
        self.source_manager = None
        self._source_name_to_id = {}
        self._source_id_to_name = {}

        # Данные графика
        self.fig = None
        self.ax = None
        self.canvas = None
        self.tree = None
        self.scalar_value_entry = None

        self._setup_layout()

    def set_source_manager(self, source_manager):
        """Устанавливает менеджер источников и обновляет список источников свойств."""
        self.source_manager = source_manager
        self._refresh_source_list()

    def _refresh_source_list(self):
        """Обновляет список источников свойств для выпадающего списка."""
        self._source_name_to_id = {}
        self._source_id_to_name = {}

        if not self.source_manager:
            self.source_combo.config(values=[])
            return

        try:
            sources = self.source_manager.get_all("property_sources")
        except TypeError:
            # На случай старого интерфейса SourceService без групп
            sources = self.source_manager.get_all()

        names = []
        for src in sources:
            sid = src.get("id_source")
            name = src.get("name_source", "Без названия")
            if not sid:
                continue
            self._source_name_to_id[name] = sid
            self._source_id_to_name[sid] = name
            names.append(name)

        self.source_combo.config(values=sorted(names))

    def _setup_layout(self):
        # Разделение на левую (поля) и правую (график) части
        content_frame = ttk.Frame(self)
        content_frame.pack(fill="both", expand=True)

        left_panel = ttk.Frame(content_frame)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right_panel = ttk.Frame(content_frame)
        if self._temperature_dependent:
            right_panel.pack(side="right", fill="both", expand=True)

        # --- ЛЕВАЯ ПАНЕЛЬ (ПОЛЯ ВЕРТИКАЛЬНО) ---
        left_panel.columnconfigure(1, weight=1)

        # 1. Единица измерения
        ttk.Label(left_panel, text="Ед. изм:").grid(row=0, column=0, sticky="w", pady=2)

        unit_type = self.prop_info.get("unit_type")
        units = UnitManager.get_units(unit_type) if unit_type else [self.prop_info["unit"]]

        self.unit_combo = ttk.Combobox(left_panel, values=units, state="readonly", width=15)
        self.unit_combo.grid(row=0, column=1, sticky="we", pady=2)
        if self.prop_info["unit"] in units:
            self.unit_combo.set(self.prop_info["unit"])

        # При смене единицы обновляем график
        self.unit_combo.bind("<<ComboboxSelected>>", lambda e: self.update_graph())

        # 2. Источник свойств (вместо Под-источника)
        ttk.Label(left_panel, text="Источник свойств:").grid(row=1, column=0, sticky="w", pady=2)
        self.source_combo = ttk.Combobox(left_panel, state="readonly")
        self.source_combo.grid(row=1, column=1, sticky="we", pady=2)

        # 3. Комментарий
        ttk.Label(left_panel, text="Комментарий:").grid(row=2, column=0, sticky="w", pady=2)
        self.comment_entry = ttk.Entry(left_panel)
        self.comment_entry.grid(row=2, column=1, sticky="we", pady=2)

        if self._temperature_dependent:
            self._setup_temperature_widgets(left_panel, right_panel)
        else:
            self._setup_scalar_widgets(left_panel)

    def _setup_scalar_widgets(self, left_panel):
        """Скалярные свойства (δ, ψ, угол): одно значение без таблицы T и графика."""
        ttk.Label(left_panel, text="Значение:").grid(row=3, column=0, sticky="w", pady=2)
        self.scalar_value_entry = ttk.Entry(left_panel)
        self.scalar_value_entry.grid(row=3, column=1, sticky="we", pady=2)

    def _setup_temperature_widgets(self, left_panel, right_panel):
        # 4. Таблица
        table_frame = ttk.Frame(left_panel)
        table_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=5)
        left_panel.rowconfigure(3, weight=1)

        self.tree = create_editable_treeview(table_frame, on_update_callback=self.update_graph)

        self.tree.configure(show="headings")
        self.tree["columns"] = ("temp", "value")

        self.tree.heading("temp", text="T, °C")
        self.tree.column("temp", width=130, anchor="center")

        self.tree.heading("value", text="Значение")
        self.tree.column("value", width=130, anchor="center")

        self.tree.pack(side="left", fill="both", expand=True)

        # Кнопки +/-
        btn_frame = ttk.Frame(table_frame)
        btn_frame.pack(side="left", fill="y", padx=5)
        ttk.Button(btn_frame, text="+", width=2,
                   command=lambda: (self.tree.insert("", "end", values=["0", "0"]), self.update_graph())).pack(pady=2)
        ttk.Button(btn_frame, text="-", width=2,
                   command=lambda: (self.tree.delete(self.tree.selection()), self.update_graph())).pack(pady=2)

        # --- ПРАВАЯ ПАНЕЛЬ (ГРАФИК) ---
        self.fig = Figure(figsize=(4, 3), dpi=90)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right_panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def update_graph(self):
        """Перерисовывает график на основе данных из таблицы."""
        if not self._temperature_dependent or not self.tree or not self.ax:
            return
        points = []
        for item in self.tree.get_children():
            v = self.tree.set(item)
            t_val = safe_float(v["temp"])
            v_val = safe_float(v["value"])
            if t_val is not None and v_val is not None:
                points.append((t_val, v_val))

        points.sort(key=lambda p: p[0])

        self.ax.clear()
        if points:
            ts, vs = zip(*points)
            self.ax.plot(ts, vs, 'o-', markersize=4)

        unit = self.unit_combo.get()
        self.ax.set_ylabel(unit, fontsize=8)
        self.ax.set_xlabel("T, °C", fontsize=8)
        self.ax.grid(True, linestyle='--', alpha=0.6)
        self.ax.tick_params(labelsize=8)
        self.fig.tight_layout()
        self.canvas.draw()

    def set_data(self, prop_data):
        """Заполняет поля данными из словаря (учитывает старый и новый формат источников)."""
        if prop_data is None:
            prop_data = {}

        # Обновляем список источников (на случай, если менеджер добавил новые)
        self._refresh_source_list()

        # Единицы
        unit = prop_data.get("value_unit") or prop_data.get("property_unit")
        if unit and unit in self.unit_combo['values']:
            self.unit_combo.set(unit)
        else:
            self.unit_combo.set(self.prop_info["unit"])

        # Источник: сначала пытаемся по source_ref_id, потом по legacy полю property_subsource
        source_to_show = ""
        source_id = prop_data.get("source_ref_id")
        if source_id and self.source_manager:
            try:
                src = self.source_manager.get_source_by_id(source_id)
            except TypeError:
                src = None
            if src:
                source_to_show = src.get("name_source", "")

        if not source_to_show:
            source_to_show = prop_data.get("property_subsource", "") or ""

        self.source_combo.set(source_to_show)

        # Комментарий
        self.comment_entry.delete(0, tk.END)
        self.comment_entry.insert(0, prop_data.get("comment", ""))

        if self._temperature_dependent:
            for i in self.tree.get_children():
                self.tree.delete(i)
            for t, v in prop_data.get("temperature_value_pairs", []):
                self.tree.insert("", "end", values=[t, v])
            self.update_graph()
        elif self.scalar_value_entry is not None:
            self.scalar_value_entry.delete(0, tk.END)
            pairs = prop_data.get("temperature_value_pairs", [])
            if pairs:
                self.scalar_value_entry.insert(0, str(pairs[0][1]))

    def get_data(self):
        """Собирает данные из полей (поддержка нового и старого формата источников)."""
        source_name = self.source_combo.get().strip()
        comment = self.comment_entry.get().strip()
        has_meta = bool(source_name or comment)

        if self._temperature_dependent:
            pairs = []
            for item in self.tree.get_children():
                v = self.tree.set(item)
                t_val = safe_float(v["temp"])
                v_val = safe_float(v["value"])
                if t_val is not None and v_val is not None:
                    pairs.append([t_val, v_val])
        else:
            pairs = []
            if self.scalar_value_entry is not None:
                scalar_val = safe_float(self.scalar_value_entry.get())
                if scalar_val is not None:
                    pairs.append([20.0, scalar_val])

        if not pairs and not has_meta:
            return None

        result = {
            "temperature_value_pairs": pairs,
            "value_unit": self.unit_combo.get(),
            "comment": comment
        }

        # Источник:
        # если имя сопоставимо с id из SourceService -> записываем source_ref_id + дублируем имя
        # иначе просто legacy property_subsource.
        if source_name:
            if self.source_manager:
                if not self._source_name_to_id:
                    self._refresh_source_list()
                src_id = self._source_name_to_id.get(source_name)
                if src_id:
                    result["source_ref_id"] = src_id
                    result["property_subsource"] = source_name
                else:
                    result["property_subsource"] = source_name
            else:
                result["property_subsource"] = source_name

        return result


class GeneralDataTab(ttk.Frame, ScrollableMixin):
    def __init__(self, parent, app_data):
        super().__init__(parent, padding=10)
        self.app_data = app_data
        self.area_widgets = {}
        self._setup_widgets()

    def _setup_widgets(self):
        self.columnconfigure(1, weight=1)

        # Основные поля
        ttk.Label(self, text="Наименование (стандарт):").grid(row=0, column=0, sticky="w", pady=2)
        self.name_entry = ttk.Entry(self, width=60)
        self.name_entry.grid(row=0, column=1, sticky="we", pady=2)
        ttk.Label(self, text="Альтернативные названия\n(через запятую):").grid(row=1, column=0, sticky="nw", pady=2)
        self.alt_names_entry = ttk.Entry(self, width=60)
        self.alt_names_entry.grid(row=1, column=1, sticky="we", pady=2)
        ttk.Label(self, text="Общий комментарий:").grid(row=2, column=0, sticky="nw", pady=2)
        self.comment_entry = ttk.Entry(self, width=60)
        self.comment_entry.grid(row=2, column=1, sticky="we", pady=2)

        # Классификация
        class_frame = ttk.LabelFrame(self, text="Классификация", padding=5)
        class_frame.grid(row=3, column=0, columnspan=2, sticky="we", pady=10)
        class_frame.columnconfigure(1, weight=1)
        ttk.Label(class_frame, text="Категория:").grid(row=0, column=0, sticky="w")
        self.cat_entry = ttk.Entry(class_frame)
        self.cat_entry.grid(row=0, column=1, sticky="we", padx=5)
        ttk.Label(class_frame, text="Структурный класс:").grid(row=1, column=0, sticky="w")
        self.class_entry = ttk.Entry(class_frame)
        self.class_entry.grid(row=1, column=1, sticky="we", padx=5)
        ttk.Label(class_frame, text="Подкласс:").grid(row=2, column=0, sticky="w")
        self.subclass_entry = ttk.Entry(class_frame)
        self.subclass_entry.grid(row=2, column=1, sticky="we", padx=5)

        # Области применения (Scroll)
        area_frame = ttk.LabelFrame(self, text="Области применения", padding=5)
        area_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=10)
        self.rowconfigure(4, weight=1)
        checkbox_canvas = tk.Canvas(area_frame, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area_frame, orient="vertical", command=checkbox_canvas.yview)
        self.checkbox_container = ttk.Frame(checkbox_canvas)
        self.checkbox_container.bind("<Configure>",
                                     lambda e: checkbox_canvas.configure(scrollregion=checkbox_canvas.bbox("all")))
        checkbox_canvas.create_window((0, 0), window=self.checkbox_container, anchor="nw")
        checkbox_canvas.configure(yscrollcommand=scrollbar.set)

        # Биндим скролл через Mixin
        self.bind_mouse_wheel(checkbox_canvas)
        self.bind_mouse_wheel(self.checkbox_container, checkbox_canvas)

        checkbox_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Добавление области
        add_area_frame = ttk.Frame(self)
        add_area_frame.grid(row=5, column=0, columnspan=2, sticky="we", pady=(0, 10))
        add_label = ttk.Label(add_area_frame, text="Добавить область применения:")
        add_label.pack(side="left", padx=(0, 5))
        add_button = ttk.Button(add_area_frame, text="Добавить", command=self._add_new_area)
        add_button.pack(side="right")
        self.new_area_entry = ttk.Entry(add_area_frame)
        self.new_area_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # Параметры применения
        temp_app_frame = ttk.LabelFrame(self, text="Параметры применения", padding=5)
        temp_app_frame.grid(row=6, column=0, columnspan=2, sticky="we", pady=10)
        temp_app_frame.columnconfigure(1, weight=1)
        ttk.Label(temp_app_frame, text="Температура применения ДО, °С:").grid(row=0, column=0, sticky="w", padx=5,
                                                                              pady=2)
        self.temp_app_value_entry = ttk.Entry(temp_app_frame)
        self.temp_app_value_entry.grid(row=0, column=1, sticky="we", padx=5, pady=2)
        ttk.Label(temp_app_frame, text="Комментарий к температуре:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.temp_app_comment_entry = ttk.Entry(temp_app_frame)
        self.temp_app_comment_entry.grid(row=1, column=1, sticky="we", padx=5, pady=2)

    def _add_new_area(self):
        new_area = self.new_area_entry.get().strip()
        if not new_area: return
        if new_area in self.area_widgets:
            messagebox.showinfo("Информация", f"Область '{new_area}' уже есть в списке.", parent=self)
            return
        var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(self.checkbox_container, text=new_area, variable=var)
        cb.pack(anchor="w", padx=5, pady=1)

        # Биндим скролл к новому чекбоксу
        self.bind_mouse_wheel(cb, self.checkbox_container.master)  # master is canvas

        self.area_widgets[new_area] = (cb, var)
        self.new_area_entry.delete(0, tk.END)

    def populate_form(self, material):
        meta = material.data.get("metadata", {})
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, meta.get("name_material_standard", ""))
        alt_names_list = meta.get("name_material_alternative", [])
        self.alt_names_entry.delete(0, tk.END)
        self.alt_names_entry.insert(0, ", ".join(alt_names_list))
        self.comment_entry.delete(0, tk.END)
        self.comment_entry.insert(0, meta.get("comment", ""))
        cls = meta.get("classification", {})
        self.cat_entry.delete(0, tk.END)
        self.cat_entry.insert(0, cls.get("classification_category", ""))
        self.class_entry.delete(0, tk.END)
        self.class_entry.insert(0, cls.get("classification_class", ""))
        self.subclass_entry.delete(0, tk.END)
        self.subclass_entry.insert(0, cls.get("classification_subclass", ""))
        for widget, var in self.area_widgets.values():
            widget.destroy()
        self.area_widgets.clear()
        all_known_areas = set()
        for mat_from_db in self.app_data.materials:
            areas = mat_from_db.data.get("metadata", {}).get("application_area", [])
            all_known_areas.update(areas)
        current_material_areas = set(meta.get("application_area", []))
        all_known_areas.update(current_material_areas)
        sorted_areas = sorted(list(all_known_areas))

        canvas_widget = self.checkbox_container.master

        for area in sorted_areas:
            var = tk.BooleanVar()
            if area in current_material_areas:
                var.set(True)
            cb = ttk.Checkbutton(self.checkbox_container, text=area, variable=var)
            cb.pack(anchor="w", padx=5, pady=1)
            self.bind_mouse_wheel(cb, canvas_widget)
            self.area_widgets[area] = (cb, var)

        temp_app_data = meta.get("temperature_application", {})
        self.temp_app_value_entry.delete(0, tk.END)
        self.temp_app_value_entry.insert(0, temp_app_data.get("value", ""))
        self.temp_app_comment_entry.delete(0, tk.END)
        self.temp_app_comment_entry.insert(0, temp_app_data.get("comment", ""))

    def collect_data(self, material):
        meta = material.data["metadata"]
        meta["name_material_standard"] = self.name_entry.get()
        alt_names_str = self.alt_names_entry.get()
        meta["name_material_alternative"] = [name.strip() for name in alt_names_str.split(',') if name.strip()]
        meta["comment"] = self.comment_entry.get().strip()
        cls = meta["classification"]
        cls["classification_category"] = self.cat_entry.get()
        cls["classification_class"] = self.class_entry.get()
        cls["classification_subclass"] = self.subclass_entry.get()
        selected_areas = [area_name for area_name, (widget, var) in self.area_widgets.items() if var.get()]
        meta["application_area"] = selected_areas

        temp_val_str = self.temp_app_value_entry.get().strip()
        temp_comment_str = self.temp_app_comment_entry.get().strip()

        # ИСПОЛЬЗУЕМ safe_float
        temp_val = safe_float(temp_val_str)

        if temp_val is not None or temp_comment_str:
            temp_app_data = meta.setdefault("temperature_application", {})
            temp_app_data["value"] = temp_val
            temp_app_data["comment"] = temp_comment_str
        elif "temperature_application" in meta:
            del meta["temperature_application"]


class PropertyEditorTab(ttk.Frame, ScrollableMixin):
    """Вкладка редактора физических свойств (Refactored)."""

    def __init__(self, parent, prop_group_key, prop_map):
        super().__init__(parent)
        self.prop_group_key = prop_group_key
        self.prop_map = prop_map
        self.editors = {}  # prop_key -> SinglePropertyEditor instance
        self.app_data = None

        self._setup_widgets()

    def set_app_data(self, app_data):
        """Устанавливает app_data и передаёт SourceService во все редакторы свойств."""
        self.app_data = app_data
        if not self.app_data or not self.app_data.source_manager:
            return
        for editor in self.editors.values():
            editor.set_source_manager(self.app_data.source_manager)

    def _setup_widgets(self):
        # Скролл-область без глобального "Источник физ. свойств"
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def on_canvas_configure(event):
            canvas.itemconfig(window_id, width=event.width)

        canvas.bind("<Configure>", on_canvas_configure)

        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Создаем редакторы по свойствам
        for prop_key, prop_info in self.prop_map.items():
            frame = ttk.LabelFrame(scrollable_frame, text=f"{prop_info['name']} ({prop_info['symbol']})", padding=10)
            frame.pack(fill="x", expand=True, padx=10, pady=5)

            editor = SinglePropertyEditor(frame, prop_key, prop_info)
            editor.pack(fill="both", expand=True)
            self.editors[prop_key] = editor

        # --- ПРИВЯЗКА ВСЕХ ДЕТЕЙ К СКРОЛЛУ ---
        self.after_idle(lambda: self.bind_all_children(scrollable_frame, canvas))

    def populate_form(self, material):
        """Заполняет форму данными конкретного материала."""
        if self.app_data and self.app_data.source_manager:
            for editor in self.editors.values():
                editor.set_source_manager(self.app_data.source_manager)

        for prop_key, editor in self.editors.items():
            p_data = material.get_physical_data(prop_key) or {}
            editor.set_data(p_data)

    def collect_data(self, material):
        """Собирает данные из всех редакторов в структуру материала."""
        for prop_key, editor in self.editors.items():
            data = editor.get_data()
            if data:
                data.pop("property_source", None)
                material.set_physical_data(prop_key, data)
            else:
                material.remove_physical_data(prop_key)


class MechanicalPropertiesTab(ttk.Frame, ScrollableMixin):
    """Вкладка редактора механических свойств (Refactored)."""

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.material = None
        self.current_category_idx = -1
        self.editors = {}  # prop_key -> SinglePropertyEditor
        self.app_data = None
        self.source_map = {}
        self._setup_widgets()

    def set_app_data(self, app_data):
        """
        Устанавливает app_data:
        - заполняет список источников КП (группа strength_sources),
        - передаёт SourceService во все редакторы свойств,
          чтобы их поле 'Источник свойств' было связано с группой property_sources.
        """
        self.app_data = app_data
        self._update_source_list()

        if self.app_data and self.app_data.source_manager:
            for editor in self.editors.values():
                editor.set_source_manager(self.app_data.source_manager)

    def _update_source_list(self):
        """
        Обновляет список источников для 'Источник КП'.
        Использует только группу 'strength_sources' в source.json.
        """
        if not self.app_data or not self.app_data.source_manager:
            return

        # Берём только источники категории прочности
        sources = self.app_data.source_manager.get_all("strength_sources")
        self.source_map = {s.get("name_source", ""): s.get("id_source") for s in sources if s.get("id_source")}
        self.category_source_combo['values'] = sorted(self.source_map.keys())

    def _setup_widgets(self):
        # 1. Панель Категории
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(top_frame, text="Категория прочности:").pack(side="left", padx=(0, 5))
        self.category_combo = ttk.Combobox(top_frame, state="readonly", width=40)
        self.category_combo.pack(side="left", fill="x", expand=True)
        self.category_combo.bind("<<ComboboxSelected>>", self._on_category_select)
        ttk.Button(top_frame, text="+", width=3, command=self._add_category).pack(side="left", padx=5)
        ttk.Button(top_frame, text="-", width=3, command=self._delete_category).pack(side="left")

        # 2. Контент редактора
        self.editor_content_frame = ttk.Frame(self)

        cat_meta_frame = ttk.Frame(self.editor_content_frame)
        cat_meta_frame.pack(fill="x", pady=5)
        ttk.Label(cat_meta_frame, text="Название КП:").grid(row=0, column=0, sticky="w", padx=5)
        self.category_name_entry = ttk.Entry(cat_meta_frame, width=20)
        self.category_name_entry.grid(row=0, column=1, sticky="w", padx=5)

        ttk.Label(cat_meta_frame, text="Источник КП:").grid(row=0, column=2, sticky="w", padx=15)
        self.category_source_combo = ttk.Combobox(cat_meta_frame, state="readonly", width=40)
        self.category_source_combo.grid(row=0, column=3, sticky="we", padx=5)
        cat_meta_frame.columnconfigure(3, weight=1)

        # Скролл
        prop_canvas = tk.Canvas(self.editor_content_frame)
        scrollbar = ttk.Scrollbar(self.editor_content_frame, orient="vertical", command=prop_canvas.yview)
        scrollable_frame = ttk.Frame(prop_canvas)

        scrollable_frame.bind("<Configure>", lambda e: prop_canvas.configure(scrollregion=prop_canvas.bbox("all")))

        window_id = prop_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def on_canvas_configure(event):
            prop_canvas.itemconfig(window_id, width=event.width)

        prop_canvas.bind("<Configure>", on_canvas_configure)

        prop_canvas.configure(yscrollcommand=scrollbar.set)

        prop_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Свойства
        for prop_key, prop_info in MECHANICAL_MAP.items():
            frame = ttk.LabelFrame(scrollable_frame, text=f"{prop_info['name']} ({prop_info['symbol']})", padding=10)
            frame.pack(fill="x", expand=True, padx=10, pady=5)

            editor = SinglePropertyEditor(frame, prop_key, prop_info)
            editor.pack(fill="both", expand=True)
            self.editors[prop_key] = editor

        # Твердость
        h_frame = ttk.LabelFrame(scrollable_frame, text="Твердость", padding=10)
        h_frame.pack(fill="x", expand=True, padx=10, pady=5)
        self.hardness_tree = self._create_hardness_table(h_frame)

        # --- ПРИВЯЗКА ВСЕХ ДЕТЕЙ ---
        # Вызываем для scrollable_frame, чтобы прокручивался prop_canvas
        self.after_idle(lambda: self.bind_all_children(scrollable_frame, prop_canvas))

    def _create_hardness_table(self, parent):
        top_h_frame = ttk.Frame(parent)
        top_h_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(top_h_frame, text="Ед. изм:").pack(side="left")
        units = UnitManager.get_units("Твердость")
        self.hardness_unit_combo = ttk.Combobox(top_h_frame, values=units, state="readonly", width=10)
        self.hardness_unit_combo.pack(side="left", padx=5)
        self.hardness_unit_combo.set("HB")

        t_frame = ttk.Frame(parent)
        t_frame.pack(fill="both", expand=True)
        tree = create_editable_treeview(t_frame)
        tree.configure(show="headings")
        # Удалили столбец "Под-источник", оставляем только Min/Max
        tree["columns"] = ("min", "max")
        tree.heading("min", text="Min")
        tree.column("min", width=80, anchor="center")
        tree.heading("max", text="Max")
        tree.column("max", width=80, anchor="center")
        tree.pack(side="left", fill="both", expand=True)

        b_frame = ttk.Frame(t_frame)
        b_frame.pack(side="left", fill="y", padx=5)
        ttk.Button(b_frame, text="+", width=2,
                   command=lambda: tree.insert("", "end", values=["", ""])).pack(pady=2)
        ttk.Button(b_frame, text="-", width=2,
                   command=lambda: tree.delete(tree.selection())).pack(pady=2)
        return tree

    def populate_form(self, material):
        if self.material and self.material != material: self._save_current_category()
        self.material = material
        self.current_category_idx = -1
        self._update_source_list()

        cats = material.get_strength_categories()
        names = [Material.category_name(c) or f"КП {i + 1}" for i, c in enumerate(cats)]
        self.category_combo["values"] = names

        if cats:
            self.editor_content_frame.pack(fill="both", expand=True)
            self.category_combo.current(0)
            self._on_category_select()
        else:
            self.category_combo.set("")
            self.editor_content_frame.pack_forget()

    def _on_category_select(self, event=None):
        new_idx = self.category_combo.current()
        if new_idx == -1: return
        if self.current_category_idx != -1 and self.current_category_idx != new_idx:
            self._save_current_category()
        self.current_category_idx = new_idx

        cat_data = self.material.get_strength_categories()[self.current_category_idx]

        self.category_name_entry.delete(0, tk.END)
        self.category_name_entry.insert(0, Material.category_name(cat_data))

        ref_id = cat_data.get("source_ref_id")
        if ref_id and self.app_data:
            name = self.app_data.source_manager.get_name_by_id(ref_id)
            self.category_source_combo.set(name)
        else:
            self.category_source_combo.set("")

        for prop_key, editor in self.editors.items():
            p_data = Material.get_category_prop_data(cat_data, prop_key) or {}
            editor.set_data(p_data)

        # Hardness Unit
        h_unit = Material.get_hardness_unit(cat_data)

        if h_unit and h_unit in self.hardness_unit_combo['values']:
            self.hardness_unit_combo.set(h_unit)
        else:
            self.hardness_unit_combo.set("HB")

        tree = self.hardness_tree
        for i in tree.get_children():
            tree.delete(i)
        for h in Material.get_hardness_entries(cat_data):
            tree.insert(
                "", "end",
                values=[
                    h.get("min_value", ""),
                    h.get("max_value", "")
                ]
            )

    def _add_category(self):
        if not self.material: return
        self._save_current_category()
        new_name = f"Новая КП {len(self.category_combo['values']) + 1}"
        new_cat = Material.empty_strength_group(new_name)

        mech = self.material.ensure_group(Schema.TYPE_MECHANICAL)
        if not isinstance(mech.get(Schema.STRENGTH_GROUPS), list):
            mech[Schema.STRENGTH_GROUPS] = []
        mech[Schema.STRENGTH_GROUPS].append(new_cat)

        vals = list(self.category_combo['values'])
        vals.append(new_name)
        self.category_combo['values'] = vals
        self.category_combo.current(len(vals) - 1)
        self._on_category_select()

    def _delete_category(self):
        if not self.material or self.current_category_idx == -1: return
        if messagebox.askyesno("Подтверждение", "Удалить категорию?"):
            cats = self.material.get_strength_categories()
            del cats[self.current_category_idx]
            self.current_category_idx = -1
            self.populate_form(self.material)

    def _save_current_category(self):
        if not self.material or self.current_category_idx == -1:
            return
        try:
            cat_data = self.material.get_strength_categories()[self.current_category_idx]
        except Exception:
            return

        cat_data[Schema.STRENGTH_CAT] = self.category_name_entry.get()
        cat_data.pop(Schema.VAL_STR_CAT, None)
        src_name = self.category_source_combo.get()
        if src_name and self.app_data:
            sid = self.source_map.get(src_name)
            if sid:
                cat_data["source_ref_id"] = sid

        for prop_key, editor in self.editors.items():
            data = editor.get_data()
            if data:
                data.pop("property_source", None)
                Material.set_category_prop_data(cat_data, prop_key, data)
            else:
                Material.remove_category_prop_data(cat_data, prop_key)

        current_h_unit = self.hardness_unit_combo.get()
        old_hardness = Material.get_hardness_entries(cat_data)
        h_list = []
        for idx, item in enumerate(self.hardness_tree.get_children()):
            v = self.hardness_tree.set(item)
            h = {
                "unit_value": current_h_unit,
                "min_value": safe_float(v.get("min")),
                "max_value": safe_float(v.get("max"))
            }
            if idx < len(old_hardness):
                old_sub = old_hardness[idx].get("property_subsource")
                if old_sub:
                    h["property_subsource"] = old_sub
                old_src = old_hardness[idx].get("property_source")
                if old_src:
                    h["property_source"] = old_src
            if h.get("property_subsource") or h["min_value"] is not None or h["max_value"] is not None:
                h_list.append(h)

        if h_list:
            Material.set_hardness_entries(cat_data, h_list, unit=current_h_unit)
        else:
            Material.remove_category_prop_data(cat_data, Schema.HARDNESS)

        vals = list(self.category_combo['values'])
        vals[self.current_category_idx] = cat_data[Schema.STRENGTH_CAT]
        self.category_combo['values'] = vals

    def collect_data(self, material):
        if self.material == material: self._save_current_category()


class ChemicalCompositionTab(ttk.Frame):
    """Вкладка для редактирования химического состава с логарифмической гистограммой."""

    ELEMENTS_MAP = {
        "Ag": {"name": "Серебро", "color": "#C0C0C0"},
        "Al": {"name": "Алюминий", "color": "#B5B5B5"},
        "As": {"name": "Мышьяк", "color": "#7D8080"},
        "B": {"name": "Бор", "color": "#2B2B2B"},
        "Be": {"name": "Бериллий", "color": "#B8CC7A"},
        "Bi": {"name": "Висмут", "color": "#C885C4"},
        "C": {"name": "Углерод", "color": "#363636"},
        "Ca": {"name": "Кальций", "color": "#808080"},
        "Cd": {"name": "Кадмий", "color": "#D1C366"},
        "Ce": {"name": "Церий", "color": "#FFFFC7"},
        "Cl": {"name": "Хлор", "color": "#1FF22D"},
        "Co": {"name": "Кобальт", "color": "#1A569E"},
        "Cr": {"name": "Хром", "color": "#8A9EA8"},
        "Cu": {"name": "Медь", "color": "#D98048"},
        "Fe": {"name": "Железо", "color": "#8C3E26"},
        "H": {"name": "Водород", "color": "#F0F0F0"},
        "La": {"name": "Лантан", "color": "#8AFAFA"},
        "Li": {"name": "Литий", "color": "#B52FED"},
        "Mg": {"name": "Магний", "color": "#E3E3E3"},
        "Mn": {"name": "Марганец", "color": "#8C6A8A"},
        "Mo": {"name": "Молибден", "color": "#8F88A1"},
        "N": {"name": "Азот", "color": "#6B85F0"},
        "Na": {"name": "Натрий", "color": "#F2F20C"},
        "Nb": {"name": "Ниобий", "color": "#6ED6C6"},
        "Nd": {"name": "Неодим", "color": "#C7FACF"},
        "Ni": {"name": "Никель", "color": "#5C8F54"},
        "O": {"name": "Кислород", "color": "#E60E0E"},
        "P": {"name": "Фосфор", "color": "#DE5914"},
        "Pb": {"name": "Свинец", "color": "#525252"},
        "S": {"name": "Сера", "color": "#F2E82E"},
        "Sb": {"name": "Сурьма", "color": "#A1759C"},
        "Si": {"name": "Кремний", "color": "#8C8C8C"},
        "Sn": {"name": "Олово", "color": "#858282"},
        "Ti": {"name": "Титан", "color": "#85878A"},
        "V": {"name": "Ванадий", "color": "#949494"},
        "W": {"name": "Вольфрам", "color": "#5C5857"},
        "Y": {"name": "Иттрий", "color": "#8AFAFA"},
        "Zn": {"name": "Цинк", "color": "#797D82"},
        "Zr": {"name": "Цирконий", "color": "#C4E0B6"},
        "РЗМ": {"name": "РЗМ", "color": "#E0E0E0"},
        "Au": {"name": "Золото", "color": "#FFD700"},
        "Ba": {"name": "Барий", "color": "#00C900"},
        "F": {"name": "Фтор", "color": "#DAA520"},
        "Ga": {"name": "Галлий", "color": "#C2C2C2"},
        "Hg": {"name": "Ртуть", "color": "#E6E6E6"},
        "In": {"name": "Индий", "color": "#4B0082"},
        "Ir": {"name": "Иридий", "color": "#FFDEAD"},
        "Pd": {"name": "Палладий", "color": "#006400"},
        "Pt": {"name": "Платина", "color": "#E5E4E2"},
        "Rh": {"name": "Родий", "color": "#FF00FF"},
        "Se": {"name": "Селен", "color": "#A0522D"},
        "Ta": {"name": "Тантал", "color": "#4682B4"},
        "Te": {"name": "Теллур", "color": "#D2691E"},
        "Tl": {"name": "Таллий", "color": "#A52A2A"},
        "Ru": {"name": "Рутений", "color": "#708090"}
    }

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.material = None
        self.current_source_idx = -1
        self.app_data = None
        # Менеджер источников и кэш отображения для источников хим. состава
        self.source_manager = None
        self._source_name_to_id = {}
        self._source_id_to_name = {}

        # Переменные для чекбоксов графика
        self.var_min = tk.BooleanVar(value=False)
        self.var_max = tk.BooleanVar(value=True)

        # График
        self.fig = None
        self.ax = None
        self.canvas = None

        # Для всплывающего окна
        self.popup_window = None
        self._setup_widgets()

    def set_app_data(self, app_data):
        self.app_data = app_data
        # Привязываем SourceService и обновляем список источников хим. свойств
        if self.app_data and hasattr(self.app_data, "source_manager"):
            self.source_manager = self.app_data.source_manager
            self._refresh_source_list()

    def _refresh_source_list(self):
        """Обновляет список источников хим. состава (группа chemical_sources)."""
        self._source_name_to_id = {}
        self._source_id_to_name = {}

        # Если SourceService не задан — очищаем выпадающий список
        if not self.source_manager:
            if hasattr(self, "source_entry"):
                self.source_entry.config(values=[])
            return

        try:
            sources = self.source_manager.get_all("chemical_sources")
        except TypeError:
            # На случай старого SourceService без групп
            sources = self.source_manager.get_all()

        names = []
        for src in sources:
            sid = src.get("id_source")
            name = src.get("name_source", "Без названия")
            if not sid:
                continue
            self._source_name_to_id[name] = sid
            self._source_id_to_name[sid] = name
            names.append(name)

        if hasattr(self, "source_entry"):
            self.source_entry.config(values=sorted(names))

    def _setup_widgets(self):
        # --- Верхняя панель ---
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(top_frame, text="Источник состава:").pack(side="left", padx=(0, 5))
        self.source_combo = ttk.Combobox(top_frame, state="readonly", width=40)
        self.source_combo.pack(side="left", fill="x", expand=True)
        self.source_combo.bind("<<ComboboxSelected>>", self._on_source_select)
        ttk.Button(top_frame, text="+", width=3, command=self._add_source).pack(side="left", padx=5)
        ttk.Button(top_frame, text="-", width=3, command=self._delete_source).pack(side="left")

        # --- Основной контейнер редактора ---
        self.editor_content_frame = ttk.Frame(self)
        self.editor_content_frame.pack(fill="both", expand=True)
        self.editor_content_frame.pack_forget()

        # 1. Метаданные
        meta_frame = ttk.LabelFrame(self.editor_content_frame, text="Данные источника", padding=5)
        meta_frame.pack(fill="x", pady=5)
        meta_frame.columnconfigure(1, weight=1)

        ttk.Label(meta_frame, text="Источник:").grid(row=0, column=0, sticky="w")
        # Выпадающий список, связанный с группой "Источник хим. свойств"
        self.source_entry = ttk.Combobox(meta_frame, state="readonly")
        self.source_entry.grid(row=0, column=1, sticky="we", padx=5, pady=2)

        # Поле "Под-источник" удалено из UI

        ttk.Label(meta_frame, text="Комментарий:").grid(row=1, column=0, sticky="w")
        self.comment_entry = ttk.Entry(meta_frame)
        self.comment_entry.grid(row=1, column=1, sticky="we", padx=5, pady=2)

        ttk.Label(meta_frame, text="Основной элемент:").grid(row=2, column=0, sticky="w")
        self.base_element_entry = ttk.Combobox(meta_frame, values=["Fe", "Ti", "Cu"], width=10)
        self.base_element_entry.grid(row=2, column=1, sticky="w", padx=5, pady=2)
        self.base_element_entry.bind("<<ComboboxSelected>>", lambda e: self._update_chart())
        self.base_element_entry.bind("<KeyRelease>", lambda e: self._update_chart())

        ttk.Label(meta_frame, text="Ед. изм.:").grid(row=3, column=0, sticky="w")
        units = UnitManager.get_units("Безразмерный")
        self.unit_combo = ttk.Combobox(meta_frame, values=units, state="readonly", width=10)
        self.unit_combo.grid(row=3, column=1, sticky="w", padx=5, pady=2)
        self.unit_combo.set("%")

        # 2. Разделенный контейнер
        split_container = ttk.Frame(self.editor_content_frame)
        split_container.pack(fill="both", expand=True, pady=5)

        # -- Левая часть: Таблица --
        left_pane = ttk.Frame(split_container)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 5))

        elements_frame = ttk.LabelFrame(left_pane, text="Элементы (ПКМ для выбора из списка)", padding=5)
        elements_frame.pack(fill="both", expand=True)
        self.elements_tree = self._create_elements_table(elements_frame)

        # -- Правая часть: График --
        right_pane = ttk.Frame(split_container)
        right_pane.pack(side="right", fill="both", expand=True, padx=(5, 0))
        self._create_chart_panel(right_pane)

    def _create_elements_table(self, parent_frame):
        table_frame = ttk.Frame(parent_frame)
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)

        tree = create_editable_treeview(table_frame, on_update_callback=self._update_chart)
        tree.configure(show="headings")
        tree["columns"] = ("name", "elem", "min", "max", "min_tol", "max_tol")

        tree.heading("name", text="Название элемента")
        tree.column("name", width=140, anchor="center")
        tree.heading("elem", text="Элемент")
        tree.column("elem", width=60, anchor="center")
        tree.heading("min", text="Min")
        tree.column("min", width=50, anchor="center")
        tree.heading("max", text="Max")
        tree.column("max", width=50, anchor="center")
        tree.heading("min_tol", text="Допуск Min")
        tree.column("min_tol", width=80, anchor="center")
        tree.heading("max_tol", text="Допуск Max")
        tree.column("max_tol", width=80, anchor="center")

        tree.pack(side="left", fill="both", expand=True)

        btn_frame = ttk.Frame(table_frame)
        btn_frame.pack(side="left", fill="y", padx=5)

        def add_row():
            tree.insert("", "end", values=["", "", "", "", "", ""])
            self._update_chart()

        def del_row():
            sel = tree.selection()
            if sel:
                tree.delete(sel)
                self._update_chart()

        ttk.Button(btn_frame, text="+", width=2, command=add_row).pack(pady=2)
        ttk.Button(btn_frame, text="-", width=2, command=del_row).pack(pady=2)

        tree.bind("<Button-3>", self._on_tree_right_click)
        return tree

    def _create_chart_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        plot_frame = ttk.LabelFrame(parent, text="Распределение элементов в составе")
        plot_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.2, right=0.95, top=0.9, bottom=0.15)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        ctrl_frame = ttk.Frame(parent)
        ctrl_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        def toggle_min():
            if self.var_min.get():
                self.var_max.set(False)
            elif not self.var_max.get():
                self.var_max.set(True)
            self._update_chart()

        def toggle_max():
            if self.var_max.get():
                self.var_min.set(False)
            elif not self.var_min.get():
                self.var_min.set(True)
            self._update_chart()

        cb_min = ttk.Checkbutton(ctrl_frame, text="Min", variable=self.var_min, command=toggle_min)
        cb_min.pack(side="left", padx=10)
        cb_max = ttk.Checkbutton(ctrl_frame, text="Max", variable=self.var_max, command=toggle_max)
        cb_max.pack(side="left", padx=10)

    # === [Логика Графика] ===
    def _update_chart(self):
        if not self.ax or not self.canvas: return

        self.ax.clear()
        plot_data = []

        base_elem_sym = self.base_element_entry.get().strip()
        if not base_elem_sym: base_elem_sym = "Основа"
        base_elem_name = self.ELEMENTS_MAP.get(base_elem_sym, {}).get("name", "Основа")
        base_elem_color = self.ELEMENTS_MAP.get(base_elem_sym, {}).get("color", "#444444")

        use_max = self.var_max.get()
        total_elements_amount = 0.0

        # Собираем данные
        for item_id in self.elements_tree.get_children():
            row = self.elements_tree.item(item_id, "values")
            # row: name, elem, min, max, min_tol, max_tol
            elem_sym = row[1]
            if not elem_sym: continue  # Пропускаем пустые строки

            color = self.ELEMENTS_MAP.get(elem_sym, {}).get("color", "#1f77b4")
            val_min = safe_float(row[2])
            val_max = safe_float(row[3])

            value = 0.0
            if use_max:
                if val_max is not None: value = val_max
            else:
                if val_min is not None: value = val_min

            # Считаем сумму для основы
            if value > 0:
                total_elements_amount += value

            # Добавляем элемент в график ДАЖЕ ЕСЛИ VALUE == 0
            plot_data.append({
                "label": elem_sym,
                "value": value,
                "color": color
            })

        # Считаем основу
        base_percent = 100.0 - total_elements_amount
        if base_percent < 0: base_percent = 0

        plot_data.append({
            "label": base_elem_sym,
            "value": base_percent,
            "color": base_elem_color
        })

        if not plot_data:
            self.ax.text(0.5, 0.5, "Нет данных", ha='center', va='center')
        else:
            # Сортировка
            plot_data.sort(key=lambda x: x["value"], reverse=False)

            labels = [d["label"] for d in plot_data]
            values = [d["value"] for d in plot_data]
            colors = [d["color"] for d in plot_data]

            # Рисуем бары
            bars = self.ax.barh(labels, values, color=colors)

            # Логарифмическая шкала
            self.ax.set_xscale('log')
            self.ax.grid(True, axis='x', which="both", ls="--", alpha=0.4)

            unit = self.unit_combo.get()

            # Подписи значений
            for i, val in enumerate(values):
                # [ИЗМЕНЕНИЕ] Показываем текст, только если значение значимое
                if val > 0.0001:
                    text_val = f"{val:.4f}".rstrip('0').rstrip('.') if val < 0.1 else f"{val:.2f}"
                    txt = f" {text_val} {unit}"
                    self.ax.text(val, i, txt, va='center', ha='left', fontsize=8, fontweight='bold')

            # Расчет лимитов оси X (чтобы логарифм не сломался от 0)
            max_val_graph = max(values) if values else 100
            non_zero_vals = [v for v in values if v > 0]
            min_val_graph = min(non_zero_vals) if non_zero_vals else 0.001

            # Ставим пределы
            self.ax.set_xlim(min_val_graph * 0.5, max_val_graph * 5)

        self.fig.tight_layout()
        self.canvas.draw()

    # === [Кастомное меню выбора] ===
    def _on_tree_right_click(self, event):
        region = self.elements_tree.identify_region(event.x, event.y)
        if region == "cell":
            item = self.elements_tree.identify_row(event.y)
            column = self.elements_tree.identify_column(event.x)
            # Если кликнули по колонкам "Название" (#1) или "Элемент" (#2)
            if column in ("#1", "#2"):
                self.elements_tree.selection_set(item)
                self.elements_tree.focus(item)
                # Вызываем кастомный скроллируемый список вместо Menu
                self._show_scrollable_element_picker(event, item)

    def _show_scrollable_element_picker(self, event, row_id):
        # Закрываем предыдущее, если было
        if self.popup_window:
            self.popup_window.destroy()

        # Создаем окно без рамок (Toplevel)
        self.popup_window = tk.Toplevel(self)
        self.popup_window.wm_overrideredirect(True)
        self.popup_window.geometry(f"+{event.x_root}+{event.y_root}")

        # Контейнер для списка
        frame = ttk.Frame(self.popup_window, relief="solid", borderwidth=1)
        frame.pack(fill="both", expand=True)

        # Скроллбар
        scrollbar = ttk.Scrollbar(frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        # Листбокс (высота 10 строк, как просили)
        listbox = tk.Listbox(frame, height=10, width=30, yscrollcommand=scrollbar.set, exportselection=False)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        # Заполняем элементами
        sorted_items = sorted(self.ELEMENTS_MAP.items(), key=lambda x: x[1]["name"])
        items_data = []  # Храним (символ, имя) для доступа по индексу

        for symbol, data in sorted_items:
            name = data["name"]
            display_text = f"{name} ({symbol})"
            listbox.insert(tk.END, display_text)
            items_data.append((symbol, name))

        # Функция выбора
        def on_select(evt):
            sel_idx = listbox.curselection()
            if not sel_idx: return
            idx = sel_idx[0]
            symbol, name = items_data[idx]

            # Обновляем таблицу
            current_values = list(self.elements_tree.item(row_id, "values"))
            current_values[0] = name
            current_values[1] = symbol
            self.elements_tree.item(row_id, values=current_values)

            # Обновляем график
            self._update_chart()

            self.popup_window.destroy()
            self.popup_window = None

        # Биндинги
        listbox.bind("<<ListboxSelect>>", on_select)
        listbox.bind("<Escape>", lambda e: self.popup_window.destroy())

        # Закрытие при потере фокуса
        self.popup_window.bind("<FocusOut>", lambda e: self.popup_window.destroy())

        # Скролл колесом мыши (для Windows/Linux/Mac)
        def _on_mousewheel(event):
            listbox.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        listbox.bind("<MouseWheel>", _on_mousewheel)
        listbox.focus_set()

    def populate_form(self, material):
        if self.material and self.material != material:
            self._save_current_source()

        self.material = material
        self.current_source_idx = -1

        compositions = material.get_compositions()
        self.source_combo["values"] = [comp.get("composition_source", f"Источник {i + 1}") for i, comp in
                                       enumerate(compositions)]

        if compositions:
            self.source_combo.current(0)
            self._on_source_select()
        else:
            self.source_combo.set("")
            self.editor_content_frame.pack_forget()

    def _on_source_select(self, event=None):
        self._save_current_source()

        idx = self.source_combo.current()
        if idx == -1:
            self.editor_content_frame.pack_forget()
            return

        self.current_source_idx = idx
        compositions = self.material.get_compositions()
        if idx >= len(compositions):
            self.editor_content_frame.pack_forget()
            return
        comp_data = compositions[idx]
        self._populate_source_fields(comp_data)
        self.editor_content_frame.pack(fill="both", expand=True)

    def _populate_source_fields(self, comp_data):
        # Обновляем список источников хим. свойств
        self._refresh_source_list()

        # Определяем отображаемое имя источника (новый и старый формат)
        source_to_show = ""
        ref_id = comp_data.get("source_ref_id")
        if ref_id and self.source_manager:
            try:
                src = self.source_manager.get_source_by_id(ref_id)
            except TypeError:
                src = None
            if src:
                source_to_show = src.get("name_source", "")

        if not source_to_show:
            # Старый формат: берем строку из composition_source
            source_to_show = comp_data.get("composition_source", "") or ""

        # Если имя источника не входит в текущий список значений — добавляем
        if source_to_show:
            current_values = list(self.source_entry['values'])
            if source_to_show not in current_values:
                current_values.append(source_to_show)
                self.source_entry['values'] = current_values
            self.source_entry.set(source_to_show)
        else:
            self.source_entry.set("")

        # Поле под-источника больше не редактируется, но существующий composition_subsource
        # сохраняется в JSON как есть (прозрачно для UI).
        self.comment_entry.delete(0, tk.END)
        self.comment_entry.insert(0, comp_data.get("comment", ""))

        self.base_element_entry.set(comp_data.get("base_element", ""))

        first_elem = comp_data.get("other_elements", [{}])[0] if comp_data.get("other_elements") else {}
        unit = first_elem.get("unit_value", "%")
        self.unit_combo.set(unit)

        for i in self.elements_tree.get_children():
            self.elements_tree.delete(i)

        for elem in comp_data.get("other_elements", []):
            symbol = elem.get("element", "")
            name = self.ELEMENTS_MAP.get(symbol, {}).get("name", "")

            self.elements_tree.insert(
                "", "end",
                values=[
                    name,
                    symbol,
                    elem.get("min_value", ""),
                    elem.get("max_value", ""),
                    elem.get("min_value_tolerance", ""),
                    elem.get("max_value_tolerance", "")
                ]
            )

        self._update_chart()

    def _add_source(self):
        if not self.material: return
        self._save_current_source()
        new_source = {"composition_source": "Новый источник", "other_elements": []}
        self.material.append_composition(new_source)
        compositions = self.material.get_compositions()
        self.populate_form(self.material)
        self.source_combo.current(len(compositions) - 1)
        self._on_source_select()

    def _delete_source(self):
        if not self.material or self.current_source_idx == -1: return
        if messagebox.askyesno("Подтверждение", "Вы уверены, что хотите удалить этот источник хим. состава?"):
            self.material.delete_composition_at(self.current_source_idx)
            self.source_combo.set("")
            self.populate_form(self.material)

    def _save_current_source(self):
        if not self.material or self.current_source_idx == -1:
            return
        try:
            compositions = self.material.get_compositions()
            comp_data = compositions[self.current_source_idx]
        except IndexError:
            return

        # Обновляем кэш источников (на случай изменений во вкладке 'Работа с источниками')
        self._refresh_source_list()

        source_name = (self.source_entry.get() or "").strip()
        comp_data["comment"] = self.comment_entry.get()
        comp_data["base_element"] = self.base_element_entry.get()

        # Логика источника:
        # - Новый формат: source_ref_id указывает на SourceService (группа chemical_sources),
        #   при этом дублируем имя в composition_source для обратной совместимости.
        # - Старый формат / неизвестный источник: только composition_source (без source_ref_id).
        if source_name and self.source_manager:
            if not self._source_name_to_id:
                self._refresh_source_list()
            src_id = self._source_name_to_id.get(source_name)
            if src_id:
                comp_data["source_ref_id"] = src_id
                comp_data["composition_source"] = source_name
            else:
                # Имя не найдено среди зарегистрированных источников — ведём себя как в старом формате
                comp_data.pop("source_ref_id", None)
                comp_data["composition_source"] = source_name
        else:
            # Поле пустое — очищаем привязку к источнику и строковое имя
            comp_data.pop("source_ref_id", None)
            comp_data.pop("composition_source", None)

        # ВАЖНО: composition_subsource не трогаем.
        # Старые JSON-файлы сохранят это поле как есть, но редактировать его в UI больше нельзя.

        common_unit = self.unit_combo.get()

        elements_list = []
        for item_id in self.elements_tree.get_children():
            values = self.elements_tree.set(item_id)
            if not values.get("elem"):
                continue

            elem_data = {
                "element": values["elem"],
                "unit_value": common_unit
            }

            elem_data["min_value"] = safe_float(values["min"])
            elem_data["max_value"] = safe_float(values["max"])

            if values["min_tol"]:
                elem_data["min_value_tolerance"] = values["min_tol"]
            if values["max_tol"]:
                elem_data["max_value_tolerance"] = values["max_tol"]

            elements_list.append(elem_data)

        comp_data["other_elements"] = elements_list
        self._update_chart()

    def collect_data(self, material):
        self._save_current_source()
        self.material = material


class EditorFrame(ttk.Frame):
    def __init__(self, parent, app_data, main_app):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app  # <--- ВОТ ЭТА СТРОКА ВАЖНА
        self.editing_copy = None
        self._setup_widgets()

        # Передаем данные во вкладки для работы с источниками
        self.phys_tab.set_app_data(app_data)
        self.mech_tab.set_app_data(app_data)
        self.chem_tab.set_app_data(app_data)

        # Изначально кнопки выключены
        self._update_button_states(False)

        self._update_button_states(False)

    def _setup_widgets(self):
        # --- Верхняя панель управления ---
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(top_frame, text="Выберите материал:").pack(side="left")
        self.mat_combo = ttk.Combobox(top_frame, state="readonly", width=40)
        self.mat_combo.pack(side="left", padx=5)
        self.mat_combo.bind("<<ComboboxSelected>>", self.load_material)

        new_button = ttk.Button(top_frame, text="Создать новый", command=self.create_new_material)
        new_button.pack(side="left", padx=(10, 5))

        # --- НАЧАЛО ИЗМЕНЕНИЙ: Новые кнопки ---
        self.save_button = ttk.Button(top_frame, text="Сохранить", command=self.save_material)
        self.save_button.pack(side="left", padx=5)

        self.save_as_button = ttk.Button(top_frame, text="Сохранить как...", command=self.save_material_as)
        self.save_as_button.pack(side="left", padx=5)

        self.revert_button = ttk.Button(top_frame, text="Отменить изменения", command=self.revert_changes)
        self.revert_button.pack(side="left", padx=5)
        # --- КОНЕЦ ИЗМЕНЕНИЙ ---

        # --- Notebook для вкладок редактора ---
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=(0, 10))

        self.general_tab = GeneralDataTab(self.notebook, self.app_data)
        self.phys_tab = PropertyEditorTab(self.notebook, Schema.TYPE_PHYSICAL, PHYSICAL_MAP)
        self.mech_tab = MechanicalPropertiesTab(self.notebook)
        self.chem_tab = ChemicalCompositionTab(self.notebook)

        self.notebook.add(self.general_tab, text="Общие данные", state="disabled")
        self.notebook.add(self.phys_tab, text="Физические свойства", state="disabled")
        self.notebook.add(self.mech_tab, text="Механические свойства", state="disabled")
        self.notebook.add(self.chem_tab, text="Химический состав", state="disabled")

    # --- НОВЫЙ МЕТОД: Управление состоянием кнопок ---
    def _update_button_states(self, active=False):
        state = "normal" if active else "disabled"
        self.save_button.config(state=state)
        self.save_as_button.config(state=state)
        self.revert_button.config(state=state)

    # --- AUDIT (тихо) ---

    def _audit_log(
        self,
        *,
        event_name,
        event_category,
        event_action,
        operation_id=None,
        parent_operation_id=None,
        result_ok=None,
        result_status=None,
        result_error_kind=None,
        duration_ms=None,
        counters=None,
        entity=None,
        changes_fields=None,
        data=None,
    ):
        """Пишет аудит-событие (если audit_logger доступен). Никогда не мешает работе UI."""
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if not logger:
                return
            logger.log(
                event_name=event_name,
                event_category=event_category,
                event_action=event_action,
                operation_id=operation_id,
                parent_operation_id=parent_operation_id,
                result_ok=result_ok,
                result_status=result_status,
                result_error_kind=result_error_kind,
                duration_ms=duration_ms,
                counters=counters,
                entity=entity,
                changes_fields=changes_fields,
                data=data,
            )
        except Exception:
            return

    def _audit_changes_fields_from_diff(self, changes):
        """Преобразует find_changes() -> список строк-путей полей (без значений)."""
        try:
            if not changes:
                return []
            fields = set()
            for ch in changes:
                if not isinstance(ch, dict):
                    continue
                path = ch.get("path")
                if isinstance(path, list) and path:
                    fields.add(".".join(str(p) for p in path if str(p)))
            return sorted(fields)
        except Exception:
            return []

    def _audit_log_material_save_by_tabs(self, operation_id, material_name, changes, *, data_extra):
        """Отдельная строка аудита на каждую вкладку редактора с ненулевым числом изменений."""
        grouped = group_editor_changes_by_tab(changes)
        if not grouped:
            return grouped
        entity = {"type": "Материал", "name": material_name}
        for tab in EDITOR_AUDIT_TAB_ORDER:
            labels = grouped.get(tab)
            if not labels:
                continue
            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE_TAB"],
                event_category="Данные",
                event_action="Изменено",
                operation_id=operation_id,
                entity=entity,
                changes_fields=labels,
                counters={"полей": len(labels)},
                data={**data_extra, "вкладка": tab},
            )
        return grouped

    def refresh_sources_in_tabs(self):
        """Обновляет списки источников во вкладках редактора материалов."""
        if not self.app_data or not getattr(self.app_data, "source_manager", None):
            return
        # Переиспользуем существующий механизм set_app_data,
        # чтобы во всех редакторах обновились combobox'ы с источниками.
        self.phys_tab.set_app_data(self.app_data)
        self.mech_tab.set_app_data(self.app_data)
        self.chem_tab.set_app_data(self.app_data)

    def update_view(self):
        mat_names = [m.get_display_name() for m in self.app_data.materials]
        self.mat_combo.config(values=mat_names)

        if self.editing_copy and self.editing_copy.get_display_name() in mat_names:
            self.mat_combo.set(self.editing_copy.get_display_name())
        else:
            self.editing_copy = None
            self.app_data.current_material = None
            self.mat_combo.set("")
            self._set_tabs_state("disabled")
            self._update_button_states(False)  # Выключаем кнопки

    def load_material(self, event=None):
        selected_name = self.mat_combo.get()
        material = next((m for m in self.app_data.materials if m.get_display_name() == selected_name), None)
        if material:
            self.app_data.current_material = material
            self.editing_copy = copy.deepcopy(material)
            self._populate_all_tabs()
            self._set_tabs_state("normal")
            self._update_button_states(True)  # Включаем кнопки
            # --- НОВОЕ ИЗМЕНЕНИЕ ---
            self.notebook.select(0)  # Выбираем первую вкладку ("Общие данные")

            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["MATERIAL_SELECTED"],
                event_category="Данные",
                event_action="Выбрано",
                entity={"type": "Материал", "name": material.get_display_name()},
            )

    def create_new_material(self):
        self.editing_copy = Material()
        self.app_data.current_material = None
        self.mat_combo.set(self.editing_copy.filename)
        self._populate_all_tabs()
        self._set_tabs_state("normal")
        self._update_button_states(True)  # Включаем кнопки
        # --- НОВОЕ ИЗМЕНЕНИЕ ---
        self.notebook.select(0)  # Выбираем первую вкладку ("Общие данные")

        self._audit_log(
            event_name=AUDIT_EVENT_NAMES["MATERIAL_CREATE_DRAFT"],
            event_category="Данные",
            event_action="Создано",
            entity={"type": "Материал", "name": self.editing_copy.get_display_name()},
        )

    # --- ПЕРЕМЕЩЕННЫЕ И АДАПТИРОВАННЫЕ МЕТОДЫ ---
    def save_material(self):
        if not self.editing_copy:
            return
        op_id = None
        t0 = None
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if logger:
                op_id = logger.new_operation_id()
                t0 = time.monotonic()
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE"],
                    event_category="Операция",
                    event_action="Старт",
                    operation_id=op_id,
                    data={"операция": "save"},
                )
        except Exception:
            op_id = None
            t0 = None
        self.collect_data()
        material_to_save = self.editing_copy

        original_material = self.app_data.current_material
        changes = None
        if original_material:
            changes = find_changes(original_material.data, material_to_save.data)
            log_changes(material_to_save.get_display_name(), changes)

        changed_fields = self._audit_changes_fields_from_diff(changes)

        if not material_to_save.filepath:
            self.save_material_as()
        else:
            try:
                material_to_save.save()
                tab_groups = self._audit_log_material_save_by_tabs(
                    op_id, material_to_save.get_display_name(), changes,
                    data_extra={"операция": "save"},
                ) or {}
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE"],
                    event_category="Операция",
                    event_action="Финиш",
                    operation_id=op_id,
                    result_ok=True,
                    result_status="Успех",
                    duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                    entity={"type": "Материал", "name": material_to_save.get_display_name()},
                    changes_fields=None,
                    counters={"изменений": len(changed_fields)} if changed_fields else None,
                    data={
                        "операция": "save",
                        "вкладки_с_изменениями": list(tab_groups.keys()),
                    },
                )
                messagebox.showinfo("Успех", f"Материал '{material_to_save.get_display_name()}' сохранен.")
                # Вызываем перезагрузку данных через главный класс
                self.main_app.open_directory(self.app_data.work_dir, show_success_message=False)
            except Exception:
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE"],
                    event_category="Операция",
                    event_action="Финиш",
                    operation_id=op_id,
                    result_ok=False,
                    result_status="Ошибка",
                    result_error_kind="io_error",
                    duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                    entity={"type": "Материал", "name": material_to_save.get_display_name()},
                    data={"операция": "save"},
                )
                messagebox.showerror("Ошибка сохранения", "Не удалось сохранить файл.")

    def save_material_as(self):
        if not self.editing_copy:
            return
        op_id = None
        t0 = None
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if logger:
                op_id = logger.new_operation_id()
                t0 = time.monotonic()
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE_AS"],
                    event_category="Операция",
                    event_action="Старт",
                    operation_id=op_id,
                    data={"операция": "save_as"},
                )
        except Exception:
            op_id = None
            t0 = None
        self.collect_data()
        material_to_save = self.editing_copy

        original_material = self.app_data.current_material
        changes = None
        if original_material:
            changes = find_changes(original_material.data, material_to_save.data)
            log_changes(f"{material_to_save.get_display_name()} (сохранен из {original_material.get_display_name()})",
                        changes)
        else:
            empty_material_data = Material.get_empty_structure()
            changes = find_changes(empty_material_data, material_to_save.data)
            log_changes(material_to_save.get_display_name(), ["Создан новый материал со следующими данными:"] + changes)

        changed_fields = self._audit_changes_fields_from_diff(changes)

        initial_name = material_to_save.get_name().replace(" ", "_") + ".json"
        new_filepath = filedialog.asksaveasfilename(
            initialdir=self.app_data.work_dir, initialfile=initial_name, title="Сохранить материал как...",
            defaultextension=".json", filetypes=[("JSON files", "*.json")])

        if new_filepath:
            try:
                # Обновляем рабочую директорию в app_data через main_app
                self.main_app.app_data.work_dir = os.path.dirname(new_filepath)
                material_to_save.save(filepath=new_filepath)
                tab_groups = self._audit_log_material_save_by_tabs(
                    op_id, material_to_save.get_display_name(), changes,
                    data_extra={"операция": "save_as"},
                ) or {}
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE_AS"],
                    event_category="Операция",
                    event_action="Финиш",
                    operation_id=op_id,
                    result_ok=True,
                    result_status="Успех",
                    duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                    entity={"type": "Материал", "name": material_to_save.get_display_name()},
                    changes_fields=None,
                    counters={"изменений": len(changed_fields)} if changed_fields else None,
                    data={
                        "операция": "save_as",
                        "вкладки_с_изменениями": list(tab_groups.keys()),
                    },
                )
                messagebox.showinfo("Успех", f"Материал сохранен как '{os.path.basename(new_filepath)}'.")
                # Вызываем перезагрузку данных через главный класс
                self.main_app.open_directory(self.app_data.work_dir, show_success_message=False)
            except Exception:
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE_AS"],
                    event_category="Операция",
                    event_action="Финиш",
                    operation_id=op_id,
                    result_ok=False,
                    result_status="Ошибка",
                    result_error_kind="io_error",
                    duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                    entity={"type": "Материал", "name": material_to_save.get_display_name()},
                    data={"операция": "save_as"},
                )
                messagebox.showerror("Ошибка сохранения", "Не удалось сохранить файл.")
        else:
            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["MATERIAL_SAVE_AS"],
                event_category="Операция",
                event_action="Закрыто",
                operation_id=op_id,
                result_ok=False,
                result_status="Отмена",
                result_error_kind="cancelled",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                entity={"type": "Материал", "name": material_to_save.get_display_name()},
                data={"операция": "save_as"},
            )

    def revert_changes(self):
        if not self.editing_copy:
            return

        if not self.app_data.current_material:
            # Если это новый материал (оригинала нет), то просто сбрасываем редактор
            if messagebox.askyesno("Подтверждение", "Вы уверены, что хотите сбросить создание нового материала?"):
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["MATERIAL_RESET_CREATE"],
                    event_category="Данные",
                    event_action="Закрыто",
                    entity={"type": "Материал", "name": self.editing_copy.get_display_name()},
                )
                self.create_new_material()
            return

        if messagebox.askyesno("Подтверждение", "Вы уверены, что хотите отменить все несохраненные изменения?"):
            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["MATERIAL_CANCEL_CHANGES"],
                event_category="Данные",
                event_action="Закрыто",
                entity={"type": "Материал", "name": self.editing_copy.get_display_name()},
            )
            self.load_material()

    def _populate_all_tabs(self):
        if not self.editing_copy:
            return
        self.general_tab.populate_form(self.editing_copy)
        self.phys_tab.populate_form(self.editing_copy)
        self.mech_tab.populate_form(self.editing_copy)
        self.chem_tab.populate_form(self.editing_copy)

    def collect_data(self):
        if not self.editing_copy:
            return
        self.general_tab.collect_data(self.editing_copy)
        self.phys_tab.collect_data(self.editing_copy)
        self.mech_tab.collect_data(self.editing_copy)
        self.chem_tab.collect_data(self.editing_copy)

    def _set_tabs_state(self, state):
        for i in range(self.notebook.index("end")):
            self.notebook.tab(i, state=state)


# ======================================================================================
# БЛОК 7: ГЛАВНЫЕ ФРЕЙМЫ И ЗАПУСК
# ======================================================================================


class ViewerFrame(ttk.Frame):
    """Контейнер для вкладки 'Подбор материала'."""

    def __init__(self, parent, app_data, main_app):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill="both")

        # Вкладки создаются здесь, импортируемые из Блока 5
        self.temp_tab = TempSelectionTab(self.notebook, self.app_data, self.main_app)
        self.calc_tab = SingleCalculationTab(self.notebook, self.app_data, self.main_app)
        self.prop_tab = PropertyComparisonTab(self.notebook, self.app_data, self.main_app)
        self.chem_tab = ChemComparisonTab(self.notebook, self.app_data, self.main_app)
        self.ashby_tab = AshbyDiagramTab(self.notebook, self.app_data, self.main_app)

        self.notebook.add(self.temp_tab, text="Подбор по температуре")
        self.notebook.add(self.calc_tab, text="Расчет отдельно")
        self.notebook.add(self.prop_tab, text="Сравнение материалов (свойства)")
        self.notebook.add(self.chem_tab, text="Сравнение материалов (хим. состав)")
        self.notebook.add(self.ashby_tab, text="Диаграмма Эшби")

    def update_view(self):
        self.temp_tab.update_comboboxes()
        self.calc_tab.update_comboboxes()
        self.prop_tab.update_lists()
        self.chem_tab.update_lists()
        self.ashby_tab.update_lists()


class SourcesManagerTab(ttk.Frame):
    """
    Вкладка для управления источниками (CRUD) с разделением на три группы:
    - Источник свойств
    - Источник категорий прочности
    - Источник хим. свойств
    """

    def __init__(self, parent, app_data, main_app):
        super().__init__(parent)
        self.app_data = app_data
        self.main_app = main_app

        self.current_source_id = None     # ID редактируемого источника
        self.current_group = None         # Текущая группа ("property_sources" / "strength_sources" / "chemical_sources")
        self.current_tree = None          # Текущее дерево, где выбран источник

        self._context_source_id = None    # ID источника для контекстного меню
        self._context_tree = None         # Treeview для контекстного меню

        self._setup_widgets()

    # --- AUDIT (тихо) ---

    def _audit_log(
        self,
        *,
        event_name,
        event_category,
        event_action,
        operation_id=None,
        parent_operation_id=None,
        result_ok=None,
        result_status=None,
        result_error_kind=None,
        duration_ms=None,
        counters=None,
        entity=None,
        changes_fields=None,
        data=None,
    ):
        """Пишет аудит-событие (если audit_logger доступен). Никогда не мешает UI."""
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if not logger:
                return
            logger.log(
                event_name=event_name,
                event_category=event_category,
                event_action=event_action,
                operation_id=operation_id,
                parent_operation_id=parent_operation_id,
                result_ok=result_ok,
                result_status=result_status,
                result_error_kind=result_error_kind,
                duration_ms=duration_ms,
                counters=counters,
                entity=entity,
                changes_fields=changes_fields,
                data=data,
            )
        except Exception:
            return

    def _audit_group_label(self, group_key: str) -> str:
        if group_key == "property_sources":
            return "Источник свойств"
        if group_key == "strength_sources":
            return "Источник категории прочности"
        if group_key == "chemical_sources":
            return "Источник хим. свойств"
        return group_key or ""

    def _audit_entity_for_source(self, src: dict | None, fallback_name: str = "", fallback_id: str = "") -> dict:
        try:
            name = ""
            sid = ""
            if isinstance(src, dict):
                name = str(src.get("name_source", "") or "").strip()
                sid = str(src.get("id_source", "") or "").strip()
            if not name:
                name = str(fallback_name or "").strip()
            if not sid:
                sid = str(fallback_id or "").strip()
            ent = {"type": "Источник", "name": name or "Без названия"}
            if sid:
                ent["id"] = sid
            return ent
        except Exception:
            return {"type": "Источник", "name": "Без названия"}

    def _audit_changed_fields_source(self, old_src: dict | None, new_name: str, new_desc: str, new_link: str) -> list[str]:
        """Сравнение только по трём полям, чтобы получить changes.fields без значений."""
        try:
            fields = []
            old_name = (old_src.get("name_source") if isinstance(old_src, dict) else None)
            old_desc = (old_src.get("description") if isinstance(old_src, dict) else None)
            old_link = (old_src.get("hyperlink") if isinstance(old_src, dict) else None)

            if (old_name or "") != (new_name or ""):
                fields.append("name_source")
            if (old_desc or "") != (new_desc or ""):
                fields.append("description")
            if (old_link or "") != (new_link or ""):
                fields.append("hyperlink")
            return fields
        except Exception:
            return []

    def _setup_widgets(self):
        # --- 1. ВНУТРЕННИЙ NOTEBOOK ДЛЯ ТРЁХ ТИПОВ ИСТОЧНИКОВ ---
        self.inner_notebook = ttk.Notebook(self)
        self.inner_notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self.trees = {}         # group_key -> Treeview
        self.tab_to_group = {}  # tab_widget -> group_key

        groups_def = [
            ("property_sources", "Источник свойств"),
            ("strength_sources", "Источник категории прочности"),
            ("chemical_sources", "Источник хим. свойств"),
        ]

        for group_key, tab_title in groups_def:
            tab = ttk.Frame(self.inner_notebook)
            self.inner_notebook.add(tab, text=tab_title)
            self.tab_to_group[tab] = group_key

            list_frame = ttk.LabelFrame(tab, text="Список источников", padding=5)
            list_frame.pack(fill="both", expand=True, padx=0, pady=5)

            columns = ("name", "desc", "link", "user_c", "date_c", "user_f", "date_f")
            tree = ttk.Treeview(list_frame, columns=columns, show="headings")

            tree.heading("name", text="Наименование")
            tree.column("name", width=250)
            tree.heading("desc", text="Описание")
            tree.column("desc", width=300)
            tree.heading("link", text="Ссылка/Файл")
            tree.column("link", width=150)

            # Служебные поля поуже
            tree.heading("user_c", text="Изм.")
            tree.column("user_c", width=80)
            tree.heading("date_c", text="Дата изм.")
            tree.column("date_c", width=120)
            tree.heading("user_f", text="Созд.")
            tree.column("user_f", width=80)
            tree.heading("date_f", text="Дата созд.")
            tree.column("date_f", width=120)

            vsb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
            hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

            tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")

            list_frame.grid_rowconfigure(0, weight=1)
            list_frame.grid_columnconfigure(0, weight=1)

            # Привязываем обработчики
            tree.bind("<<TreeviewSelect>>", self._on_select)
            tree.bind("<Button-3>", self._on_tree_right_click)  # только контекстное меню для открытия ссылки

            self.trees[group_key] = tree

        # --- 2. ПАНЕЛЬ РЕДАКТИРОВАНИЯ (ОБЩАЯ ДЛЯ ВСЕХ ВКЛАДОК) ---
        edit_frame = ttk.LabelFrame(self, text="Редактирование источника", padding=10)
        edit_frame.pack(fill="x", padx=10, pady=10, side="bottom")

        ttk.Label(edit_frame, text="Наименование:").grid(row=0, column=0, sticky="w", pady=2)
        self.name_entry = ttk.Entry(edit_frame, width=80)
        self.name_entry.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(edit_frame, text="Описание:").grid(row=1, column=0, sticky="w", pady=2)
        self.desc_entry = ttk.Entry(edit_frame, width=80)
        self.desc_entry.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(edit_frame, text="Ссылка/Файл:").grid(row=2, column=0, sticky="w", pady=2)
        self.link_entry = ttk.Entry(edit_frame, width=80)
        self.link_entry.grid(row=2, column=1, sticky="w", pady=2)

        # Кнопки
        btn_frame = ttk.Frame(edit_frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)

        self.btn_new = ttk.Button(btn_frame, text="Новый источник", command=self._create_new)
        self.btn_new.pack(side="left", padx=5)

        self.btn_save = ttk.Button(btn_frame, text="Сохранить изменения",
                                   command=self._save_changes, state="disabled")
        self.btn_save.pack(side="left", padx=5)

        self.btn_del = ttk.Button(btn_frame, text="Удалить источник",
                                  command=self._delete_source, state="disabled")
        self.btn_del.pack(side="left", padx=5)

        self.btn_clear = ttk.Button(btn_frame, text="Очистить поля", command=self._clear_form)
        self.btn_clear.pack(side="left", padx=5)

        # --- 3. КОНТЕКСТНОЕ МЕНЮ ДЛЯ ССЫЛОК ---
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Открыть ссылку", command=self._open_link_from_context)

    # === ОБНОВЛЕНИЕ ДАННЫХ ===

    def update_view(self):
        """Обновляет таблицы во всех трёх вкладках данными из SourceService."""
        self._clear_form()

        for tree in self.trees.values():
            tree.delete(*tree.get_children())

        if not self.app_data.source_manager:
            return

        for group_key, tree in self.trees.items():
            sources = self.app_data.source_manager.get_all(group_key)

            # Сортируем по имени
            sources = list(sources)
            sources.sort(key=lambda s: s.get("name_source", "").lower())

            for src in sources:
                values = (
                    src.get("name_source", ""),
                    src.get("description", ""),
                    src.get("hyperlink", ""),
                    src.get("user_name_change", ""),
                    src.get("data_change", ""),
                    src.get("user_name_found", ""),
                    src.get("data_found", "")
                )
                tree.insert("", "end", iid=src["id_source"], values=values)

    # === ВЫБОР СТРОКИ И РАБОТА С ФОРМОЙ ===

    def _on_select(self, event):
        """Обработчик выбора строки в любом из трёх деревьев."""
        tree = event.widget
        selected = tree.selection()
        if not selected:
            return

        source_id = selected[0]
        self.current_source_id = source_id
        self.current_tree = tree

        # Определяем группу по дереву
        group = None
        for g_key, t in self.trees.items():
            if t is tree:
                group = g_key
                break
        self.current_group = group

        src = self.app_data.source_manager.get_source_by_id(source_id)
        if not src:
            return

        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, src.get("name_source", ""))
        self.desc_entry.delete(0, tk.END)
        self.desc_entry.insert(0, src.get("description", ""))
        self.link_entry.delete(0, tk.END)
        self.link_entry.insert(0, src.get("hyperlink", ""))

        self.btn_save.config(state="normal")
        self.btn_del.config(state="normal")
        self.btn_new.config(state="disabled")

        self._audit_log(
            event_name=AUDIT_EVENT_NAMES["SOURCE_SELECTED"],
            event_category="База",
            event_action="Выбрано",
            entity=self._audit_entity_for_source(src, fallback_id=source_id),
            data={"группа": self.current_group or ""},
        )

    def _clear_form(self):
        """Очищает форму и сбрасывает выбор."""
        self.current_source_id = None
        self.current_group = None
        self.current_tree = None
        self._context_source_id = None
        self._context_tree = None

        self.name_entry.delete(0, tk.END)
        self.desc_entry.delete(0, tk.END)
        self.link_entry.delete(0, tk.END)

        # Снимаем выделение во всех деревьях
        for tree in self.trees.values():
            tree.selection_remove(tree.selection())

        self.btn_save.config(state="disabled")
        self.btn_del.config(state="disabled")
        self.btn_new.config(state="normal")

    # === СОЗДАНИЕ / СОХРАНЕНИЕ / УДАЛЕНИЕ ===

    def _create_new(self):
        """Создаёт новый источник в текущей активной группе."""
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Введите наименование источника.")
            return
        op_id = None
        t0 = None
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if logger:
                op_id = logger.new_operation_id()
                t0 = time.monotonic()
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["SOURCE_CREATE"],
                    event_category="Операция",
                    event_action="Старт",
                    operation_id=op_id,
                )
        except Exception:
            op_id = None
            t0 = None

        desc = self.desc_entry.get().strip()
        link = self.link_entry.get().strip()

        # Определяем группу: либо по текущему выбору, либо по активной вкладке
        group = self.current_group
        if not group:
            tab_id = self.inner_notebook.select()
            tab_widget = self.nametowidget(tab_id)
            group = self.tab_to_group.get(tab_widget, "property_sources")
        self.current_group = group

        # Добавляем источник в выбранную группу
        new_id = self.app_data.source_manager.add_source(name, desc, link, group=group)

        self.update_view()
        # Обновляем списки источников во вкладках редактора,
        # чтобы новый источник сразу был доступен для выбора
        if hasattr(self.main_app, "editor_frame"):
            self.main_app.editor_frame.refresh_sources_in_tabs()
        messagebox.showinfo("Успех", "Источник создан.")

        self._audit_log(
            event_name=AUDIT_EVENT_NAMES["SOURCE_CREATE"],
            event_category="Операция",
            event_action="Финиш",
            operation_id=op_id,
            result_ok=True,
            result_status="Успех",
            duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
            entity={"type": "Источник", "name": name, "id": new_id},
            changes_fields=["name_source", "description", "hyperlink"],
            data={"группа": group, "группа_название": self._audit_group_label(group)},
        )

    def _save_changes(self):
        """Сохраняет изменения в выделенном источнике."""
        if not self.current_source_id:
            return
        op_id = None
        t0 = None
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if logger:
                op_id = logger.new_operation_id()
                t0 = time.monotonic()
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["SOURCE_UPDATE"],
                    event_category="Операция",
                    event_action="Старт",
                    operation_id=op_id,
                    entity={"type": "Источник", "id": self.current_source_id},
                )
        except Exception:
            op_id = None
            t0 = None

        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Наименование не может быть пустым.")
            return

        desc = self.desc_entry.get().strip()
        link = self.link_entry.get().strip()

        old_src = None
        try:
            old_src = self.app_data.source_manager.get_source_by_id(self.current_source_id)
        except Exception:
            old_src = None

        changes_fields = self._audit_changed_fields_source(old_src, name, desc, link)

        success = self.app_data.source_manager.update_source(
            self.current_source_id, name, desc, link
        )
        if success:
            self.update_view()
            # Обновляем списки источников во вкладках редактора,
            # чтобы переименованный источник сразу был виден
            if hasattr(self.main_app, "editor_frame"):
                self.main_app.editor_frame.refresh_sources_in_tabs()
            messagebox.showinfo("Успех", "Изменения сохранены.")

            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["SOURCE_UPDATE"],
                event_category="Операция",
                event_action="Финиш",
                operation_id=op_id,
                result_ok=True,
                result_status="Успех",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                entity={"type": "Источник", "name": name, "id": self.current_source_id},
                changes_fields=changes_fields if changes_fields else None,
                counters={"изменений": len(changes_fields)} if changes_fields else None,
                data={"группа": self.current_group or "", "группа_название": self._audit_group_label(self.current_group or "")},
            )
        else:
            messagebox.showerror("Ошибка", "Не удалось найти источник для обновления.")

            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["SOURCE_UPDATE"],
                event_category="Операция",
                event_action="Финиш",
                operation_id=op_id,
                result_ok=False,
                result_status="Ошибка",
                result_error_kind="not_found",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                entity={"type": "Источник", "name": name, "id": self.current_source_id},
                data={"группа": self.current_group or ""},
            )

    def _delete_source(self, event=None):
        """Удаляет источник, если он не используется ни в одном материале."""
        if not self.current_source_id:
            return
        op_id = None
        t0 = None
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if logger:
                op_id = logger.new_operation_id()
                t0 = time.monotonic()
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["SOURCE_DELETE"],
                    event_category="Операция",
                    event_action="Старт",
                    operation_id=op_id,
                    entity={"type": "Источник", "id": self.current_source_id},
                )
        except Exception:
            op_id = None
            t0 = None

        # 1. ПРОВЕРКА ИСПОЛЬЗОВАНИЯ В МАТЕРИАЛАХ
        usage_count = 0
        used_in = []

        for mat in self.app_data.materials:
            found = False
            for prop in mat.get_physical_properties_list():
                data = Material.get_prop_data(prop) or {}
                if data.get("source_ref_id") == self.current_source_id:
                    usage_count += 1
                    used_in.append(mat.get_display_name())
                    found = True
                    break
            if found:
                continue

            found_in_mech = False
            for cat in mat.get_strength_categories():
                if cat.get("source_ref_id") == self.current_source_id:
                    usage_count += 1
                    used_in.append(mat.get_display_name())
                    found_in_mech = True
                    break
                for entry in cat.get(Schema.PROPERTIES) or []:
                    data = Material.get_prop_data(entry) or {}
                    if data.get("source_ref_id") == self.current_source_id:
                        usage_count += 1
                        used_in.append(mat.get_display_name())
                        found_in_mech = True
                        break
                if found_in_mech:
                    break
            if found_in_mech:
                continue

            for comp in mat.get_compositions():
                if comp.get("source_ref_id") == self.current_source_id:
                    usage_count += 1
                    used_in.append(mat.get_display_name())
                    break

        src = None
        try:
            src = self.app_data.source_manager.get_source_by_id(self.current_source_id)
        except Exception:
            src = None

        if usage_count > 0:
            msg = (
                f"Нельзя удалить источник!\n"
                f"Он используется в {usage_count} материалах, например:\n"
                + "\n".join(used_in[:3])
            )
            if len(used_in) > 3:
                msg += "\n..."
            messagebox.showerror("Ошибка удаления", msg)

            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["SOURCE_DELETE"],
                event_category="Операция",
                event_action="Финиш",
                operation_id=op_id,
                result_ok=False,
                result_status="Ошибка",
                result_error_kind="in_use",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                counters={"материалов": int(usage_count)},
                entity=self._audit_entity_for_source(src, fallback_id=self.current_source_id),
                data={"группа": self.current_group or ""},
            )
            return

        if messagebox.askyesno("Подтверждение", "Вы уверены, что хотите удалить этот источник?"):
            self.app_data.source_manager.delete_source(self.current_source_id)
            self.update_view()
            # Обновляем списки источников во вкладках редактора,
            # чтобы удалённый источник не оставался в выпадающих списках
            if hasattr(self.main_app, "editor_frame"):
                self.main_app.editor_frame.refresh_sources_in_tabs()

            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["SOURCE_DELETE"],
                event_category="Операция",
                event_action="Финиш",
                operation_id=op_id,
                result_ok=True,
                result_status="Успех",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                entity=self._audit_entity_for_source(src, fallback_id=self.current_source_id),
                data={"группа": self.current_group or "", "группа_название": self._audit_group_label(self.current_group or "")},
            )
        else:
            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["SOURCE_DELETE"],
                event_category="Операция",
                event_action="Закрыто",
                operation_id=op_id,
                result_ok=False,
                result_status="Отмена",
                result_error_kind="cancelled",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                entity=self._audit_entity_for_source(src, fallback_id=self.current_source_id),
                data={"группа": self.current_group or ""},
            )

    # === РАБОТА СО ССЫЛКАМИ ===

    def _on_tree_right_click(self, event):
        """
        ПКМ по строке открывает контекстное меню с пунктом 'Открыть ссылку'.
        """
        tree = event.widget
        item = tree.identify_row(event.y)
        if item:
            tree.selection_set(item)
            self._context_tree = tree
            self._context_source_id = item

            src = self.app_data.source_manager.get_source_by_id(item)
            link = (src.get("hyperlink", "").strip() if src else "")
            # Включаем/выключаем пункт меню в зависимости от наличия ссылки
            state = "normal" if link else "disabled"
            self.context_menu.entryconfig(0, state=state)

            self.context_menu.post(event.x_root, event.y_root)

    def _open_link_from_context(self):
        """Открывает ссылку для источника, выбранного через контекстное меню."""
        if not self._context_source_id:
            return
        self._open_file_link_by_id(self._context_source_id)

    def _open_file_link_by_id(self, source_id):
        """Открывает файл или ссылку по ID источника."""
        src = self.app_data.source_manager.get_source_by_id(source_id)
        if not src:
            return

        link = src.get("hyperlink", "").strip()
        if not link:
            return

        op_id = None
        t0 = None
        try:
            logger = getattr(self.main_app, "audit_logger", None)
            if logger:
                op_id = logger.new_operation_id()
                t0 = time.monotonic()
                self._audit_log(
                    event_name=AUDIT_EVENT_NAMES["SOURCE_OPEN_LINK"],
                    event_category="Операция",
                    event_action="Старт",
                    operation_id=op_id,
                    entity=self._audit_entity_for_source(src, fallback_id=source_id),
                    data={"группа": self.current_group or ""},
                )
        except Exception:
            op_id = None
            t0 = None

        self._audit_log(
            event_name=AUDIT_EVENT_NAMES["SOURCE_OPEN_LINK"],
            event_category="База",
            event_action="Открыто",
            entity=self._audit_entity_for_source(src, fallback_id=source_id),
            data={"группа": self.current_group or ""},
        )

        # Если это локальный путь и он относительный, пробуем найти в папке Источники
        if not os.path.isabs(link) and not link.lower().startswith(("http://", "https://")):
            sources_dir = os.path.join(get_app_directory(), "Источники")
            potential_path = os.path.join(sources_dir, link)
            if os.path.exists(potential_path):
                link = potential_path

        try:
            if sys.platform == "win32":
                os.startfile(link)
            elif sys.platform == "darwin":
                subprocess.call(["open", link])
            else:
                subprocess.call(["xdg-open", link])
            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["SOURCE_OPEN_LINK"],
                event_category="Операция",
                event_action="Финиш",
                operation_id=op_id,
                result_ok=True,
                result_status="Успех",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                entity=self._audit_entity_for_source(src, fallback_id=source_id),
                data={"группа": self.current_group or ""},
            )
        except Exception as e:
            self._audit_log(
                event_name=AUDIT_EVENT_NAMES["SOURCE_OPEN_LINK"],
                event_category="Операция",
                event_action="Финиш",
                operation_id=op_id,
                result_ok=False,
                result_status="Ошибка",
                result_error_kind="io_error",
                duration_ms=((time.monotonic() - t0) * 1000.0 if t0 is not None else None),
                entity=self._audit_entity_for_source(src, fallback_id=source_id),
                data={"группа": self.current_group or ""},
            )
            messagebox.showerror("Ошибка", f"Не удалось открыть: {e}")


class MainApplication(tk.Tk):
    APP_VERSION = "2.1.20"

    def __init__(self):
        super().__init__()
        self.app_data = MaterialRepository()
        self.title(f"Material_Lib ({self.APP_VERSION})")
        self.geometry("1200x800")

        # --- AUDIT (тихо, для аналитики) ---
        self.audit_logger = None
        self._audit_session_t0 = None
        self._audit_session_finished = False

        # Этот код для горячих клавиш можно оставить или убрать, если он не работает
        self.bind_class("Entry", "<KeyPress>", self._handle_russian_hotkeys)
        self.bind_class("Text", "<KeyPress>", self._handle_russian_hotkeys)
        self.bind_class("ttk::Combobox", "<KeyPress>", self._handle_russian_hotkeys)

        self.create_menu()
        self.create_widgets()

        # Инициализация аудита после создания виджетов (чтобы можно было навесить хуки на Notebook)
        self._init_audit_logger()

        # Автозагрузка
        try:
            default_dir = os.path.join(get_app_directory(), "БД Материалов")
            if os.path.isdir(default_dir):
                self.open_directory(directory=default_dir, show_success_message=False)
        except Exception as e:
            print(f"Ошибка автозагрузки: {e}")

    # --- AUDIT: инициализация/завершение/навигация ---

    def _init_audit_logger(self):
        """Инициализирует AuditLogger. Ошибки не показываем пользователю."""
        try:
            from audit_logger import AuditLogger
            import atexit
            import time
        except Exception:
            return

        try:
            # app_id/app_version должны быть стабильными для дашборда
            self.audit_logger = AuditLogger(app_id="material_lib", app_version=self.APP_VERSION)
            self._audit_session_t0 = time.monotonic()
            self.audit_logger.log_session_start()
        except Exception:
            self.audit_logger = None
            self._audit_session_t0 = None
            return

        # Закрытие окна: фиксируем завершение сессии и корректно останавливаем writer
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        except Exception:
            pass

        # Подстраховка: если закрытие прошло нештатно
        try:
            atexit.register(self._on_app_exit_atexit)
        except Exception:
            pass

        # Навигация по вкладкам (верхние уровни)
        try:
            self.after(0, self._bind_audit_navigation_hooks)
        except Exception:
            pass

    def _bind_audit_navigation_hooks(self):
        """Навешивает аудит на смену вкладок (NotebookTabChanged)."""
        if not self.audit_logger:
            return

        def bind_notebook(nb, container_name: str):
            try:
                nb.bind(
                    "<<NotebookTabChanged>>",
                    lambda e, n=nb, c=container_name: self._audit_on_notebook_tab_changed(c, n)
                )
            except Exception:
                pass

        # Главные вкладки приложения
        if hasattr(self, "main_notebook"):
            bind_notebook(self.main_notebook, "Main")

        # Вкладки подбора материала
        try:
            if getattr(self, "viewer_frame", None) and hasattr(self.viewer_frame, "notebook"):
                bind_notebook(self.viewer_frame.notebook, "Viewer")
        except Exception:
            pass

        # Вкладки редактора материала
        try:
            if getattr(self, "editor_frame", None) and hasattr(self.editor_frame, "notebook"):
                bind_notebook(self.editor_frame.notebook, "Editor")
        except Exception:
            pass

        # Вкладки источников (внутренний notebook)
        try:
            if getattr(self, "sources_frame", None) and hasattr(self.sources_frame, "inner_notebook"):
                bind_notebook(self.sources_frame.inner_notebook, "Sources")
        except Exception:
            pass

    def _audit_on_notebook_tab_changed(self, container_name: str, nb):
        """Логирует смену вкладки (тихо)."""
        if not self.audit_logger:
            return
        try:
            tab_id = nb.select()
            tab_text = nb.tab(tab_id, "text") if tab_id else ""
        except Exception:
            tab_text = ""

        try:
            self.audit_logger.log(
                event_name=AUDIT_EVENT_NAMES["NAV_TAB_SELECTED"],
                event_category="Навигация",
                event_action="Выбрано",
                data={
                    "контейнер": container_name,
                    "вкладка": tab_text or "",
                }
            )
        except Exception:
            pass

    def _audit_finish_session(self, ok: bool = True):
        """Пишет 'Сессия: завершение' один раз."""
        if self._audit_session_finished:
            return
        self._audit_session_finished = True

        if not self.audit_logger:
            return

        duration_ms = None
        try:
            import time
            if self._audit_session_t0 is not None:
                duration_ms = (time.monotonic() - self._audit_session_t0) * 1000.0
        except Exception:
            duration_ms = None

        try:
            self.audit_logger.log_session_end(duration_ms=duration_ms, ok=ok)
        except Exception:
            pass

        try:
            self.audit_logger.shutdown(timeout_sec=1.5)
        except Exception:
            pass

    def _on_app_close(self):
        """Закрытие окна пользователем (WM_DELETE_WINDOW)."""
        self._audit_finish_session(ok=True)
        try:
            self.destroy()
        except Exception:
            pass

    def _on_app_exit_atexit(self):
        """Фолбэк на случай нештатного завершения."""
        self._audit_finish_session(ok=True)

    def quit(self):
        """Перехватываем quit, чтобы гарантированно записать завершение сессии."""
        self._audit_finish_session(ok=True)
        try:
            super().quit()
        except Exception:
            pass

    def _handle_russian_hotkeys(self, event):
        is_ctrl_pressed = (event.state & 4) != 0
        if is_ctrl_pressed:
            key = event.keysym.lower()
            if key == 'с':
                event.widget.event_generate("<<Copy>>")
                return "break"
            elif key == 'м':
                event.widget.event_generate("<<Paste>>")
                return "break"
            elif key == 'ч':
                event.widget.event_generate("<<Cut>>")
                return "break"
            elif key == 'ф':
                if isinstance(event.widget, tk.Text):
                    event.widget.tag_add("sel", "1.0", "end")
                elif isinstance(event.widget, tk.Entry):
                    event.widget.selection_range(0, 'end')
                return "break"

    def create_menu(self):
        self.menu_bar = tk.Menu(self)
        self.config(menu=self.menu_bar)

        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(label="Открыть директорию...", command=self.open_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.quit)

        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Справка", menu=help_menu)
        help_menu.add_command(label="Инструкция", command=self.show_instructions)
        help_menu.add_command(label="О приложении", command=self.show_about_info)
        help_menu.add_command(label="Список изменений", command=self.show_change)

    def create_widgets(self):
        self.main_notebook = ttk.Notebook(self)
        self.main_notebook.pack(expand=True, fill="both", padx=10, pady=10)

        self.viewer_frame = ViewerFrame(self.main_notebook, self.app_data, self)
        self.editor_frame = EditorFrame(self.main_notebook, self.app_data, self)
        self.sources_frame = SourcesManagerTab(self.main_notebook, self.app_data, self)

        self.main_notebook.add(self.viewer_frame, text="Подбор материала")
        self.main_notebook.add(self.editor_frame, text="Добавление / Редактирование материала")
        self.main_notebook.add(self.sources_frame, text="Работа с источниками")

    def open_directory(self, directory=None, show_success_message=True):
        # AUDIT: операция импорта (без путей)
        op_id = None
        t0 = None
        manual_choice = False
        if self.audit_logger:
            try:
                import time
                op_id = self.audit_logger.new_operation_id()
                t0 = time.monotonic()
                manual_choice = (directory is None)
                self.audit_logger.log(
                            event_name=AUDIT_EVENT_NAMES["IMPORT_OPEN_DIR"],
                    event_category="Импорт",
                    event_action="Старт",
                    operation_id=op_id,
                    data={"выбор_пользователя": bool(manual_choice)},
                )
            except Exception:
                op_id = None
                t0 = None

        if not directory:
            filepath = filedialog.askopenfilename(title="Выберите любой .json", filetypes=[("JSON files", "*.json")])
            if filepath:
                directory = os.path.dirname(filepath)
            else:
                # AUDIT: отмена выбора
                if self.audit_logger and op_id:
                    try:
                        import time
                        duration_ms = (time.monotonic() - t0) * 1000.0 if t0 is not None else None
                        self.audit_logger.log(
                            event_name=AUDIT_EVENT_NAMES["IMPORT_OPEN_DIR"],
                            event_category="Импорт",
                            event_action="Закрыто",
                            operation_id=op_id,
                            result_ok=False,
                            result_status="Отмена",
                            result_error_kind="cancelled",
                            duration_ms=duration_ms,
                            data={"выбор_пользователя": True},
                        )
                    except Exception:
                        pass
                return

        if directory:
            try:
                self.app_data.load_materials_from_dir(directory)
                if show_success_message:
                    messagebox.showinfo("Успех", f"Загружено {len(self.app_data.materials)} материалов.")
                self.on_data_load()

                # AUDIT: финиш импорта
                if self.audit_logger and op_id:
                    try:
                        import time
                        duration_ms = (time.monotonic() - t0) * 1000.0 if t0 is not None else None
                        self.audit_logger.log(
                            event_name=AUDIT_EVENT_NAMES["IMPORT_OPEN_DIR"],
                            event_category="Импорт",
                            event_action="Финиш",
                            operation_id=op_id,
                            result_ok=True,
                            result_status="Успех",
                            duration_ms=duration_ms,
                            counters={"материалов": int(len(self.app_data.materials))},
                            data={"выбор_пользователя": bool(manual_choice)},
                        )
                    except Exception:
                        pass

            except Exception as e:
                messagebox.showerror("Ошибка", f"Сбой загрузки: {e}")

                # AUDIT: ошибка импорта
                if self.audit_logger and op_id:
                    try:
                        import time
                        duration_ms = (time.monotonic() - t0) * 1000.0 if t0 is not None else None
                        self.audit_logger.log(
                            event_name=AUDIT_EVENT_NAMES["IMPORT_OPEN_DIR_ERROR"],
                            event_category="Импорт",
                            event_action="Ошибка",
                            operation_id=op_id,
                            result_ok=False,
                            result_status="Ошибка",
                            result_error_kind="io_error",
                            duration_ms=duration_ms,
                            data={"выбор_пользователя": bool(manual_choice)},
                        )
                    except Exception:
                        pass

    def on_data_load(self):
        self.editor_frame.editing_copy = None
        self.app_data.current_material = None
        self.viewer_frame.update_view()
        self.editor_frame.update_view()
        self.sources_frame.update_view()

    def show_about_info(self):
        if self.audit_logger:
            try:
                self.audit_logger.log(
                    event_name=AUDIT_EVENT_NAMES["HELP_ABOUT_OPEN"],
                    event_category="Навигация",
                    event_action="Открыто",
                )
            except Exception:
                pass

        title = "О приложении"
        message = read_text_from_file("app_list.txt")
        messagebox.showinfo(title, message, parent=self)

    def show_instructions(self):
        if self.audit_logger:
            try:
                self.audit_logger.log(
                    event_name=AUDIT_EVENT_NAMES["HELP_INSTRUCTIONS_OPEN"],
                    event_category="Навигация",
                    event_action="Открыто",
                )
            except Exception:
                pass

        instr_window = tk.Toplevel(self)
        instr_window.title("Инструкция по использованию")
        instr_window.geometry("750x600")
        instr_window.minsize(500, 400)
        instruction_text = read_text_from_file("instruction_list.txt")
        text_frame = ttk.Frame(instr_window, padding=10)
        text_frame.pack(fill="both", expand=True)
        text_widget = tk.Text(text_frame, wrap=tk.WORD, state="disabled", font=("Arial", 10), padx=5, pady=5)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text_widget.pack(side="left", fill="both", expand=True)
        text_widget.config(state="normal")
        text_widget.insert("1.0", instruction_text.strip())
        text_widget.config(state="disabled")
        ok_button = ttk.Button(instr_window, text="OK", command=instr_window.destroy)
        ok_button.pack(pady=(0, 10))

    def show_change(self):
        if self.audit_logger:
            try:
                self.audit_logger.log(
                    event_name=AUDIT_EVENT_NAMES["HELP_CHANGELOG_OPEN"],
                    event_category="Навигация",
                    event_action="Открыто",
                )
            except Exception:
                pass

        instr_window = tk.Toplevel(self)
        instr_window.title("Список изменений")
        instr_window.geometry("750x600")
        instr_window.minsize(500, 400)
        instruction_text = read_text_from_file("change_list.txt")
        text_frame = ttk.Frame(instr_window, padding=10)
        text_frame.pack(fill="both", expand=True)
        text_widget = tk.Text(text_frame, wrap=tk.WORD, state="disabled", font=("Arial", 10), padx=5, pady=5)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text_widget.pack(side="left", fill="both", expand=True)
        text_widget.config(state="normal")
        text_widget.insert("1.0", instruction_text.strip())
        text_widget.config(state="disabled")
        ok_button = ttk.Button(instr_window, text="OK", command=instr_window.destroy)
        ok_button.pack(pady=(0, 10));


if __name__ == "__main__":
    app = MainApplication()
    app.mainloop()
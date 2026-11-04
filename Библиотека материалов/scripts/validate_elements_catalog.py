import os
import sys
import json


def is_valid_json_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            json.load(f)
        return True
    except (json.JSONDecodeError, FileNotFoundError, PermissionError):
        return False


def is_utf8(p):
    with open(p, 'rb') as f:
        d = f.read()
    try:
        t = d.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def is_key(d, q):
    try:
        a = d[q]
        return True
    except KeyError:
        return False


f = 0
errors = []
path_to_elements_catalog = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "elements_catalog.json")
if os.path.exists(path_to_elements_catalog):
    if is_valid_json_file(path_to_elements_catalog):
        if is_utf8(path_to_elements_catalog):
            with open(path_to_elements_catalog,"r", encoding="utf-8") as file:
                elements = json.load(file)
                if is_key(elements, "schema_version"):
                    elements = elements["elements"]
                    if len(elements) > 0:
                        r = {"symbol", "name", "color"}
                        symbols = set()
                        names = set()
                        color_format = "0123456789ABCDEF"
                        for i in elements:
                            if not r <= set(i.keys()):
                                f = 1
                                for j in r:
                                    if j not in i.keys():
                                        errors.append(f"У элемента {i} нет поля {j}")
                                        if j != "symbol":
                                            symbols.add(i["symbol"])
                                            if not i["symbol"] == "РЗМ" and not i["symbol"].isascii():
                                                f = 1
                                                errors.append(f"У элемента {i} поле symbol не ASCII")
                                        elif j != "name":
                                            names.add(i["name"])
                                            if i["name"] == "" or i["name"] is None:
                                                f = 1
                                                errors.append(f"У элемента {i} пустое поле name")
                                        elif j != "color":
                                            if not i["symbol"] == 'Cs' and not i["color"] is None and i["color"][0] == "#" and len(i["color"]) == 7:
                                                for ii in i["color"][1:]:
                                                    if ii not in color_format:
                                                        f = 1
                                                        errors.append(f"У элемента {i} неправильный формат цвета")
                                            elif i["symbol"] == 'Cs':
                                                pass
                                            else:
                                                f = 1
                                                errors.append(f"У элемента {i} неправильный формат цвета")
                            else:
                                if not i["symbol"] == "РЗМ" and not i["symbol"].isascii():
                                    f = 1
                                    errors.append(f"У элемента {i} поле symbol не ASCII")
                                if i["name"] == "" or i["name"] is None:
                                    f = 1
                                    errors.append(f"У элемента {i} пустое поле name")
                                if not i["symbol"] == 'Cs' and not i["color"] is None and i["color"][0] == "#" and len(i["color"]) == 7:
                                    for ii in i["color"][1:]:
                                        if ii not in color_format:
                                            f = 1
                                            errors.append(f"У элемента {i} неправильный формат цвета")

                                elif i["symbol"] == 'Cs':
                                    pass
                                else:
                                    f = 1
                                    errors.append(f"У элемента {i} неправильный формат цвета")
                            if not i["display_symbol"] is None:
                                if i["display_symbol"] == "":
                                    f = 1
                                    errors.append(f"У элемента {i} поле display_symbol задано, но является пустой строкой")
                            if i == "N":
                                if i["display_symbol"] != "N₂":
                                    f = 1
                                    errors.append("У элемента N поле display_symbol не N₂")
                            elif i == "O":
                                if i["display_symbol"] != "O₂":
                                    f = 1
                                    errors.append("У элемента O поле display_symbol не O₂")
                            elif i == "H":
                                if i["display_symbol"] != "H₂":
                                    f = 1
                                    errors.append("У элемента H поле display_symbol не H₂")
                    else:
                        f = 1
                        errors.append("elements - пустой массив")
                else:
                    f = 1
                    errors.append("Нет поля schema_version")
        else:
            f = 1
            errors.append("Неверная кодировка")
    else:
        f = 1
        errors.append("Не валидный json файл")
else:
    f = 1
    errors.append("json файла нет")

# Добавляем родительскую папку в путь поиска Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import ChemicalCompositionTab, ChemComparisonTab

tech_key = ChemicalCompositionTab.ELEMENTS_MAP
o = object.__new__(ChemComparisonTab)
o.__init__(None, None, None)
display = getattr(o, 'element_tooltips', {})
with open(path_to_elements_catalog, "r", encoding="utf-8") as file:
    elements = json.load(file)
    elements = elements["elements"]
e = []
for i in elements:
    e.append(i["symbol"])
a = set(tech_key.keys())
for i in display.keys():
    q = i[:-1] if i[-1].isdigit() else i
    g = 0
    for ii in e:
        if q == ii:
            g = 1
    if not g:
        f = 1
        errors.append("Не все элементы из element_tooltips покрыты как symbol или алиас")
for i in elements:
    try:
        q = display[i["symbol"]]
        if i["influence"] is None:
            f = 1
            errors.append("Не у всех элементов из element_tooltips есть influence")
            break
    except KeyError:
        pass
for i in tech_key.keys():
    for ii in elements:
        if ii["symbol"] == i:
            if tech_key[i]["color"] != ii["color"]:
                f = 1
                errors.append("У элементов из ELEMENTS_MAP не совпадает цвет со значение в каталоге")
for i in errors:
    print(i)
exit(f)


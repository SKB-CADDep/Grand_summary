import json
import sys
import os


if len(sys.argv) > 1 and sys.argv[1] == "--validate":
    import validate_elements_catalog
# Добавляем родительскую папку в путь поиска Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import ChemicalCompositionTab, ChemComparisonTab
o = object.__new__(ChemComparisonTab)
o.__init__(None, None, None)
display = getattr(o, 'element_tooltips', {})
tech_key = ChemicalCompositionTab.ELEMENTS_MAP
#   Элемента "P+S" нет
lower_indexes = "₀₁₂₃₄₅₆₇₈₉"
elements = []
e = []
a = []
tech_key_only = 0
display_only = 0
for i in display.keys():
    q = i
    r = ""
    f = 0
    while q[-1].isdigit():
        q = i[:-1]
        r = lower_indexes[int(i[-1])] + r
        f += 1
    if f:
        a.append([i, q, q + r])
    e.append(q)
    try:
        w = tech_key[q]
        elements.append(
            {
                "symbol": q,
                "display_symbol": q + r,
                "name": w["name"],
                "color": w["color"],
                "influence": display[i]
            }
        )
    except KeyError:
        display_only += 1
        elements.append(
            {
                "symbol": q,
                "display_symbol": i,
                "name": display[i][:display[i].find(".")],
                "color": None,
                "influence": display[i]
            }
        )
for i in tech_key.keys():
    if i not in e:
        tech_key_only += 1
        elements.append(
            {
                "symbol": i,
                "display_symbol": i,
                "name": tech_key[i]["name"],
                "color": tech_key[i]["color"],
                "influence": None
            }
        )
elements = {
    "schema_version": "1.0",
    "elements": sorted(elements, key=lambda x: x["name"])
}
q = len(elements["elements"])
print(f"Всего элементов - {q}")
print(f"С influence - {len(display)}, без - {q - len(display)}")
print(f"Только в ELEMENTS_MAP - {tech_key_only}, только в element_tooltips - {display_only}")
print("Обработанные алиасы:")
for i in a: print(f"{i[0]} → {i[1]} + display_symbol: {i[2]}")
path_to_json = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "elements_catalog.json")
with open(path_to_json, "w", encoding="utf-8") as f:
    json.dump(elements, f, ensure_ascii=False, indent=4)

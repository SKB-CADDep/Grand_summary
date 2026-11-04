from __future__ import annotations

import json
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from sqlalchemy.orm import Session

from backend.models import Version, Workbook
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from src.catalog import columns, parameters
from src.services.workbooks import hyperlinks_map, snapshot_cells

YELLOW = "FFFF99"
GREEN = "C6EFCE"

SHORT_NOZZLE_ROWS = [
    ("r010", "Высота лопаток lc, мм"),
    ("r012", "Ширина профиля в корне в рабочем положении, мм"),
    ("r013", "Корневой диаметр D'к, мм по выходной кромке"),
    ("r014", "Средний диаметр D'ср, мм"),
    ("r028", "Угол наружного обвода, °"),
    ("r027", "Угол внутреннего обвода, °"),
    ("r026", "Наружный диаметр обода, мм"),
    ("r021", "Тип исполнения"),
    ("r023", "Ширина зуба обода, мм"),
    ("r022", "Ширина тела, мм"),
    ("r035", "Диаметр по диафрагменным уплотнениям, мм"),
]

SHORT_ROTOR_ROWS = [
    ("r083", "Ширина обода диска, мм"),
    ("r047", "Высота лопаток Lр, мм"),
    ("r049", "Диаметр средний Dср, мм"),
    ("r048", "Диаметр корневой Dк, мм"),
    ("r084", "Конусность диска"),
    ("r060", "Тип хвостовика"),
    ("r061", "№ черт. хвостовика"),
    ("r062", "Ширина шейки, мм"),
    ("r063", "Высота промтела, мм"),
]


def _stage_columns() -> list[dict]:
    return [item for item in columns() if item["kind"] == "stage"]


def _seal_columns() -> list[dict]:
    return [item for item in columns() if item["kind"] in {"pku", "zku"}]


def _set_cell_shading(cell, fill: str | None) -> None:
    if not fill:
        return
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    shd.set(qn("w:val"), "clear")
    tc_pr.append(shd)


def _fill_for(current: str | None, baseline: str | None, has_value: bool) -> str | None:
    if current is None or current == "":
        return None
    if baseline is None or baseline == "":
        return GREEN if has_value else None
    if current != baseline:
        return YELLOW
    return None


def _add_hyperlink(paragraph, text: str, url: str) -> None:
    part = paragraph.part
    rel = part.relate_to(url, RT.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    r_pr.append(color)
    r_pr.append(underline)
    run.append(r_pr)
    text_el = OxmlElement("w:t")
    text_el.text = text
    run.append(text_el)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _write_matrix(
    document: Document,
    title: str,
    row_specs: list[tuple[str, str]],
    col_specs: list[dict],
    current: dict[str, dict[str, str | None]],
    baseline: dict[str, dict[str, str | None]] | None,
    links: dict[str, dict[str, str]] | None = None,
) -> None:
    document.add_paragraph(title)
    table = document.add_table(rows=1 + len(row_specs), cols=1 + len(col_specs))
    table.style = "Table Grid"
    table.cell(0, 0).text = "Наименование параметра"
    for index, col in enumerate(col_specs, start=1):
        table.cell(0, index).text = col["label"]
    for row_index, (param_key, label) in enumerate(row_specs, start=1):
        table.cell(row_index, 0).text = label
        for col_index, col in enumerate(col_specs, start=1):
            value = (current.get(param_key) or {}).get(col["key"])
            old = (baseline.get(param_key) or {}).get(col["key"]) if baseline else None
            cell = table.cell(row_index, col_index)
            url = ((links or {}).get(param_key) or {}).get(col["key"])
            cell.text = ""
            paragraph = cell.paragraphs[0]
            if url and value:
                _add_hyperlink(paragraph, str(value), url)
            else:
                paragraph.add_run(value or "")
            _set_cell_shading(cell, _fill_for(value, old, bool(value)))


def preview_tables(
    workbook: Workbook,
    report_type: str,
    compare_version: Version | None,
) -> list[dict]:
    current = snapshot_cells(workbook)
    baseline = json.loads(compare_version.snapshot_json) if compare_version else None
    obj = workbook.object
    cylinder = obj.cylinder or "ПЧ"
    turbine = obj.turbine or ""
    stages = _stage_columns()
    seals = _seal_columns()

    def matrix(title: str, specs: list[tuple[str, str]], cols: list[dict]) -> dict:
        rows = []
        for key, label in specs:
            cells = []
            for col in cols:
                value = (current.get(key) or {}).get(col["key"]) or ""
                old = (baseline.get(key) or {}).get(col["key"]) if baseline else None
                fill = _fill_for(value, old, bool(value))
                changed = fill is not None
                cells.append(
                    {
                        "column_key": col["key"],
                        "value": value,
                        "changed": changed,
                        "fill": fill,
                    }
                )
            rows.append({"parameter_key": key, "label": label, "cells": cells})
        return {"title": title, "columns": cols, "rows": rows}

    if report_type == "full":
        specs = [(item["key"], item["label"]) for item in parameters() if item["row_kind"] != "section"]
        return [matrix("Полная гранд-сводка ИД", specs, stages + seals)]
    return [
        matrix("Диаметры концевых уплотнений", [("r098", "Диаметр бочки ротора, мм"), ("r099", "Количество дросселей"), ("r100", "Радиальный зазор, мм")], seals),
        matrix(f"Таблица 1 – Диафрагмы и направляющие лопатки {cylinder} {turbine}", SHORT_NOZZLE_ROWS, stages),
        matrix(f"Таблица 2 – Диски и рабочие лопатки {cylinder} {turbine}", SHORT_ROTOR_ROWS, stages),
    ]


def build_report_docx(
    session: Session,
    workbook: Workbook,
    report_type: str,
    compare_version: Version | None,
    extra_notes: str = "",
) -> bytes:
    current = snapshot_cells(workbook)
    links = hyperlinks_map(workbook)
    baseline = json.loads(compare_version.snapshot_json) if compare_version else None
    obj = workbook.object
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    header = document.add_paragraph()
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.add_run("СКБт\nОР").bold = True

    document.add_paragraph("Начальнику ОПТ")
    document.add_paragraph("И.О.Ф.")
    document.add_paragraph("Копия: Главному конструктору")
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("СЛУЖЕБНАЯ ЗАПИСКА")
    run.bold = True
    run.font.size = Pt(14)

    turbine = obj.turbine or "К-ХХХ"
    station = obj.station or "ХХ"
    cylinder = obj.cylinder or "ПЧ"
    document.add_paragraph(
        f"Об ИД по ПЧ {cylinder} турбин {station} ({turbine})"
    )
    document.add_paragraph(
        f"Уважаемый И.О.!\nВ рамках конструкторской подготовки производства по турбинам {turbine} "
        f"для {station} направляем Вам предварительные данные для разработки чертежа проточной части "
        f"{cylinder}."
    )
    document.add_paragraph(
        "В Приложении 1 представлены данные по основной геометрии направляющих лопаток (таблица 1), "
        "рабочих лопаток (таблица 2)."
    )

    if extra_notes.strip():
        document.add_paragraph("Примечания")
        document.add_paragraph(extra_notes.strip())

    seal_rows = [
        ("r098", "Диаметр бочки ротора, мм"),
        ("r099", "Количество дросселей"),
        ("r100", "Радиальный зазор, мм"),
    ]
    document.add_paragraph("Таблица – Диаметры концевых уплотнений")
    _write_matrix(document, "", seal_rows, _seal_columns(), current, baseline, links)

    stages = _stage_columns()
    if report_type == "full":
        grouped: list[tuple[str, str]] = []
        for item in parameters():
            if item["row_kind"] == "section":
                continue
            grouped.append((item["key"], item["label"]))
        _write_matrix(
            document,
            "Приложение 1 – Полная гранд-сводка ИД",
            grouped,
            stages + _seal_columns(),
            current,
            baseline,
            links,
        )
    else:
        _write_matrix(
            document,
            f"Таблица 1 – Данные по диафрагмам и направляющим лопаткам {cylinder} {turbine}",
            SHORT_NOZZLE_ROWS,
            stages,
            current,
            baseline,
            links,
        )
        _write_matrix(
            document,
            f"Таблица 2 – Данные по дискам и рабочим лопаткам {cylinder} {turbine}",
            SHORT_ROTOR_ROWS,
            stages,
            current,
            baseline,
            links,
        )

    footer = document.add_paragraph()
    footer.add_run("Начальник отдела").italic = True
    footer.add_run("\nИ.О.Ф.")
    note = document.add_paragraph()
    note.add_run("Жёлтый — изменение относительно выбранной версии; зелёный — новое значение. ").font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    note.add_run("Комментарии в отчёт не включаются.")

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()

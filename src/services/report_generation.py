from __future__ import annotations

import json
import re
from io import BytesIO

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Mm, Pt, RGBColor
from sqlalchemy.orm import Session

from backend.models import Version, Workbook
from src.services import workbooks as workbook_service
from src.services.triangle_import import triangle_synced_parameter_keys
from src.services.workbooks import (
    _display,
    effective_cells,
    hyperlinks_map,
    report_notes,
    snapshot_cells,
    workbook_columns,
    workbook_parameters,
)

HEADER_FILL = "D9EAF7"
YELLOW = "FFFF99"
GREEN = "C6EFCE"
_A3_LANDSCAPE_WIDTH = Mm(420)
_A3_LANDSCAPE_HEIGHT = Mm(297)
_MARGIN_LR_EMU = 320040
_MARGIN_TB_EMU = 365760
_PAGE_CONTENT_TWIPS = (15_120_000 - 2 * _MARGIN_LR_EMU) // 635
_NAME_WIDTH = 4431
_DESIGNATION_WIDTH = 1280
_UNIT_WIDTH = 1108
_MIN_STAGE_WIDTH = 700
_FROZEN_HEADERS = ("Наименование параметра", "Обозначение", "Ед. изм.")
REPORT_NOTE_NAME = "__name__"
REPORT_NOTE_UNIT = "__unit__"
_SUPER_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def note_marker(number: int) -> str:
    return "*" + str(number).translate(_SUPER_DIGITS)


def format_cell_with_notes(value: str, numbers: list[int]) -> str:
    suffix = "".join(note_marker(item) for item in numbers)
    return f"{value or ''}{suffix}"


def notes_for_export(notes: list[dict], parameter_keys: set[str], column_keys: set[str]) -> list[dict]:
    exported = []
    for note in notes:
        param = note.get("parameter_key") or ""
        column = note.get("column_key") or ""
        if param not in parameter_keys:
            continue
        if column in {REPORT_NOTE_NAME, REPORT_NOTE_UNIT} or column in column_keys:
            exported.append(note)
    return exported
_PAREN_GROUPS = re.compile(r"\(([^()]*)\)")
_FACTORY_NUMBER = re.compile(r"\(зав\.([^)]+)\)")

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

GROUP_TITLES = {
    "r005": "Данные по направляющим лопаткам и диафрагмам ступеней {cylinder}",
}


def _stage_columns(workbook: Workbook) -> list[dict]:
    return [item for item in workbook_columns(workbook) if item.get("kind") == "stage"]


def _seal_columns(workbook: Workbook) -> list[dict]:
    return [item for item in workbook_columns(workbook) if item.get("kind") in {"pku", "zku"}]


def parameter_designation(param: dict) -> str:
    if (param.get("key") or "") not in triangle_synced_parameter_keys():
        return ""
    groups = _PAREN_GROUPS.findall(param.get("label") or "")
    if not groups:
        return ""
    return groups[-1].strip().rstrip(",").strip()


def parameter_display_label(param: dict) -> str:
    label = param.get("label") or ""
    unit = param.get("unit") or ""
    if unit and label.endswith(f", {unit}"):
        label = label[: -len(unit) - 2].strip()
    if parameter_designation(param):
        match = None
        for match in _PAREN_GROUPS.finditer(label):
            pass
        if match is not None:
            label = f"{label[: match.start()]}{label[match.end() :]}"
    return " ".join(label.replace(" ,", " ").split()).strip(" ,")


def _set_run_font(run, size_pt: int) -> None:
    run.font.name = "Times New Roman"
    run.font.size = Pt(size_pt)
    r_pr = run._element.get_or_add_rPr()
    fonts = r_pr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        r_pr.append(fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), "Times New Roman")


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


def _selected(keys: list[str] | None) -> set[str] | None:
    cleaned = [key for key in (keys or []) if key]
    return set(cleaned) if cleaned else None


def _filter_specs(specs: list[tuple[str, str]], selected_keys: set[str] | None) -> list[tuple[str, str]]:
    if not selected_keys:
        return specs
    return [item for item in specs if item[0] in selected_keys]


def report_snapshot_cells(
    workbook: Workbook,
    compare_version: Version | None = None,
    selected_parameter_keys: list[str] | None = None,
) -> dict[str, dict[str, str | None]]:
    snapshot = snapshot_cells(workbook)
    selected_keys = _selected(selected_parameter_keys)
    if not selected_keys:
        return snapshot
    return {key: value for key, value in snapshot.items() if key in selected_keys}


def preview_tables(
    workbook: Workbook,
    report_type: str,
    compare_version: Version | None,
    selected_parameter_keys: list[str] | None = None,
) -> list[dict]:
    current = snapshot_cells(workbook)
    baseline = json.loads(compare_version.snapshot_json) if compare_version else None
    obj = workbook.object
    cylinder = obj.cylinder or "ПЧ"
    turbine = obj.turbine or ""
    stages = _stage_columns(workbook)
    seals = _seal_columns(workbook)
    selected_keys = _selected(selected_parameter_keys)

    def matrix(title: str, specs: list[tuple[str, str]], cols: list[dict]) -> dict:
        rows = []
        for key, label in _filter_specs(specs, selected_keys):
            cells = []
            for col in cols:
                value = (current.get(key) or {}).get(col["key"]) or ""
                old = (baseline.get(key) or {}).get(col["key"]) if baseline else None
                fill = _fill_for(value, old, bool(value))
                cells.append(
                    {
                        "column_key": col["key"],
                        "value": value,
                        "changed": fill is not None,
                        "fill": fill,
                    }
                )
            rows.append({"parameter_key": key, "label": label, "cells": cells})
        return {"title": title, "columns": cols, "rows": rows}

    if report_type == "full":
        specs = [
            (item["key"], item["label"])
            for item in workbook_parameters(workbook)
            if item["row_kind"] != "section"
        ]
        return [matrix("Полная гранд-сводка ИД", specs, stages + seals)]
    return [
        matrix(
            "Диаметры концевых уплотнений",
            [("r098", "Диаметр бочки ротора, мм"), ("r099", "Количество дросселей"), ("r100", "Радиальный зазор, мм")],
            seals,
        ),
        matrix(
            f"Таблица 1 – Диафрагмы и направляющие лопатки {cylinder} {turbine}",
            SHORT_NOZZLE_ROWS,
            stages,
        ),
        matrix(
            f"Таблица 2 – Диски и рабочие лопатки {cylinder} {turbine}",
            SHORT_ROTOR_ROWS,
            stages,
        ),
    ]


def _write_matrix(
    document: Document,
    title: str,
    row_specs: list[tuple[str, str]],
    col_specs: list[dict],
    current: dict[str, dict[str, str | None]],
    baseline: dict[str, dict[str, str | None]] | None,
    links: dict[str, dict[str, str]] | None = None,
    shade: bool = False,
) -> None:
    if title:
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
            if shade:
                _set_cell_shading(cell, _fill_for(value, old, bool(value)))


def build_report_docx(
    session: Session,
    workbook: Workbook,
    report_type: str,
    compare_version: Version | None,
    extra_notes: str = "",
    selected_parameter_keys: list[str] | None = None,
    fields: dict | None = None,
) -> bytes:
    current = snapshot_cells(workbook)
    links = hyperlinks_map(workbook)
    baseline = json.loads(compare_version.snapshot_json) if compare_version else None
    obj = workbook.object
    selected_keys = _selected(selected_parameter_keys)
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    fields = fields or {}
    header = document.add_paragraph()
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.add_run(fields.get("recipient_block") or "СКБт\nОР").bold = True

    document.add_paragraph(fields.get("subject") or "Начальнику ОПТ")
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
    document.add_paragraph(fields.get("greeting") or f"Об ИД по ПЧ {cylinder} турбин {station} ({turbine})")
    document.add_paragraph(
        fields.get("narrative")
        or (
            f"Уважаемый И.О.!\nВ рамках конструкторской подготовки производства по турбинам {turbine} "
            f"для {station} направляем Вам предварительные данные для разработки чертежа проточной части "
            f"{cylinder}."
        )
    )
    document.add_paragraph(
        "В Приложении 1 представлены данные по основной геометрии направляющих лопаток (таблица 1), "
        "рабочих лопаток (таблица 2)."
    )

    notes = (extra_notes or fields.get("extra_notes") or "").strip()
    if notes:
        document.add_paragraph("Примечания")
        document.add_paragraph(notes)

    stages = _stage_columns(workbook)
    if report_type == "full":
        specs = [
            (item["key"], item["label"])
            for item in workbook_parameters(workbook)
            if item["row_kind"] != "section"
        ]
        _write_matrix(
            document,
            "Приложение 1 – Полная гранд-сводка ИД",
            _filter_specs(specs, selected_keys),
            stages + _seal_columns(workbook),
            current,
            baseline,
            links,
            shade=False,
        )
    else:
        _write_matrix(
            document,
            f"Таблица 1 – Данные по диафрагмам и направляющим лопаткам {cylinder} {turbine}",
            _filter_specs(SHORT_NOZZLE_ROWS, selected_keys),
            stages,
            current,
            baseline,
            links,
            shade=False,
        )
        rotor_rows = _filter_specs(SHORT_ROTOR_ROWS, selected_keys)
        if rotor_rows:
            _write_matrix(
                document,
                f"Таблица 2 – Данные по дискам и рабочим лопаткам {cylinder} {turbine}",
                rotor_rows,
                stages,
                current,
                baseline,
                links,
                shade=False,
            )

    footer = document.add_paragraph()
    footer.add_run(fields.get("signature_block") or "Начальник отдела").italic = True
    footer.add_run("\nИ.О.Ф.")
    note = document.add_paragraph()
    note.add_run("Жёлтый — изменение относительно выбранной версии; зелёный — новое значение. ").font.color.rgb = RGBColor(
        0x66, 0x66, 0x66
    )
    note.add_run("Комментарии в отчёт не включаются.")

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _factory_number(name: str) -> str:
    match = _FACTORY_NUMBER.search(name or "")
    return match.group(1).strip() if match else ""


def _table_caption(obj, table_number: int, group_title: str) -> str:
    turbine = (obj.turbine or "").strip()
    station = (obj.station or "").strip()
    factory = _factory_number(obj.name or "")
    tail = " ".join(part for part in (f"турбины {turbine}" if turbine else "", station) if part)
    if factory:
        tail = f"{tail} ({factory})".strip()
    caption = f"Таблица {table_number} – {group_title}"
    return f"{caption} {tail}".strip() if tail else caption


def _rows_for_export(parameters: list[dict], selected_keys: set[str]) -> list[dict]:
    sections = [index for index, item in enumerate(parameters) if item.get("row_kind") == "section"]
    spans: dict[int, int] = {}
    for position, index in enumerate(sections):
        indent = int(parameters[index].get("indent") or 0)
        end = len(parameters)
        for next_index in sections[position + 1 :]:
            if int(parameters[next_index].get("indent") or 0) <= indent:
                end = next_index
                break
        spans[index] = end
    included_sections = {
        index
        for index, end in spans.items()
        if any(
            parameters[row].get("row_kind") != "section" and parameters[row].get("key") in selected_keys
            for row in range(index + 1, end)
        )
    }
    rows: list[dict] = []
    for index, item in enumerate(parameters):
        if item.get("row_kind") == "section":
            if index in included_sections:
                rows.append(item)
        elif item.get("key") in selected_keys:
            rows.append(item)
    return rows


def _apply_a3_landscape(section) -> None:
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = _A3_LANDSCAPE_WIDTH
    section.page_height = _A3_LANDSCAPE_HEIGHT
    section.left_margin = Emu(_MARGIN_LR_EMU)
    section.right_margin = Emu(_MARGIN_LR_EMU)
    section.top_margin = Emu(_MARGIN_TB_EMU)
    section.bottom_margin = Emu(_MARGIN_TB_EMU)


def _max_stage_columns() -> int:
    remaining = _PAGE_CONTENT_TWIPS - _NAME_WIDTH - _DESIGNATION_WIDTH - _UNIT_WIDTH
    return max(1, remaining // _MIN_STAGE_WIDTH)


def _column_chunks(columns: list) -> list[list]:
    size = _max_stage_columns()
    return [columns[index : index + size] for index in range(0, len(columns), size)]


def _column_widths(stage_count: int) -> list[int]:
    name, designation, unit = _NAME_WIDTH, _DESIGNATION_WIDTH, _UNIT_WIDTH
    remaining = _PAGE_CONTENT_TWIPS - name - designation - unit
    count = max(stage_count, 1)
    share = remaining // count
    stage = share if share >= _MIN_STAGE_WIDTH else max(_MIN_STAGE_WIDTH, share)
    widths = [name, designation, unit] + [stage] * stage_count
    slack = _PAGE_CONTENT_TWIPS - sum(widths)
    if slack > 0:
        widths[-1] += slack
    return widths


def _cell_run(text: str, superscript: bool = False) -> object:
    run = OxmlElement("w:r")
    run_props = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), "Times New Roman")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "20")
    size_cs = OxmlElement("w:szCs")
    size_cs.set(qn("w:val"), "20")
    run_props.extend((fonts, size, size_cs))
    if superscript:
        align = OxmlElement("w:vertAlign")
        align.set(qn("w:val"), "superscript")
        run_props.append(align)
    run.append(run_props)
    text_el = OxmlElement("w:t")
    value = text or ""
    if value[:1].isspace() or value[-1:].isspace():
        text_el.set(qn("xml:space"), "preserve")
    text_el.text = value
    run.append(text_el)
    return run


def _write_table_cell(
    tc,
    text: str,
    width: int,
    fill: str | None = None,
    note_numbers: list[int] | None = None,
) -> None:
    for child in list(tc):
        if child.tag == qn("w:p"):
            tc.remove(child)
    paragraph = OxmlElement("w:p")
    paragraph_props = OxmlElement("w:pPr")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    paragraph_props.append(spacing)
    paragraph.append(paragraph_props)
    value = text or ""
    if value or not note_numbers:
        paragraph.append(_cell_run(value))
    for number in note_numbers or []:
        paragraph.append(_cell_run("*"))
        paragraph.append(_cell_run(str(number), superscript=True))
    tc.append(paragraph)
    tc_pr = tc.find(qn("w:tcPr"))
    if tc_pr is None:
        tc_pr = OxmlElement("w:tcPr")
        tc.insert(0, tc_pr)
    align = OxmlElement("w:vAlign")
    align.set(qn("w:val"), "center")
    tc_pr.append(align)
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width))
    tc_w.set(qn("w:type"), "dxa")
    if fill:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), fill)
        shading.set(qn("w:val"), "clear")
        tc_pr.append(shading)


def _fix_table_layout(table, widths: list[int]) -> None:
    tbl = table._tbl
    tbl_pr = tbl.find(qn("w:tblPr"))
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_w.set(qn("w:type"), "dxa")
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    grid = tbl.find(qn("w:tblGrid"))
    for column, width in zip(grid.findall(qn("w:gridCol")), widths):
        column.set(qn("w:w"), str(width))


def build_id_table_docx(
    workbook: Workbook,
    selected_parameter_keys: list[str],
    selected_column_keys: list[str],
    table_number: int = 1,
) -> bytes:
    if not selected_parameter_keys or not selected_column_keys:
        raise ValueError("Выберите строки и столбцы для экспорта")
    selected_keys = set(selected_parameter_keys)
    catalog = workbook_parameters(workbook)
    parameters = _rows_for_export(catalog, selected_keys)
    editable = [item for item in parameters if item.get("row_kind") != "section"]
    if not editable:
        raise ValueError("Нет выбранных параметров")
    columns = [item for item in workbook_columns(workbook) if item["key"] in set(selected_column_keys)]
    if not columns:
        raise ValueError("Нет выбранных столбцов")
    cells = {(cell.parameter_key, cell.column_key): cell for cell in effective_cells(workbook)}
    notes = report_notes(workbook)
    notes_by_cell: dict[tuple[str, str], list[int]] = {}
    for note in notes:
        notes_by_cell.setdefault((note["parameter_key"], note["column_key"]), []).append(note["number"])
    exported_notes = notes_for_export(notes, {item["key"] for item in parameters}, {item["key"] for item in columns})
    obj = workbook.object
    cylinder = obj.cylinder or "ЦСД"
    group_key = editable[0].get("group") or ""
    group_title = GROUP_TITLES.get(group_key, editable[0].get("label") or "таблица ИД").format(cylinder=cylinder)

    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)
    _apply_a3_landscape(document.sections[0])

    frozen_rows: list[list[str]] = []
    for parameter in parameters:
        section_row = parameter.get("row_kind") == "section"
        frozen_rows.append(
            [
                parameter_display_label(parameter),
                "" if section_row else parameter_designation(parameter),
                "" if section_row else (parameter.get("unit") or ""),
            ]
        )

    for chunk_index, chunk in enumerate(_column_chunks(columns)):
        caption = document.add_paragraph()
        caption.alignment = WD_ALIGN_PARAGRAPH.LEFT
        caption.paragraph_format.space_before = Pt(10 if chunk_index else 0)
        caption.paragraph_format.space_after = Pt(6)
        caption_text = (
            _table_caption(obj, table_number, group_title)
            if chunk_index == 0
            else f"Продолжение таблицы {table_number}"
        )
        _set_run_font(caption.add_run(caption_text), 12)
        _add_id_data_table(document, parameters, chunk, frozen_rows, cells, notes_by_cell)

    _add_report_note_list(document, exported_notes)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _add_id_data_table(
    document,
    parameters: list[dict],
    columns: list[dict],
    frozen_rows: list[list[str]],
    cells: dict,
    notes_by_cell: dict[tuple[str, str], list[int]] | None = None,
) -> None:
    notes_by_cell = notes_by_cell or {}
    widths = _column_widths(len(columns))
    table = document.add_table(rows=1 + len(parameters), cols=3 + len(columns))
    table.style = "Table Grid"
    _fix_table_layout(table, widths)
    header_row = [(text, None) for text in list(_FROZEN_HEADERS) + [column.get("label") or column["key"] for column in columns]]
    body = [header_row]
    for frozen, parameter in zip(frozen_rows, parameters):
        key = parameter.get("key") or ""
        section_row = parameter.get("row_kind") == "section"
        row = [
            (frozen[0], notes_by_cell.get((key, REPORT_NOTE_NAME))),
            (frozen[1], None),
            (frozen[2], notes_by_cell.get((key, REPORT_NOTE_UNIT))),
        ]
        for column in columns:
            cell = None if section_row else cells.get((parameter["key"], column["key"]))
            row.append(
                (
                    _display(cell) if cell else "",
                    None if section_row else notes_by_cell.get((parameter["key"], column["key"])),
                )
            )
        body.append(row)
    for row_index, row in enumerate(body):
        fill = HEADER_FILL if row_index == 0 or parameters[row_index - 1].get("row_kind") == "section" else None
        for tc, (text, numbers), width in zip(table._tbl.tr_lst[row_index].tc_lst, row, widths):
            _write_table_cell(tc, text or "", width, fill, numbers)


def _add_report_note_list(document, notes: list[dict]) -> None:
    if not notes:
        return
    spacer = document.add_paragraph()
    spacer.paragraph_format.space_before = Pt(8)
    spacer.paragraph_format.space_after = Pt(2)
    _set_run_font(spacer.add_run("Примечания"), 11)
    for note in notes:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(2)
        _set_run_font(paragraph.add_run(f"*{note['number']} {note['text']}"), 10)
